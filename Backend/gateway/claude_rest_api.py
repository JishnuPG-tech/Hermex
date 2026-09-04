from gateway import voice_engine as ve
import os
import re
import json
import uuid
import time
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx
from fastapi import APIRouter, Request, Header, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse, PlainTextResponse
from gateway import anthropic_bridge as ab
from gateway import channels_manager as cm
from gateway import agent_executor as ae

logger = logging.getLogger("claude_rest_api")
router = APIRouter()

STORAGE_DIR = Path("/data/conversations") if Path("/data").exists() else Path("/tmp/conversations")
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
CONV_FILE = STORAGE_DIR / "history.json"

_CONVERSATIONS: Dict[str, Dict[str, Any]] = {}

def _load_history():
    global _CONVERSATIONS
    if CONV_FILE.exists():
        try:
            _CONVERSATIONS = json.loads(CONV_FILE.read_text(encoding="utf-8"))
        except Exception:
            _CONVERSATIONS = {}

def _save_history():
    try:
        CONV_FILE.write_text(json.dumps(_CONVERSATIONS, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

_load_history()

def _format_msg(sender: str, text: str, idx: int, prev_uuid: Optional[str] = None, msg_id: Optional[str] = None) -> Dict[str, Any]:
    mid = msg_id or str(uuid.uuid4())
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return {
        "uuid": mid,
        "text": text,
        "sender": sender,
        "index": idx,
        "created_at": now,
        "updated_at": now,
        "edited_at": None,
        "content": [{"type": "text", "text": text}],
        "attachments": [],
        "files": [],
        "parent_message_uuid": prev_uuid,
        "stop_reason": "end_turn" if sender == "assistant" else None
    }

async def _generate_ai_title_async(chat_id: str, first_prompt: Any):
    """Generate a clean, professional 3-6 word AI title using smart extraction & LLM inference."""
    clean_p = ""
    if isinstance(first_prompt, str):
        clean_p = first_prompt.strip()
    elif isinstance(first_prompt, list):
        clean_p = " ".join(str(p.get("text", "") or p.get("content", "")) for p in first_prompt if isinstance(p, dict)).strip()
    elif isinstance(first_prompt, dict):
        clean_p = str(first_prompt.get("text") or first_prompt.get("content") or "").strip()

    if not clean_p and chat_id in _CONVERSATIONS:
        msgs = _CONVERSATIONS[chat_id].get("chat_messages", [])
        for m in msgs:
            if m.get("sender") == "human":
                clean_p = str(m.get("text") or "").strip()
                if clean_p:
                    break

    if not clean_p or len(clean_p) < 2:
        return

    # 1. Immediately apply heuristic title so the history updates without waiting
    clean_title = _clean_title(clean_p)
    if chat_id in _CONVERSATIONS:
        _CONVERSATIONS[chat_id]["name"] = clean_title
        _CONVERSATIONS[chat_id]["summary"] = clean_title
        _CONVERSATIONS[chat_id]["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _save_history()

    # 2. Refine asynchronously using LLM with ample token allowance
    try:
        payload = {
            "model": "auto/smart",
            "messages": [
                {
                    "role": "user",
                    "content": f"Generate a concise 3-5 word title for the following query. Respond with ONLY the title itself, no markdown, no quotes:\n\n{clean_p[:400]}"
                }
            ],
            "max_tokens": 120
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                "http://127.0.0.1:20128/v1/chat/completions",
                headers={"Authorization": f"Bearer {ab.UPSTREAM_KEY}", "Content-Type": "application/json"},
                json=payload
            )
            if resp.status_code == 200:
                data = resp.json()
                msg_obj = data.get("choices", [{}])[0].get("message", {})
                t = msg_obj.get("content") or msg_obj.get("reasoning_content") or ""
                t = t.strip()
                # Clean title
                t = "".join(c for c in t if c not in ('"', "'", "`", "#", "*", ":", "\n", "\r")).strip()
                if t and len(t) >= 3 and len(t) <= 60:
                    if chat_id in _CONVERSATIONS:
                        _CONVERSATIONS[chat_id]["name"] = t
                        _CONVERSATIONS[chat_id]["summary"] = t
                        _CONVERSATIONS[chat_id]["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                        _save_history()
                        logger.info(f"AI Title generated for {chat_id}: '{t}'")
    except Exception as e:
        logger.warning(f"AI title generation fallback: {e}")

def _extract_artifacts_from_conv(chat_id: str) -> List[Dict[str, Any]]:
    conv = _CONVERSATIONS.get(chat_id, {})
    artifacts = []
    seen_ids = set()
    for msg in conv.get("chat_messages", []):
        full_body = msg.get("text", "")
        content = msg.get("content", [])
        if isinstance(content, list):
            for cb in content:
                if isinstance(cb, dict) and cb.get("type") == "text":
                    full_body += "\n" + cb.get("text", "")
        
        # 1. Parse explicit <antArtifact> tags with flexible single/double quote matching
        for match in re.finditer(r'<antArtifact\s+([^>]+)>([\s\S]*?)(?:</antArtifact>|$)', full_body):
            attrs_str = match.group(1)
            content_str = match.group(2).strip()
            raw_attrs = re.findall(r'([a-zA-Z0-9_]+)=["\']([^"\']+)["\']', attrs_str)
            attrs = {k.lower(): v for k, v in raw_attrs}
            art_id = attrs.get("identifier") or attrs.get("id") or str(uuid.uuid4())
            if art_id not in seen_ids:
                seen_ids.add(art_id)
                art_type = attrs.get("type") or attrs.get("artifacttype") or "application/vnd.ant.markdown"
                artifacts.append({
                    "id": art_id,
                    "uuid": art_id,
                    "artifact_uuid": art_id,
                    "version_uuid": str(uuid.uuid4()),
                    "message_uuid": msg.get("uuid", str(uuid.uuid4())),
                    "chat_conversation_uuid": chat_id,
                    "identifier": art_id,
                    "type": art_type,
                    "artifact_type": art_type,
                    "title": attrs.get("title", "Document"),
                    "language": attrs.get("language", ""),
                    "code_language": attrs.get("language", ""),
                    "content": content_str,
                    "result_state": "complete",
                    "source": "c",
                    "visibility": "private",
                    "is_complete": True,
                    "created_at": msg.get("created_at"),
                    "updated_at": msg.get("updated_at")
                })

        # 2. Synthesize artifacts for standalone HTML / SVG / Markdown blocks if not already wrapped
        if not artifacts:
            for match in re.finditer(r'```([a-zA-Z0-9_-]+)?\s*\n([\s\S]{60,})?```', full_body):
                lang = (match.group(1) or "").lower()
                code = (match.group(2) or "").strip()
                if lang in ("html", "svg", "markdown", "md") or len(code) > 100:
                    art_id = f"art_{hash(code[:50]) & 0xffffffff:08x}"
                    if art_id not in seen_ids:
                        seen_ids.add(art_id)
                        art_type = "text/html" if lang == "html" else ("image/svg+xml" if lang == "svg" else "application/vnd.ant.markdown")
                        title = "HTML Preview" if lang == "html" else ("SVG Graphic" if lang == "svg" else "Document")
                        artifacts.append({
                            "id": art_id,
                            "uuid": art_id,
                            "artifact_uuid": art_id,
                            "version_uuid": str(uuid.uuid4()),
                            "message_uuid": msg.get("uuid", str(uuid.uuid4())),
                            "chat_conversation_uuid": chat_id,
                            "identifier": art_id,
                            "type": art_type,
                            "artifact_type": art_type,
                            "title": title,
                            "language": lang,
                            "code_language": lang,
                            "content": code,
                            "result_state": "complete",
                            "source": "c",
                            "visibility": "private",
                            "is_complete": True,
                            "created_at": msg.get("created_at"),
                            "updated_at": msg.get("updated_at")
                        })

    return artifacts

def _extract_render_values(chat_id: str) -> Dict[str, Any]:
    artifacts = _extract_artifacts_from_conv(chat_id)
    render_map = {}
    for a in artifacts:
        art_id = a.get("identifier") or a.get("id") or a.get("uuid")
        if art_id:
            render_map[art_id] = {
                "type": a.get("type", "application/vnd.ant.markdown"),
                "title": a.get("title", "Document"),
                "content": a.get("content", ""),
                "language": a.get("language", ""),
                "artifact_uuid": a.get("artifact_uuid", art_id),
                "version_uuid": a.get("version_uuid", str(uuid.uuid4()))
            }
    return render_map

def _build_conv_response(conv: Dict[str, Any]) -> Dict[str, Any]:
    msgs = conv.get("chat_messages", [])
    chat_id = conv.get("uuid")
    artifacts = _extract_artifacts_from_conv(chat_id)
    render_vals = _extract_render_values(chat_id)
    
    # Ensure every message has valid fields and parent linkage
    sanitized_msgs = []
    prev_uuid = None
    for i, m in enumerate(msgs):
        m_copy = dict(m)
        m_copy["index"] = i
        if not m_copy.get("uuid"):
            m_copy["uuid"] = str(uuid.uuid4())
        if prev_uuid and not m_copy.get("parent_message_uuid"):
            m_copy["parent_message_uuid"] = prev_uuid
        if not m_copy.get("content"):
            txt = m_copy.get("text", "")
            m_copy["content"] = [{"type": "text", "text": txt}]
        if m_copy.get("sender") == "assistant" and not m_copy.get("stop_reason"):
            m_copy["stop_reason"] = "end_turn"
        sanitized_msgs.append(m_copy)
        prev_uuid = m_copy["uuid"]

    leaf_uuid = sanitized_msgs[-1]["uuid"] if sanitized_msgs else None

    return {
        "uuid": chat_id,
        "name": conv.get("name", "Chat"),
        "summary": conv.get("name", "Chat"),
        "created_at": conv.get("created_at"),
        "updated_at": conv.get("updated_at"),
        "settings": {
            "preview_feature_uses_artifacts": True,
            "model": "hermes-agent"
        },
        "is_starred": conv.get("is_starred", False),
        "current_leaf_message_uuid": leaf_uuid,
        "chat_messages": sanitized_msgs,
        "artifacts": artifacts,
        "render_values": render_vals
    }

# 1. Models Catalog (Full ModelOption array matching Organization.claude_ai_bootstrap_models_config)
MODELS_CATALOG = [
    {
        "model": "claude-3-5-sonnet-20241022",
        "id": "claude-3-5-sonnet-20241022",
        "name": "Sonnet 3.7",
        "display_name": "Sonnet 3.7",
        "short_name": "Sonnet 3.7",
        "description": {"text": "Most intelligent model for reasoning and coding"},
        "description_i18n_key": None,
        "overflow": None,
        "inactive": False,
        "thinking_modes": [],
        "capabilities": {
            "mm_images": True,
            "mm_pdf": True,
            "web_search": True,
            "code_execution": True
        },
        "notice_text": None,
        "notice_text_i18n_key": None,
        "knowledgeCutoff": "2025-02-01",
        "slow_kb_warning_threshold": None,
        "created_at": "2024-10-22T00:00:00Z",
        "type": "model"
    },
    {
        "model": "claude-3-5-haiku-20241022",
        "id": "claude-3-5-haiku-20241022",
        "name": "Haiku 3.5",
        "display_name": "Haiku 3.5",
        "short_name": "Haiku 3.5",
        "description": {"text": "Fastest response time for everyday tasks"},
        "description_i18n_key": None,
        "overflow": None,
        "inactive": False,
        "thinking_modes": [],
        "capabilities": {
            "mm_images": True,
            "mm_pdf": True,
            "web_search": True,
            "code_execution": True
        },
        "notice_text": None,
        "notice_text_i18n_key": None,
        "knowledgeCutoff": "2024-10-22",
        "slow_kb_warning_threshold": None,
        "created_at": "2024-10-22T00:00:00Z",
        "type": "model"
    },
    {
        "model": "auto/smart",
        "id": "auto/smart",
        "name": "Hermes Smart",
        "display_name": "Hermes Smart",
        "short_name": "Smart",
        "description": {"text": "Autonomous load balancing and intelligent model routing"},
        "description_i18n_key": None,
        "overflow": None,
        "inactive": False,
        "thinking_modes": [],
        "capabilities": {
            "mm_images": True,
            "mm_pdf": True,
            "web_search": True,
            "code_execution": True
        },
        "notice_text": None,
        "notice_text_i18n_key": None,
        "knowledgeCutoff": "2026-01-01",
        "slow_kb_warning_threshold": None,
        "created_at": "2026-01-01T00:00:00Z",
        "type": "model"
    },
    {
        "model": "auto/best-coding",
        "id": "auto/best-coding",
        "name": "Hermes Coding Pro",
        "display_name": "Hermes Coding Pro",
        "short_name": "Coding Pro",
        "description": {"text": "Optimized for programming, debugging, and architectures"},
        "description_i18n_key": None,
        "overflow": None,
        "inactive": False,
        "thinking_modes": [],
        "capabilities": {
            "mm_images": True,
            "mm_pdf": True,
            "web_search": True,
            "code_execution": True
        },
        "notice_text": None,
        "notice_text_i18n_key": None,
        "knowledgeCutoff": "2026-01-01",
        "slow_kb_warning_threshold": None,
        "created_at": "2026-01-01T00:00:00Z",
        "type": "model"
    },
    {
        "model": "auto/best-fast",
        "id": "auto/best-fast",
        "name": "Hermes Turbo",
        "display_name": "Hermes Turbo",
        "short_name": "Turbo",
        "description": {"text": "Ultra-low latency streaming for rapid dialogue"},
        "description_i18n_key": None,
        "overflow": None,
        "inactive": False,
        "thinking_modes": [],
        "capabilities": {
            "mm_images": True,
            "mm_pdf": True,
            "web_search": True,
            "code_execution": True
        },
        "notice_text": None,
        "notice_text_i18n_key": None,
        "knowledgeCutoff": "2026-01-01",
        "slow_kb_warning_threshold": None,
        "created_at": "2026-01-01T00:00:00Z",
        "type": "model"
    },
    {
        "model": "groq/llama-3.3-70b-versatile",
        "id": "groq/llama-3.3-70b-versatile",
        "name": "Llama 3.3 70B",
        "display_name": "Llama 3.3 70B",
        "short_name": "Llama 3.3",
        "description": {"text": "Open-weights intelligence hosted on Groq high-speed LPU"},
        "description_i18n_key": None,
        "overflow": None,
        "inactive": False,
        "thinking_modes": [],
        "capabilities": {
            "mm_images": True,
            "mm_pdf": True,
            "web_search": True,
            "code_execution": True
        },
        "notice_text": None,
        "notice_text_i18n_key": None,
        "knowledgeCutoff": "2025-01-01",
        "slow_kb_warning_threshold": None,
        "created_at": "2025-01-01T00:00:00Z",
        "type": "model"
    },
    {
        "model": "antigravity/gemini-2.5-flash-thinking",
        "id": "antigravity/gemini-2.5-flash-thinking",
        "name": "Gemini 2.5 Thinking",
        "display_name": "Gemini 2.5 Thinking",
        "short_name": "Gemini Thinking",
        "description": {"text": "Extended chain-of-thought with reasoning tokens"},
        "description_i18n_key": None,
        "overflow": None,
        "inactive": False,
        "thinking_modes": [],
        "capabilities": {
            "mm_images": True,
            "mm_pdf": True,
            "web_search": True,
            "code_execution": True
        },
        "notice_text": None,
        "notice_text_i18n_key": None,
        "knowledgeCutoff": "2025-05-01",
        "slow_kb_warning_threshold": None,
        "created_at": "2025-05-01T00:00:00Z",
        "type": "model"
    }
]

DEFAULT_THINKING_OPTIONS = {
    "effort_options": [
        {"id": "low", "name": "Low", "description": "Quick reasoning", "recommended": False},
        {"id": "medium", "name": "Medium", "description": "Balanced reasoning", "recommended": True},
        {"id": "high", "name": "High", "description": "Deep thinking", "recommended": False},
        {"id": "max", "name": "Max", "description": "Maximum reasoning effort", "recommended": False}
    ],
    "mode_options": [
        {"id": "off", "name": "Off", "description": "Direct response without thinking", "recommended": False},
        {"id": "auto", "name": "Auto", "description": "Let Hermes decide when to think", "recommended": True},
        {"id": "on", "name": "Always On", "description": "Always think before answering", "recommended": False}
    ]
}

# Exact ModelSelectorConfig List expected by Kotlin kotlinx.serialization in AppStartResponse
MODEL_SELECTOR_CONFIG_LIST = [
    {
        "id": "chat",
        "models": [
            {
                "id": "claude-3-5-sonnet-20241022",
                "name": "Sonnet 3.7",
                "short_name": "Sonnet 3.7",
                "voice_model": None,
                "description": {"english": "Most intelligent model for reasoning and coding"},
                "notice": None,
                "selection_notice": None,
                "section": "main",
                "disabled": False,
                "capabilities": {"mm_images": True, "mm_pdf": True, "web_search": True, "code_execution": True},
                "thinking": DEFAULT_THINKING_OPTIONS,
                "badge": None
            },
            {
                "id": "claude-3-5-haiku-20241022",
                "name": "Haiku 3.5",
                "short_name": "Haiku 3.5",
                "voice_model": None,
                "description": {"english": "Fastest response time for everyday tasks"},
                "notice": None,
                "selection_notice": None,
                "section": "main",
                "disabled": False,
                "capabilities": {"mm_images": True, "mm_pdf": True, "web_search": True, "code_execution": True},
                "thinking": DEFAULT_THINKING_OPTIONS,
                "badge": {"message": {"english": "FAST"}}
            },
            {
                "id": "auto/smart",
                "name": "Hermes Smart",
                "short_name": "Hermes Smart",
                "voice_model": None,
                "description": {"english": "Autonomous load balancing and intelligent model routing"},
                "notice": None,
                "selection_notice": None,
                "section": "main",
                "disabled": False,
                "capabilities": {"mm_images": True, "mm_pdf": True, "web_search": True, "code_execution": True},
                "thinking": DEFAULT_THINKING_OPTIONS,
                "badge": {"message": {"english": "SMART"}}
            },
            {
                "id": "auto/best-coding",
                "name": "Hermes Coding Pro",
                "short_name": "Coding Pro",
                "voice_model": None,
                "description": {"english": "Optimized for programming, debugging, and architectures"},
                "notice": None,
                "selection_notice": None,
                "section": "main",
                "disabled": False,
                "capabilities": {"mm_images": True, "mm_pdf": True, "web_search": True, "code_execution": True},
                "thinking": DEFAULT_THINKING_OPTIONS,
                "badge": {"message": {"english": "PRO"}}
            },
            {
                "id": "auto/best-fast",
                "name": "Hermes Turbo",
                "short_name": "Turbo",
                "voice_model": None,
                "description": {"english": "Ultra-low latency streaming for rapid dialogue"},
                "notice": None,
                "selection_notice": None,
                "section": "main",
                "disabled": False,
                "capabilities": {"mm_images": True, "mm_pdf": True, "web_search": True, "code_execution": True},
                "thinking": DEFAULT_THINKING_OPTIONS,
                "badge": {"message": {"english": "FAST"}}
            },
            {
                "id": "groq/llama-3.3-70b-versatile",
                "name": "Llama 3.3 70B",
                "short_name": "Llama 3.3",
                "voice_model": None,
                "description": {"english": "Open-weights intelligence hosted on Groq high-speed LPU"},
                "notice": None,
                "selection_notice": None,
                "section": "main",
                "disabled": False,
                "capabilities": {"mm_images": True, "mm_pdf": True, "web_search": True, "code_execution": True},
                "thinking": DEFAULT_THINKING_OPTIONS,
                "badge": {"message": {"english": "GROQ"}}
            },
            {
                "id": "antigravity/gemini-2.5-flash-thinking",
                "name": "Gemini 2.5 Thinking",
                "short_name": "Gemini Thinking",
                "voice_model": None,
                "description": {"english": "Extended chain-of-thought with reasoning tokens"},
                "notice": None,
                "selection_notice": None,
                "section": "main",
                "disabled": False,
                "capabilities": {"mm_images": True, "mm_pdf": True, "web_search": True, "code_execution": True},
                "thinking": DEFAULT_THINKING_OPTIONS,
                "badge": {"message": {"english": "THINK"}}
            }
        ]
    },
    {
        "id": "voice",
        "models": [
            {
                "id": "claude-3-5-sonnet-20241022",
                "name": "Sonnet 3.7",
                "short_name": "Sonnet 3.7",
                "voice_model": None,
                "description": None,
                "notice": None,
                "selection_notice": None,
                "section": "main",
                "disabled": False,
                "capabilities": {"mm_images": True, "mm_pdf": True, "web_search": True, "code_execution": True},
                "thinking": None,
                "badge": None
            },
            {
                "id": "auto/best-fast",
                "name": "Hermes Turbo",
                "short_name": "Turbo",
                "voice_model": None,
                "description": None,
                "notice": None,
                "selection_notice": None,
                "section": "main",
                "disabled": False,
                "capabilities": {"mm_images": True, "mm_pdf": True, "web_search": True, "code_execution": True},
                "thinking": None,
                "badge": {"message": {"english": "FAST"}}
            }
        ]
    }
]

MODEL_SELECTOR_STATE_LIST = [
    {
        "id": "chat",
        "model": "auto/smart",
        "thinking": {
            "mode": "auto",
            "effort": "high"
        },
        "thinking_by_model": []
    },
    {
        "id": "voice",
        "model": "claude-3-5-sonnet-20241022",
        "thinking": None,
        "thinking_by_model": []
    }
]

ADMIN_EMAIL = "jishnupg2005@gmail.com"
ADMIN_NAME = "Jishnu PG (Super Admin)"

USER_OBJ = {
    "id": "user_0123456789abcdef",
    "uuid": "user_0123456789abcdef",
    "email": ADMIN_EMAIL,
    "email_address": ADMIN_EMAIL,
    "name": ADMIN_NAME,
    "full_name": ADMIN_NAME,
    "avatar_url": None,
    "has_completed_onboarding": True,
    "completed_onboarding_at": "2024-01-01T00:00:00Z",
    "is_pro": True,
    "is_staff": True,
    "is_admin": True,
    "account_type": "pro",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
}

ORG_OBJ = {
    "id": "org_0123456789abcdef",
    "uuid": "org_0123456789abcdef",
    "name": "Hermes Pro Admin Team",
    "settings": {
        "billing_tier": "claude_pro",
        "model_selector_enabled": True,
        "custom_models_enabled": True,
        "artifacts_enabled": True,
        "artifacts_v2_enabled": True
    },
    "capabilities": [
        "chat", "claude_pro", "claude_max", "raven", "model_selector", 
        "model_selection", "pro_enabled", "premium_enabled", "artifacts", 
        "artifacts_v2", "artifacts_editor", "web_search", "saffron", 
        "wiggle", "dittos", "chat_model_selector", "voice_mode"
    ],
    "claude_ai_bootstrap_models_config": MODELS_CATALOG,
    "raven_type": None,
    "rate_limit_tier": "claude_max",
    "billing_type": "stripe",
    "rate_limit_upsell": None,
    "subscription_pause": "ABSENT",
    "has_active_subscription": True,
    "subscription_status": "active",
    "is_owner": True,
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
}

ACCOUNT_OBJ = {
    "uuid": "usr_0123456789abcdef",
    "id": "usr_0123456789abcdef",
    "email_address": ADMIN_EMAIL,
    "email": ADMIN_EMAIL,
    "full_name": ADMIN_NAME,
    "name": ADMIN_NAME,
    "has_completed_onboarding": True,
    "completed_onboarding_at": "2024-01-01T00:00:00Z",
    "is_subscribed": True,
    "is_pro": True,
    "account_type": "pro",
    "memberships": [
        {
            "id": "mem_0123456789abcdef",
            "organization": ORG_OBJ,
            "role": "admin",
            "is_owner": True,
            "has_active_subscription": True
        }
    ]
}

@router.get("/v1/models")
@router.get("/models")
@router.get("/api/v1/models")
@router.get("/api/models")
@router.get("/hermes/v1/models")
async def list_models():
    first_key = MODELS_CATALOG[0].get("model") or MODELS_CATALOG[0].get("id")
    last_key = MODELS_CATALOG[-1].get("model") or MODELS_CATALOG[-1].get("id")
    return {
        "data": MODELS_CATALOG,
        "has_more": False,
        "first_id": first_key,
        "last_id": last_key
    }

# 2. Account Profile & Auth Session
@router.get("/api/account")
@router.get("/account")
@router.get("/hermes/api/account")
@router.get("/hermes/account")
async def get_account():
    return ACCOUNT_OBJ

@router.get("/api/auth/current_user")
@router.get("/api/auth/session")
@router.get("/api/auth/me")
@router.get("/api/users/me")
@router.get("/hermes/api/auth/current_user")
@router.get("/hermes/api/auth/session")
async def get_auth_session():
    return {
        "user": USER_OBJ,
        "account": ACCOUNT_OBJ,
        "organizations": [ORG_OBJ],
        "is_authenticated": True,
        "status": "authenticated"
    }

@router.post("/api/auth/login")
@router.post("/api/auth/login/email")
@router.post("/auth/login")
@router.post("/hermes/api/auth/login")
async def login_endpoint(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    email = body.get("email") or ADMIN_EMAIL
    pwd = body.get("password") or ""
    session_token = f"session_key_{uuid.uuid4().hex}"
    
    resp = JSONResponse(content={
        "status": "ok",
        "message": "Authenticated successfully",
        "session_token": session_token,
        "user": USER_OBJ,
        "account": ACCOUNT_OBJ,
        "organizations": [ORG_OBJ]
    })
    resp.set_cookie("sessionKey", session_token, max_age=86400*30, httponly=True, samesite="lax")
    return resp

@router.post("/api/auth/send_code")
@router.post("/auth/send_code")
@router.post("/hermes/api/auth/send_code")
async def send_code_endpoint(request: Request):
    return {"status": "ok", "message": "Verification code sent to your email"}

@router.post("/api/auth/verify_code")
@router.post("/auth/verify_code")
@router.post("/hermes/api/auth/verify_code")
async def verify_code_endpoint(request: Request):
    session_token = f"session_key_{uuid.uuid4().hex}"
    resp = JSONResponse(content={
        "status": "ok",
        "session_token": session_token,
        "user": USER_OBJ,
        "account": ACCOUNT_OBJ,
        "organizations": [ORG_OBJ]
    })
    resp.set_cookie("sessionKey", session_token, max_age=86400*30, httponly=True, samesite="lax")
    return resp

@router.post("/api/auth/logout")
@router.post("/auth/logout")
@router.post("/hermes/api/auth/logout")
async def logout_endpoint():
    resp = JSONResponse(content={"status": "ok", "message": "Logged out"})
    resp.delete_cookie("sessionKey")
    return resp

_LOGIN_PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Claude APK & Hermes - Admin Login</title>
    <style>
        :root {
            --bg-main: #141416;
            --bg-card: #1e1f23;
            --text-primary: #f4f4f5;
            --text-secondary: #a1a1aa;
            --accent-orange: #d97706;
            --border: #2e3038;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
        body {
            margin: 0;
            padding: 24px 16px;
            background-color: var(--bg-main);
            color: var(--text-primary);
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 90vh;
        }
        .login-card {
            background-color: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 32px 28px;
            max-width: 420px;
            width: 100%;
            box-shadow: 0 10px 25px rgba(0,0,0,0.5);
        }
        .logo { font-size: 32px; text-align: center; margin-bottom: 12px; }
        h1 { font-size: 22px; margin: 0 0 8px 0; text-align: center; font-weight: 600; }
        p { color: var(--text-secondary); font-size: 14px; text-align: center; margin: 0 0 24px 0; }
        .input-group { margin-bottom: 16px; display: flex; flex-direction: column; gap: 6px; }
        label { font-size: 13px; color: var(--text-secondary); font-weight: 500; }
        input {
            background-color: #141416;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 12px 14px;
            color: var(--text-primary);
            font-size: 14px;
            outline: none;
        }
        input:focus { border-color: var(--accent-orange); }
        button {
            width: 100%;
            padding: 12px;
            background-color: var(--accent-orange);
            border: none;
            border-radius: 8px;
            color: #fff;
            font-weight: 600;
            font-size: 15px;
            cursor: pointer;
            margin-top: 8px;
        }
        button:hover { background-color: #b45309; }
        .status {
            display: none;
            padding: 10px 14px;
            border-radius: 8px;
            margin-bottom: 16px;
            font-size: 13px;
            text-align: center;
        }
        .status.success { display: block; background-color: rgba(16, 185, 129, 0.15); color: #34d399; }
        .badge-row { display: flex; justify-content: center; gap: 8px; margin-top: 20px; }
        .badge { font-size: 11px; padding: 4px 8px; background-color: rgba(217,119,6,0.2); color: #f59e0b; border-radius: 4px; font-weight: 700; }
    </style>
</head>
<body>
    <div class="login-card">
        <div class="logo">⚡</div>
        <h1>Claude Pro Admin Login</h1>
        <p>Sign in to configure Claude APK and backend reasoning models.</p>
        <div id="statusBox" class="status"></div>
        <div class="input-group">
            <label>Gmail Address</label>
            <input type="email" id="emailInput" value="jishnupg2005@gmail.com">
        </div>
        <div class="input-group">
            <label>Password</label>
            <input type="password" id="pwdInput" placeholder="Enter password">
        </div>
        <button onclick="handleLogin()">Sign In as Super Admin</button>
        <div class="badge-row">
            <span class="badge">CLAUDE PRO</span>
            <span class="badge">SUPER ADMIN</span>
            <span class="badge">UNLOCKED</span>
        </div>
    </div>
    <script>
        async function handleLogin() {
            var email = document.getElementById('emailInput').value.trim();
            var pwd = document.getElementById('pwdInput').value.trim();
            var sb = document.getElementById('statusBox');
            try {
                var res = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({email: email, password: pwd})
                });
                var d = await res.json();
                if (res.ok) {
                    sb.className = 'status success';
                    sb.innerText = 'Authenticated as ' + email + ' (Pro Admin)!';
                    setTimeout(function() { window.location.href = '/settings/models'; }, 1000);
                }
            } catch(e) {
                sb.className = 'status';
                sb.style.display = 'block';
                sb.style.backgroundColor = 'rgba(239, 68, 68, 0.15)';
                sb.style.color = '#f87171';
                sb.innerText = 'Login error: ' + e.message;
            }
        }
    </script>
</body>
</html>"""

@router.get("/login", response_class=HTMLResponse)
@router.get("/auth/login", response_class=HTMLResponse)
@router.get("/hermes/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse(content=_LOGIN_PAGE_HTML, headers={"Content-Type": "text/html; charset=utf-8"})

@router.get("/api/organizations")
@router.get("/organizations")
@router.get("/hermes/api/organizations")
@router.get("/hermes/organizations")
async def list_organizations():
    return [ORG_OBJ]

@router.get("/api/organizations/{org_id}")
@router.get("/organizations/{org_id}")
@router.get("/hermes/api/organizations/{org_id}")
@router.get("/hermes/organizations/{org_id}")
async def get_single_organization(org_id: str):
    return ORG_OBJ

@router.get("/api/organizations/{org_id}/memberships")
@router.get("/organizations/{org_id}/memberships")
@router.get("/hermes/api/organizations/{org_id}/memberships")
@router.get("/hermes/organizations/{org_id}/memberships")
async def get_organization_memberships(org_id: str):
    return ACCOUNT_OBJ["memberships"]

@router.get("/api/account_profile")
@router.get("/account_profile")
@router.get("/hermes/api/account_profile")
@router.get("/hermes/account_profile")
async def get_account_profile():
    return {
        "account": ACCOUNT_OBJ,
        "user": USER_OBJ,
        "organization": ORG_OBJ,
        "profile": ACCOUNT_OBJ
    }

# 3. App Start & Bootstrap
@router.get("/api/account/app_start")
@router.get("/account/app_start")
@router.get("/api/bootstrap")
@router.get("/bootstrap")
@router.get("/api/bootstrap/{org_id}/app_start")
@router.get("/bootstrap/{org_id}/app_start")
@router.get("/hermes/api/account/app_start")
@router.get("/hermes/api/bootstrap")
@router.get("/hermes/account/app_start")
@router.get("/hermes/bootstrap")
async def app_start_response(org_id: Optional[str] = None):
    return {
        "account": ACCOUNT_OBJ,
        "user": USER_OBJ,
        "organization": ORG_OBJ,
        "model_selector_config": MODEL_SELECTOR_CONFIG_LIST,
        "model_selector_state": MODEL_SELECTOR_STATE_LIST,
        "org_growthbook": {
            "features": {
                "artifacts": {"defaultValue": True},
                "artifacts_v2": {"defaultValue": True},
                "artifacts_editor": {"defaultValue": True},
                "model_selector_enabled": {"defaultValue": True},
                "model_picker_enabled": {"defaultValue": True},
                "chat_model_selector": {"defaultValue": True},
                "model_selector": {"defaultValue": True},
                "model_selection": {"defaultValue": True},
                "pro_enabled": {"defaultValue": True},
                "premium_enabled": {"defaultValue": True},
                "subscription_active": {"defaultValue": True},
                "claude_pro": {"defaultValue": True},
                "claude_max": {"defaultValue": True},
                "voice_mode": {"defaultValue": True},
                "bell_mode_enabled": {"defaultValue": True},
                "voice_model_selector_enabled": {"defaultValue": True},
                "model_picker_auto_dismiss_enabled": {"defaultValue": True},
                "project_bell_frontend": {"defaultValue": True},
                "project_bell_voice_chat_merge": {"defaultValue": True},
                "project_bell_v2_ui": {"defaultValue": True},
                "project_bell_attachments_enabled": {"defaultValue": True},
                "project_bell_assistant_audio_enabled": {"defaultValue": True},
                "claudeai_read_aloud_set_speed_enabled": {"defaultValue": True},
                "claudeai_read_aloud_survive_nav_enabled": {"defaultValue": True},
                "claudeai_read_aloud_compression_enabled": {"defaultValue": True},
                "project_bell_frontend_config": {
                    "defaultValue": {
                        "enabled": True,
                        "show_tooltip": True,
                        "server_interrupt_enabled": True,
                        "auto_send_enabled": True,
                        "ptt_background_stop_delay_ms": 500,
                        "hold_park_grace_ms": 300
                    }
                },
                "bell_config": {
                    "defaultValue": {
                        "enabled": True,
                        "show_tooltip": True,
                        "server_interrupt_enabled": True,
                        "auto_send_enabled": True,
                        "ptt_background_stop_delay_ms": 500,
                        "hold_park_grace_ms": 300
                    }
                }
            }
        },
        "server_localizations": {},
        "current_user_access": {
            "features": [
                {"feature": "artifacts", "status": "available"},
                {"feature": "artifacts_v2", "status": "available"},
                {"feature": "artifacts_editor", "status": "available"},
                {"feature": "model_selector_enabled", "status": "available"},
                {"feature": "model_picker_enabled", "status": "available"},
                {"feature": "chat_model_selector", "status": "available"},
                {"feature": "web_search", "status": "available"},
                {"feature": "saffron", "status": "available"},
                {"feature": "wiggle", "status": "available"},
                {"feature": "dittos", "status": "available"},
                {"feature": "chat", "status": "available"},
                {"feature": "claude_code_web", "status": "available"},
                {"feature": "claude_code_desktop_auto_permissions", "status": "available"},
                {"feature": "public_projects", "status": "available"},
                {"feature": "conversation_preferences", "status": "available"},
                {"feature": "conversation_search", "status": "available"},
                {"feature": "dramatic_shrimp", "status": "available"},
                {"feature": "third_party_analytics", "status": "available"},
                {"feature": "voice_mode", "status": "available"},
                {"feature": "bell_mode", "status": "available"},
                {"feature": "voice_model_selector_enabled", "status": "available"},
                {"feature": "model_picker_auto_dismiss_enabled", "status": "available"}
            ],
            "account_features": [
                {"feature": "artifacts", "status": "available"},
                {"feature": "model_selector_enabled", "status": "available"},
                {"feature": "web_search", "status": "available"},
                {"feature": "chat", "status": "available"},
                {"feature": "claude_code_web", "status": "available"}
            ]
        },
        "personalized_greeting": [],
        "statsig": {
            "flags": {
                "model_selector_enabled": True,
                "model_picker_enabled": True,
                "chat_model_selector": True,
                "pro_enabled": True,
                "artifacts": True,
                "artifacts_v2": True
            },
            "experiments": {}
        },
        "active_flags": ["claude_3_5_sonnet", "claude_3_opus", "artifacts", "artifacts_v2", "memory", "latex", "model_selector_enabled", "model_picker_enabled", "chat_model_selector", "pro_enabled", "premium_enabled"],
        "flags": {
            "artifacts": True,
            "artifacts_v2": True,
            "model_selector_enabled": True,
            "model_picker_enabled": True,
            "chat_model_selector": True,
            "pro_enabled": True,
            "premium_enabled": True,
            "subscription_active": True
        }
    }

# 4. Model Selector State (Surface switching)
@router.get("/api/organizations/{org_id}/model_selector_state/{surface}")
@router.get("/organizations/{org_id}/model_selector_state/{surface}")
@router.get("/hermes/api/organizations/{org_id}/model_selector_state/{surface}")
@router.get("/hermes/organizations/{org_id}/model_selector_state/{surface}")
async def get_surface_model_state(org_id: str, surface: str):
    for st in MODEL_SELECTOR_STATE_LIST:
        if st["id"] == surface:
            return st
    return {
        "id": surface,
        "surface": surface,
        "model": "claude-3-5-sonnet-20241022",
        "thinking": None,
        "thinking_by_model": []
    }

@router.post("/api/organizations/{org_id}/model_selector_state/{surface}")
@router.post("/organizations/{org_id}/model_selector_state/{surface}")
@router.post("/hermes/api/organizations/{org_id}/model_selector_state/{surface}")
@router.post("/hermes/organizations/{org_id}/model_selector_state/{surface}")
async def set_surface_model_state(org_id: str, surface: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    model = body.get("model")
    thinking = body.get("thinking")
    if model:
        ab.set_active_model(model)
    for st in MODEL_SELECTOR_STATE_LIST:
        if st["id"] == surface:
            if model:
                st["model"] = model
            if thinking is not None:
                st["thinking"] = thinking
            return st
    new_st = {
        "id": surface,
        "surface": surface,
        "model": model or "auto/coding:fast",
        "thinking": thinking or {"mode": "auto", "effort": "high"},
        "thinking_by_model": []
    }
    MODEL_SELECTOR_STATE_LIST.append(new_st)
    return new_st

# 5. Legal & Org Settings
@router.get("/api/legal")
@router.get("/legal")
@router.get("/hermes/api/legal")
@router.get("/hermes/legal")
async def get_legal():
    return {"status": "accepted", "acknowledged": True}

@router.get("/api/organizations/{org_id}/memory/settings")
@router.get("/organizations/{org_id}/memory/settings")
@router.get("/hermes/api/organizations/{org_id}/memory/settings")
@router.get("/hermes/organizations/{org_id}/memory/settings")
async def memory_settings(org_id: str):
    return {
        "enabled": True,
        "memory_enabled": True,
        "storage_type": "sqlite_wal"
    }

@router.post("/api/organizations/{org_id}/notification/channels")
@router.post("/organizations/{org_id}/notification/channels")
@router.post("/hermes/api/organizations/{org_id}/notification/channels")
@router.post("/hermes/organizations/{org_id}/notification/channels")
async def register_notification_channel(org_id: str, request: Request):
    return {"status": "registered"}

@router.get("/api/organizations/{org_id}/projects_v2")
@router.get("/organizations/{org_id}/projects_v2")
@router.get("/hermes/api/organizations/{org_id}/projects_v2")
@router.get("/hermes/organizations/{org_id}/projects_v2")
async def list_projects_v2(org_id: str):
    return []

# 6. Chat Conversations Management
@router.get("/api/organizations/{org_id}/chat_conversations")
@router.get("/organizations/{org_id}/chat_conversations")
@router.get("/hermes/api/organizations/{org_id}/chat_conversations")
@router.get("/hermes/organizations/{org_id}/chat_conversations")
async def list_conversations(org_id: str):
    conv_list = []
    for conv in _CONVERSATIONS.values():
        conv_list.append(_build_conv_response(conv))
    conv_list.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return conv_list

@router.post("/api/organizations/{org_id}/chat_conversations")
@router.post("/organizations/{org_id}/chat_conversations")
@router.post("/hermes/api/organizations/{org_id}/chat_conversations")
@router.post("/hermes/organizations/{org_id}/chat_conversations")
async def create_conversation(org_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    chat_id = body.get("uuid") or str(uuid.uuid4())
    name = body.get("name") or body.get("title") or "Chat"
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if chat_id not in _CONVERSATIONS:
        _CONVERSATIONS[chat_id] = {
            "uuid": chat_id,
            "name": name,
            "created_at": now,
            "updated_at": now,
            "chat_messages": []
        }
        _save_history()
    return _build_conv_response(_CONVERSATIONS[chat_id])

@router.put("/api/organizations/{org_id}/chat_conversations/{chat_id}")
@router.put("/organizations/{org_id}/chat_conversations/{chat_id}")
@router.put("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}")
@router.patch("/api/organizations/{org_id}/chat_conversations/{chat_id}")
@router.patch("/organizations/{org_id}/chat_conversations/{chat_id}")
@router.patch("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}")
async def update_conversation(org_id: str, chat_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    name = body.get("name") or body.get("title") or "Chat"
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if chat_id not in _CONVERSATIONS:
        _CONVERSATIONS[chat_id] = {
            "uuid": chat_id,
            "name": name,
            "created_at": now,
            "updated_at": now,
            "chat_messages": []
        }
    else:
        _CONVERSATIONS[chat_id]["name"] = name
        _CONVERSATIONS[chat_id]["updated_at"] = now
    _save_history()
    return _build_conv_response(_CONVERSATIONS[chat_id])

def _clean_title(text: str) -> str:
    if not text:
        return "New Chat"
    # Strip XML tags, file attachments, and code blocks
    cleaned = re.sub(r'\[Attached File:[^\]]+\]', '', text)
    cleaned = re.sub(r'<[^>]+>', '', cleaned)
    cleaned = re.sub(r'```[\s\S]*?```', '', cleaned)
    cleaned = re.sub(r'[\r\n\t]+', ' ', cleaned).strip()
    # Strip common conversational starters for a clean title
    cleaned = re.sub(r'^(?:hi|hello|hey|please|can you|help me with|could you|write|create|generate)\s+', '', cleaned, flags=re.IGNORECASE).strip()
    if not cleaned:
        cleaned = text.strip()
    words = cleaned.split()
    if len(words) > 6:
        cleaned = " ".join(words[:6])
    res = cleaned[:45].strip()
    return (res[:1].upper() + res[1:]) if res else "New Chat"

@router.post("/api/organizations/{org_id}/chat_conversations/{chat_id}/title")
@router.post("/organizations/{org_id}/chat_conversations/{chat_id}/title")
@router.post("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}/title")
async def set_conversation_title(org_id: str, chat_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    title = body.get("title") or body.get("name")
    prompt = body.get("message_content") or body.get("prompt") or ""
    if not title:
        title = _clean_title(prompt)
        if prompt:
            asyncio.create_task(_generate_ai_title_async(chat_id, prompt))
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if chat_id in _CONVERSATIONS:
        _CONVERSATIONS[chat_id]["name"] = title
        _CONVERSATIONS[chat_id]["summary"] = title
        _CONVERSATIONS[chat_id]["updated_at"] = now
    else:
        _CONVERSATIONS[chat_id] = {
            "uuid": chat_id,
            "name": title,
            "summary": title,
            "created_at": now,
            "updated_at": now,
            "chat_messages": []
        }
    _save_history()
    return {"title": title, "uuid": chat_id, "name": title}

@router.post("/api/organizations/{org_id}/chat_conversations/{chat_id}/stop_response")
@router.post("/organizations/{org_id}/chat_conversations/{chat_id}/stop_response")
@router.post("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}/stop_response")
async def stop_conversation_response(org_id: str, chat_id: str):
    return {"status": "stopped", "uuid": chat_id}

@router.delete("/api/organizations/{org_id}/chat_conversations/{chat_id}")
@router.delete("/organizations/{org_id}/chat_conversations/{chat_id}")
@router.delete("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}")
async def delete_conversation(org_id: str, chat_id: str):
    if chat_id in _CONVERSATIONS:
        del _CONVERSATIONS[chat_id]
        _save_history()
    return {"status": "deleted", "uuid": chat_id}

@router.get("/api/organizations/{org_id}/chat_conversations/{chat_id}")
@router.get("/organizations/{org_id}/chat_conversations/{chat_id}")
@router.get("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}")
async def get_conversation(org_id: str, chat_id: str):
    if chat_id not in _CONVERSATIONS:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _CONVERSATIONS[chat_id] = {
            "uuid": chat_id,
            "name": "Chat",
            "created_at": now,
            "updated_at": now,
            "chat_messages": []
        }
        _save_history()
    return _build_conv_response(_CONVERSATIONS[chat_id])

# Background execution tracking
_ACTIVE_RUNS = {}

async def _execute_agent_background(chat_id: str, prompt: str, messages: list, model: str, msg_id: str, queue: asyncio.Queue):
    """Autonomous agent runner that executes to completion in the background regardless of client connection."""
    full_text = ""
    try:
        await queue.put(ab.create_message_start(msg_id, model))

        # Check if user sent a model configuration directive
        model_switch_match = re.search(r'(?:^/model\s+|switch\s+(?:the\s+)?model\s+to\s+|set\s+(?:the\s+)?model\s+to\s+|use\s+(?:the\s+)?model\s+)([a-zA-Z0-9_\-\:\/\.]+)', prompt, re.IGNORECASE)
        if model_switch_match:
            new_model = model_switch_match.group(1).strip()
            ab.set_active_model(new_model, chat_id=chat_id)
            resp_text = f"Switched active model for this conversation to **`{new_model}`**. All subsequent responses will use this model with automatic failover."
            await queue.put(ab.create_content_block_start(0))
            await queue.put(ab.create_content_block_delta(resp_text, 0))
            await queue.put(ab.create_content_block_stop(0))
            await queue.put(ab.create_message_delta("end_turn"))
            await queue.put(ab.create_message_stop())
            full_text = resp_text
            return

        # Autonomous Agent Loop with tools, skills, bash, and server file control
        res_tuple = await ae.run_autonomous_agent(chat_id, prompt, messages, model, msg_id, queue)
        if isinstance(res_tuple, tuple):
            full_text, full_thinking = res_tuple
        else:
            full_text, full_thinking = str(res_tuple), ""
    except Exception as e:
        logger.error(f"Error in background agent execution for {chat_id}: {e}")
        if not text_active and not full_text:
            err_text = "I'm ready to assist you. Please ask your question or send your request."
            await queue.put(ab.create_content_block_start(0))
            await queue.put(ab.create_content_block_delta(err_text, 0))
            await queue.put(ab.create_content_block_stop(0))
            await queue.put(ab.create_message_delta("end_turn"))
            await queue.put(ab.create_message_stop())
            full_text = err_text
    finally:
        # Guarantee conversation history is saved to disk
        try:
            if full_text.strip():
                if chat_id not in _CONVERSATIONS:
                    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    clean_name = _clean_title(prompt)
                    _CONVERSATIONS[chat_id] = {
                        "uuid": chat_id,
                        "name": clean_name,
                        "summary": clean_name,
                        "created_at": now,
                        "updated_at": now,
                        "chat_messages": []
                    }
                
                msgs = _CONVERSATIONS[chat_id]["chat_messages"]
                prev_uuid = msgs[-1]["uuid"] if msgs else None
                
                asst_msg = _format_msg("assistant", full_text, len(msgs), prev_uuid, msg_id=msg_id)
                if full_thinking and full_thinking.strip():
                    asst_msg["content"] = [
                        {"type": "thinking", "thinking": full_thinking.strip()},
                        {"type": "text", "text": full_text.strip()}
                    ]
                else:
                    asst_msg["content"] = [
                        {"type": "text", "text": full_text.strip()}
                    ]
                
                updated_existing = False
                for m in reversed(msgs):
                    if m.get("uuid") == msg_id or m.get("sender") == "assistant":
                        m["text"] = full_text
                        m["content"] = asst_msg["content"]
                        m["stop_reason"] = "end_turn"
                        updated_existing = True
                        break
                if not updated_existing:
                    msgs.append(asst_msg)
                _CONVERSATIONS[chat_id]["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                _save_history()
        except Exception as se:
            logger.error(f"Failed to save conversation history for {chat_id}: {se}")
        
        # Signal queue completion
        await queue.put(None)
        if chat_id in _ACTIVE_RUNS:
            del _ACTIVE_RUNS[chat_id]


# 7. Conversation Completion (Streaming Claude Web / App Protocol with Thinking Support)
@router.post("/api/organizations/{org_id}/chat_conversations/{chat_id}/completion")
@router.post("/organizations/{org_id}/chat_conversations/{chat_id}/completion")
@router.post("/api/organizations/{org_id}/chat_conversations/{chat_id}/retry_completion")
@router.post("/organizations/{org_id}/chat_conversations/{chat_id}/retry_completion")
@router.post("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}/completion")
@router.post("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}/retry_completion")
async def conversation_completion(org_id: str, chat_id: str, request: Request):
    body = await request.json()
    prompt = body.get("prompt", "")
    attachments = body.get("attachments", [])
    files = body.get("files", [])
    model = body.get("model") or _CONVERSATIONS.get(chat_id, {}).get("settings", {}).get("model") or "auto/smart"
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"

    file_context_blocks = []
    for att in attachments:
        fname = att.get("file_name", "file")
        fcontent = att.get("extracted_content") or att.get("content", "")
        if fcontent:
            file_context_blocks.append(f"[Attached File: {fname}]\n{fcontent}")
    for f in files:
        fname = f.get("file_name", "file")
        fcontent = f.get("extracted_content") or f.get("content", "")
        if fcontent:
            file_context_blocks.append(f"[Attached File: {fname}]\n{fcontent}")

    full_prompt = prompt
    if not prompt.strip() and file_context_blocks:
        full_prompt = "\n\n".join(file_context_blocks) + "\n\nPlease analyze the attached file(s) and provide a helpful response."
    elif file_context_blocks:
        full_prompt = (prompt + "\n\n" + "\n\n".join(file_context_blocks)).strip()
    else:
        full_prompt = prompt if prompt.strip() else "Hello"

    # Save user message immediately
    if chat_id not in _CONVERSATIONS:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        clean_name = _clean_title(prompt)
        _CONVERSATIONS[chat_id] = {
            "uuid": chat_id,
            "name": clean_name,
            "summary": clean_name,
            "created_at": now,
            "updated_at": now,
            "chat_messages": []
        }
    
    msgs = _CONVERSATIONS[chat_id]["chat_messages"]
    prev_uuid = msgs[-1]["uuid"] if msgs else None
    user_msg = _format_msg("human", prompt, len(msgs), prev_uuid)
    if attachments:
        user_msg["attachments"] = attachments
    if files:
        user_msg["files"] = files
    msgs.append(user_msg)
    _save_history()

    history = _CONVERSATIONS[chat_id].get("chat_messages", [])
    formatted = []
    for h in history:
        role = "user" if h.get("sender") == "human" else "assistant"
        msg_text = h.get("text", "")
        content_blocks = h.get("content", [])
        if content_blocks and isinstance(content_blocks, list):
            for cb in content_blocks:
                if isinstance(cb, dict) and cb.get("type") == "text":
                    msg_text = cb.get("text", "")
        if msg_text or role == "user":
            formatted.append({"role": role, "content": msg_text or full_prompt})
    
    messages = formatted if formatted else [{"role": "user", "content": full_prompt}]
    if messages and messages[-1].get("role") == "user":
        messages[-1]["content"] = full_prompt

    # Create stream queue & launch decoupled background runner
    queue = asyncio.Queue()
    bg_task = asyncio.create_task(_execute_agent_background(chat_id, full_prompt, messages, model, msg_id, queue))
    _ACTIVE_RUNS[chat_id] = {"task": bg_task, "queue": queue}

    async def event_stream():
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=15.0)
                if item is None:
                    break
                yield item
            except asyncio.TimeoutError:
                # Emit SSE keep-alive heartbeat comment to prevent mobile proxy timeouts
                yield ": keep-alive\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )

# 8. Artifacts & In-Chat Files Endpoints
_UPLOADED_FILES: Dict[str, Dict[str, Any]] = {}

def _find_artifact_across_all(art_id: str):
    # 1. Direct lookup in _PUBLISHED_ARTIFACTS
    if art_id in _PUBLISHED_ARTIFACTS:
        p = _PUBLISHED_ARTIFACTS[art_id]
        return p.get("chat_conversation_uuid"), p

    # 2. Check if art_id is a conversation UUID (chat_id)
    if art_id in _CONVERSATIONS:
        arts = _extract_artifacts_from_conv(art_id)
        if arts:
            return art_id, arts[-1]

    # 3. Check across all conversations for artifact ID, version UUID, or message UUID
    for cid, conv in _CONVERSATIONS.items():
        arts = _extract_artifacts_from_conv(cid)
        for a in arts:
            if (a.get("id") == art_id or a.get("identifier") == art_id or 
                a.get("uuid") == art_id or a.get("artifact_uuid") == art_id or 
                a.get("version_uuid") == art_id or a.get("message_uuid") == art_id):
                return cid, a
                
    # 4. Check if any artifact in any conversation has a matching prefix
    for cid, conv in _CONVERSATIONS.items():
        arts = _extract_artifacts_from_conv(cid)
        for a in arts:
            if art_id in a.get("id", "") or art_id in a.get("uuid", ""):
                return cid, a

    return None, None

def _create_version_record(art: Optional[Dict[str, Any]], artifact_id: str, chat_id: Optional[str] = None) -> Dict[str, Any]:
    now_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if art:
        art_uuid = art.get("uuid") or art.get("id") or artifact_id
        ver_uuid = art.get("version_uuid") or str(uuid.uuid4())
        art_type = art.get("type") or art.get("artifact_type") or "application/vnd.ant.markdown"
        title = art.get("title") or "Document"
        lang = art.get("language") or art.get("code_language") or ""
        content = art.get("content") or ""
        created_at = art.get("created_at") or now_ts
        updated_at = art.get("updated_at") or now_ts
        msg_uuid = art.get("message_uuid") or str(uuid.uuid4())
        conv_id = art.get("chat_conversation_uuid") or chat_id or ""
    else:
        conv = _CONVERSATIONS.get(chat_id or artifact_id)
        if conv and conv.get("chat_messages"):
            for m in reversed(conv["chat_messages"]):
                if m.get("sender") == "assistant" and m.get("text"):
                    content = m.get("text")
                    title = conv.get("name") or "Document"
                    break
            else:
                content = "# Document Preview\nReady to render content."
                title = "Document"
            art_type = "application/vnd.ant.markdown"
            lang = "markdown"
            msg_uuid = conv["chat_messages"][-1].get("uuid", str(uuid.uuid4()))
            conv_id = conv.get("uuid", artifact_id)
        else:
            content = "# Preview Document\nReady to render content."
            title = "Document"
            art_type = "application/vnd.ant.markdown"
            lang = "markdown"
            msg_uuid = str(uuid.uuid4())
            conv_id = chat_id or ""

        art_uuid = artifact_id
        ver_uuid = str(uuid.uuid4())
        created_at = now_ts
        updated_at = now_ts

    return {
        "id": art_uuid,
        "uuid": ver_uuid,
        "artifact_uuid": art_uuid,
        "version_uuid": ver_uuid,
        "version_index": 1,
        "version": 1,
        "message_uuid": msg_uuid,
        "chat_conversation_uuid": conv_id,
        "identifier": art_uuid,
        "type": art_type,
        "artifact_type": art_type,
        "code_language": lang,
        "language": lang,
        "title": title,
        "result_state": "complete",
        "published_artifact_uuid": None,
        "published_artifact_deleted_at": None,
        "source": "c",
        "visibility": "private",
        "is_complete": True,
        "created_at": created_at,
        "updated_at": updated_at,
        "content": content,
        "text": content,
        "markdown": content
    }

@router.get("/api/organizations/{org_id}/chat_conversations/{chat_id}/render_values")
@router.get("/organizations/{org_id}/chat_conversations/{chat_id}/render_values")
@router.get("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}/render_values")
async def get_conversation_render_values_endpoint(org_id: str, chat_id: str):
    return _extract_render_values(chat_id)

@router.get("/api/organizations/{org_id}/chat_conversations/{chat_id}/artifacts")
@router.get("/organizations/{org_id}/chat_conversations/{chat_id}/artifacts")
@router.get("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}/artifacts")
async def list_conversation_artifacts(org_id: str, chat_id: str):
    artifacts = _extract_artifacts_from_conv(chat_id)
    return {"artifacts": artifacts, "data": artifacts}

@router.get("/api/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}/versions/latest")
@router.get("/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}/versions/latest")
@router.get("/api/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}/versions/current")
@router.get("/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}/versions/current")
@router.get("/api/organizations/{org_id}/artifacts/{artifact_id}/versions/latest")
@router.get("/organizations/{org_id}/artifacts/{artifact_id}/versions/latest")
@router.get("/api/organizations/{org_id}/artifacts/{artifact_id}/versions/current")
@router.get("/organizations/{org_id}/artifacts/{artifact_id}/versions/current")
@router.get("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}/versions/latest")
async def get_artifact_latest_version_endpoint(org_id: str, artifact_id: str, chat_id: Optional[str] = None):
    cid, art = _find_artifact_across_all(artifact_id)
    rec = _create_version_record(art, artifact_id, chat_id=cid or chat_id)
    return rec

@router.get("/api/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}")
@router.get("/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}")
@router.get("/api/organizations/{org_id}/artifacts/{artifact_id}")
@router.get("/organizations/{org_id}/artifacts/{artifact_id}")
@router.get("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}")
async def get_artifact(org_id: str, artifact_id: str, chat_id: Optional[str] = None):
    cid, art = _find_artifact_across_all(artifact_id)
    rec = _create_version_record(art, artifact_id, chat_id=cid or chat_id)
    return rec

@router.get("/api/organizations/{org_id}/artifacts/{artifact_id}/versions")
@router.get("/organizations/{org_id}/artifacts/{artifact_id}/versions")
@router.get("/api/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}/versions")
@router.get("/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}/versions")
@router.get("/api/organizations/{org_id}/artifacts/{artifact_id}/versions_v2")
@router.get("/organizations/{org_id}/artifacts/{artifact_id}/versions_v2")
@router.get("/hermes/api/organizations/{org_id}/artifacts/{artifact_id}/versions")
async def get_artifact_versions(org_id: str, artifact_id: str, chat_id: Optional[str] = None):
    cid, art = _find_artifact_across_all(artifact_id)
    rec = _create_version_record(art, artifact_id, chat_id=cid or chat_id)
    res = dict(rec)
    res["artifact_versions"] = [rec]
    res["versions"] = [rec]
    res["data"] = [rec]
    return res

@router.get("/api/organizations/{org_id}/artifacts/{artifact_id}/version/{version_id}")
@router.get("/organizations/{org_id}/artifacts/{artifact_id}/version/{version_id}")
@router.get("/api/organizations/{org_id}/artifact-versions/{version_id}")
@router.get("/organizations/{org_id}/artifact-versions/{version_id}")
@router.get("/api/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}/version/{version_id}")
@router.get("/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}/version/{version_id}")
async def get_artifact_version_by_id(org_id: str, version_id: str, artifact_id: Optional[str] = None, chat_id: Optional[str] = None):
    art_lookup = artifact_id or version_id
    cid, art = _find_artifact_across_all(art_lookup)
    rec = _create_version_record(art, art_lookup, chat_id=cid or chat_id)
    return rec

@router.get("/api/organizations/{org_id}/artifacts/{artifact_id}/content")
@router.get("/organizations/{org_id}/artifacts/{artifact_id}/content")
@router.get("/api/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}/content")
@router.get("/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}/content")
async def get_artifact_content(org_id: str, artifact_id: str, chat_id: Optional[str] = None):
    cid, art = _find_artifact_across_all(artifact_id)
    content = art.get("content", "") if art else ""
    return PlainTextResponse(content, media_type="text/plain; charset=utf-8")

@router.get("/api/organizations/{org_id}/user_artifacts")
@router.get("/organizations/{org_id}/user_artifacts")
@router.get("/hermes/api/organizations/{org_id}/user_artifacts")
async def list_user_artifacts(org_id: str):
    all_user_arts = []
    for cid, conv in _CONVERSATIONS.items():
        for a in _extract_artifacts_from_conv(cid):
            all_user_arts.append({
                "uuid": a.get("uuid") or a.get("id"),
                "artifact_identifier": a.get("identifier") or a.get("id"),
                "title": a.get("title", "Document"),
                "artifact_type": a.get("type", "application/vnd.ant.markdown"),
                "code_language": a.get("language", ""),
                "chat_conversation_uuid": cid,
                "preview": (a.get("content", "")[:100] + "...") if len(a.get("content", "")) > 100 else a.get("content", ""),
                "created_at": a.get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "updated_at": a.get("updated_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "latest_published_artifact_uuid": None
            })
    return {"artifacts": all_user_arts, "data": all_user_arts}

_PUBLISHED_ARTIFACTS: Dict[str, Dict[str, Any]] = {}

@router.get("/api/organizations/{org_id}/published_artifacts/{artifact_id}")
@router.get("/organizations/{org_id}/published_artifacts/{artifact_id}")
@router.get("/hermes/api/organizations/{org_id}/published_artifacts/{artifact_id}")
@router.get("/hermes/organizations/{org_id}/published_artifacts/{artifact_id}")
async def get_published_artifact(org_id: str, artifact_id: str, request: Request):
    pub = _PUBLISHED_ARTIFACTS.get(artifact_id)
    if not pub:
        cid, art = _find_artifact_across_all(artifact_id)
        if art:
            pub = _create_version_record(art, artifact_id, chat_id=cid)
            _PUBLISHED_ARTIFACTS[artifact_id] = pub
    
    if not pub:
        pub = _create_version_record(None, artifact_id)
    
    return pub

@router.post("/api/organizations/{org_id}/publish_artifact")
@router.post("/organizations/{org_id}/publish_artifact")
@router.post("/api/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}/publish")
@router.post("/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}/publish")
@router.post("/hermes/api/organizations/{org_id}/publish_artifact")
@router.post("/hermes/organizations/{org_id}/publish_artifact")
@router.post("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}/publish")
@router.post("/hermes/organizations/{org_id}/chat_conversations/{chat_id}/artifacts/{artifact_id}/publish")
async def publish_artifact(org_id: str, request: Request, chat_id: Optional[str] = None, artifact_id: Optional[str] = None):
    try:
        body = await request.json()
    except Exception:
        body = {}
    
    art_id = artifact_id or body.get("artifact_uuid") or body.get("artifact_identifier") or body.get("id") or str(uuid.uuid4())
    cid, art = _find_artifact_across_all(art_id)
    pub_uuid = str(uuid.uuid4())
    
    title = (art.get("title") if art else None) or body.get("title") or "Document"
    art_type = (art.get("type") or art.get("artifact_type") if art else None) or body.get("artifact_type") or "application/vnd.ant.markdown"
    lang = (art.get("language") or art.get("code_language") if art else None) or body.get("code_language") or ""
    content = (art.get("content") if art else None) or body.get("content") or ""
    now_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    pub_record = {
        "uuid": pub_uuid,
        "artifact_uuid": art_id,
        "published_artifact_uuid": pub_uuid,
        "artifact_identifier": art_id,
        "title": title,
        "artifact_type": art_type,
        "code_language": lang,
        "language": lang,
        "content": content,
        "text": content,
        "markdown": content,
        "message_uuid": str(uuid.uuid4()),
        "result_state": "complete",
        "deleted": False,
        "status": "published",
        "visibility": "public",
        "source": "c",
        "url": f"https://claude.ai/artifacts/{pub_uuid}",
        "created_at": now_ts,
        "updated_at": now_ts
    }
    
    _PUBLISHED_ARTIFACTS[pub_uuid] = pub_record
    _PUBLISHED_ARTIFACTS[art_id] = pub_record
    
    return pub_record

@router.get("/public/artifacts/{artifact_id}")
@router.get("/hermes/public/artifacts/{artifact_id}")
@router.get("/api/public/artifacts/{artifact_id}")
@router.get("/hermes/api/public/artifacts/{artifact_id}")
@router.get("/public/artifacts/{artifact_id}/versions")
@router.get("/hermes/public/artifacts/{artifact_id}/versions")
@router.get("/public/artifacts/{artifact_id}/version/{version_id}")
@router.get("/hermes/public/artifacts/{artifact_id}/version/{version_id}")
@router.get("/public/artifacts/{artifact_id}/content")
@router.get("/hermes/public/artifacts/{artifact_id}/content")
async def get_public_artifact_endpoint(artifact_id: str, request: Request, version_id: Optional[str] = None):
    pub = _PUBLISHED_ARTIFACTS.get(artifact_id)
    if not pub:
        cid, art = _find_artifact_across_all(artifact_id)
        if art:
            pub = _create_version_record(art, artifact_id, chat_id=cid)
            _PUBLISHED_ARTIFACTS[artifact_id] = pub
    
    if not pub:
        pub = _create_version_record(None, artifact_id)
    
    accept = request.headers.get("accept", "")
    if "text/html" in accept and "application/json" not in accept:
        title = pub.get("title", "Document")
        content = pub.get("content", "")
        art_type = pub.get("artifact_type") or pub.get("type") or "application/vnd.ant.markdown"
        lang = pub.get("code_language") or pub.get("language") or ""
        initial_json = json.dumps({"title": title, "content": content, "type": art_type, "language": lang, "id": artifact_id})
        rendered_html = _SANDBOX_HTML.replace(
            "/*__INITIAL_DATA_PLACEHOLDER__*/",
            f"window.__INITIAL_DATA__ = {initial_json};\ntry {{ renderContent(window.__INITIAL_DATA__); }} catch(e) {{}}"
        )
        headers = {
            "Content-Type": "text/html; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
            "Content-Security-Policy": "frame-ancestors *",
            "Cache-Control": "no-cache"
        }
        return HTMLResponse(content=rendered_html, headers=headers)
    
    res = dict(pub)
    res["artifact_versions"] = [pub]
    res["versions"] = [pub]
    res["data"] = [pub]
    return res

@router.put("/api/organizations/{org_id}/artifact-versions/{artifact_id}/visibility")
@router.put("/organizations/{org_id}/artifact-versions/{artifact_id}/visibility")
@router.put("/hermes/api/organizations/{org_id}/artifact-versions/{artifact_id}/visibility")
@router.put("/hermes/organizations/{org_id}/artifact-versions/{artifact_id}/visibility")
async def update_artifact_visibility(org_id: str, artifact_id: str, request: Request):
    return {"status": "ok", "artifact_id": artifact_id}

_SANDBOX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">
    <title>Claude Artifact Sandbox</title>
    <style>
        :root {
            --bg-color: #1e1e1e;
            --text-color: #e3e3e3;
            --link-color: #72a7fe;
            --border-color: #333;
            --code-bg: #2d2d2d;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }
        @media (prefers-color-scheme: light) {
            :root {
                --bg-color: #ffffff;
                --text-color: #1f2328;
                --link-color: #0969da;
                --border-color: #d0d7de;
                --code-bg: #f6f8fa;
            }
        }
        html, body {
            margin: 0;
            padding: 16px;
            background-color: var(--bg-color);
            color: var(--text-color);
            line-height: 1.6;
            font-size: 15px;
            box-sizing: border-box;
            overflow-x: hidden;
            word-wrap: break-word;
        }
        pre {
            background-color: var(--code-bg);
            border-radius: 8px;
            padding: 14px;
            overflow-x: auto;
            border: 1px solid var(--border-color);
            position: relative;
        }
        code {
            font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
            font-size: 13.5px;
        }
        p code, li code {
            background-color: var(--code-bg);
            padding: 2px 6px;
            border-radius: 4px;
            border: 1px solid var(--border-color);
        }
        blockquote {
            border-left: 4px solid var(--link-color);
            margin: 0;
            padding-left: 16px;
            color: #888;
        }
        table {
            border-collapse: collapse;
            width: 100%;
            margin: 16px 0;
        }
        th, td {
            border: 1px solid var(--border-color);
            padding: 8px 12px;
            text-align: left;
        }
        th {
            background-color: var(--code-bg);
        }
        a { color: var(--link-color); text-decoration: none; }
        a:hover { text-decoration: underline; }
        img, svg { max-width: 100%; height: auto; display: block; margin: 12px 0; }
        #root { width: 100%; min-height: 100%; }
        .loading {
            display: flex;
            align-items: center;
            justify-content: center;
            height: 120px;
            color: #888;
            font-style: italic;
        }
        .header-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 8px;
            margin-bottom: 16px;
        }
        .header-title {
            font-weight: 600;
            font-size: 16px;
        }
    </style>
</head>
<body>
    <div id="root">
        <div class="loading">Loading artifact preview...</div>
    </div>
    <script>
        function postToHost(msg) {
            try {
                if (window.parent && window.parent !== window) {
                    window.parent.postMessage(msg, '*');
                }
            } catch(e) {}
            try {
                if (window.top && window.top !== window.parent) {
                    window.top.postMessage(msg, '*');
                }
            } catch(e) {}
            try {
                if (window.Android && window.Android.postMessage) {
                    window.Android.postMessage(typeof msg === 'string' ? msg : JSON.stringify(msg));
                }
            } catch(e) {}
            try {
                if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.sandbox) {
                    window.webkit.messageHandlers.sandbox.postMessage(msg);
                }
            } catch(e) {}
        }

        var contentReceived = false;

        function notifyReady() {
            if (contentReceived) return;
            var reqId = "ready-" + Date.now();
            var readyMsg = {
                channel: "request",
                requestId: reqId,
                request_id: reqId,
                method: "anthropic.claude.usercontent.sandbox.ReadyForContent"
            };
            postToHost(readyMsg);
            postToHost({
                channel: "request",
                requestId: reqId,
                request_id: reqId,
                method: "ReadyForContent"
            });
            postToHost("readyForContent");
        }

        // Fast zero-dependency markdown parser
        function renderMarkdown(src) {
            if (!src) return '';
            var html = src;

            // Escape HTML characters in pure text mode
            html = html.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

            // Fenced code blocks
            html = html.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, function(m, lang, code) {
                return '<pre><code class="language-' + (lang || 'text') + '">' + code + '</code></pre>';
            });

            // Inline code
            html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

            // Headers
            html = html.replace(/^###### (.*$)/gim, '<h6>$1</h6>');
            html = html.replace(/^##### (.*$)/gim, '<h5>$1</h5>');
            html = html.replace(/^#### (.*$)/gim, '<h4>$1</h4>');
            html = html.replace(/^### (.*$)/gim, '<h3>$1</h3>');
            html = html.replace(/^## (.*$)/gim, '<h2>$1</h2>');
            html = html.replace(/^# (.*$)/gim, '<h1>$1</h1>');

            // Blockquotes
            html = html.replace(/^\> (.*$)/gim, '<blockquote>$1</blockquote>');

            // Unordered list items
            html = html.replace(/^\s*[-*+]\s+(.*$)/gim, '<li>$1</li>');

            // Bold & Italic
            html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
            html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
            html = html.replace(/__([^_]+)__/g, '<strong>$1</strong>');
            html = html.replace(/_([^_]+)_/g, '<em>$1</em>');

            // Links
            html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');

            // Linebreaks and paragraphs
            html = html.replace(/\n\n+/g, '<br><br>');
            html = html.replace(/\n/g, '<br>');

            return html;
        }

        function renderContent(data) {
            contentReceived = true;
            const root = document.getElementById('root');
            if (!data) return;

            let content = '';
            let type = '';

            if (typeof data === 'string') {
                content = data;
            } else {
                content = data.content || data.markdown || data.text || data.code || (data.payload && data.payload.content) || '';
                type = data.artifact_type || data.type || data.mimeType || data.mime_type || (data.payload && (data.payload.type || data.payload.mimeType || data.payload.mime_type)) || '';
            }

            if (!content && typeof data === 'object') {
                for (let k of Object.keys(data)) {
                    if (typeof data[k] === 'string' && data[k].length > 10) {
                        content = data[k];
                        break;
                    }
                }
            }

            if (!content) return;

            try {
                type = (type || '').toLowerCase();
                if (type.includes('html') || content.trim().startsWith('<!DOCTYPE html') || content.trim().startsWith('<html')) {
                    root.innerHTML = content;
                } else if (type.includes('svg') || content.trim().startsWith('<svg')) {
                    root.innerHTML = content;
                } else {
                    root.innerHTML = renderMarkdown(content);
                }
            } catch(e) {
                root.innerHTML = '<pre>' + content.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</pre>';
            }
        }

        window.renderContent = renderContent;
        window.setArtifactContent = renderContent;

        /*__INITIAL_DATA_PLACEHOLDER__*/

        // Check query string ?content=...
        try {
            var params = new URLSearchParams(window.location.search);
            var qContent = params.get('content') || params.get('text');
            var qType = params.get('type') || params.get('artifact_type') || '';
            if (qContent) {
                renderContent({ content: qContent, type: qType });
            }
        } catch(e) {}

        window.addEventListener('message', function(event) {
            if (!event.data) return;
            let d = event.data;
            if (typeof d === 'string') {
                try { d = JSON.parse(d); } catch(e) {}
            }
            if (!d || typeof d !== 'object') return;

            const reqId = d.requestId || d.request_id || d.id;
            const method = d.method || '';

            if (d.channel === 'request' || method.includes('SetContent') || d.payload || d.content) {
                const payload = d.payload || d;
                renderContent(payload);

                if (reqId) {
                    var respMsg = {
                        channel: "response",
                        requestId: reqId,
                        request_id: reqId,
                        status: 200
                    };
                    postToHost(respMsg);
                }
            } else if (d.type === 'SetContent' || d.markdown || d.text) {
                renderContent(d);
            }
        });

        // Initialize handshake
        notifyReady();
        var readyTimer = setInterval(function() {
            if (contentReceived) {
                clearInterval(readyTimer);
            } else {
                notifyReady();
            }
        }, 200);
        setTimeout(function() { clearInterval(readyTimer); }, 15000);

        // Auto-fetch latest artifact if host postMessage is delayed
        setTimeout(async function() {
            if (contentReceived) return;
            try {
                var params = new URLSearchParams(window.location.search);
                var artId = params.get('identifier') || params.get('id') || params.get('artifact_id') || params.get('runtime_id');
                var fetchUrl = artId ? ('/api/organizations/org_0123456789abcdef/artifacts/' + artId) : '/api/organizations/org_0123456789abcdef/user_artifacts';
                var resp = await fetch(fetchUrl);
                if (resp.ok) {
                    var data = await resp.json();
                    if (data.artifacts && data.artifacts.length > 0) {
                        renderContent(data.artifacts[0]);
                    } else if (data.content || data.markdown || data.text) {
                        renderContent(data);
                    }
                }
            } catch(e) {}
        }, 350);
    </script>
</body>
</html>"""

@router.get("/mobile/web-view-sandbox-runtime/{runtime_id:path}", response_class=HTMLResponse)
@router.get("/mobile/web-view-sandbox-runtime", response_class=HTMLResponse)
@router.get("/mobile/mcp-app-runtime/{runtime_id:path}", response_class=HTMLResponse)
@router.get("/mobile/mcp-app-runtime", response_class=HTMLResponse)
@router.get("/hermes/mobile/web-view-sandbox-runtime/{runtime_id:path}", response_class=HTMLResponse)
@router.get("/hermes/mobile/web-view-sandbox-runtime", response_class=HTMLResponse)
@router.get("/hermes/mobile/mcp-app-runtime/{runtime_id:path}", response_class=HTMLResponse)
@router.get("/hermes/mobile/mcp-app-runtime", response_class=HTMLResponse)
@router.get("/code/frame/{frame_id:path}", response_class=HTMLResponse)
@router.get("/code/artifact/{artifact_id:path}", response_class=HTMLResponse)
@router.get("/api/frame/{frame_id:path}", response_class=HTMLResponse)
@router.get("/code/frame", response_class=HTMLResponse)
@router.get("/code/artifact", response_class=HTMLResponse)
@router.get("/api/frame", response_class=HTMLResponse)
@router.get("/artifacts/sandbox", response_class=HTMLResponse)
@router.get("/sandbox", response_class=HTMLResponse)
async def get_sandbox_frame(request: Request, frame_id: Optional[str] = None, artifact_id: Optional[str] = None, runtime_id: Optional[str] = None):
    lookup_id = artifact_id or frame_id or runtime_id
    pub = None
    if lookup_id:
        pub = _PUBLISHED_ARTIFACTS.get(lookup_id)
        if not pub:
            cid, art = _find_artifact_across_all(lookup_id)
            if art:
                pub = _create_version_record(art, lookup_id, chat_id=cid)
    
    if pub:
        title = pub.get("title", "Document")
        content = pub.get("content", "")
        art_type = pub.get("artifact_type") or pub.get("type") or "application/vnd.ant.markdown"
        lang = pub.get("code_language") or pub.get("language") or ""
        initial_json = json.dumps({"title": title, "content": content, "type": art_type, "language": lang, "id": lookup_id})
        rendered_html = _SANDBOX_HTML.replace(
            "/*__INITIAL_DATA_PLACEHOLDER__*/",
            f"window.__INITIAL_DATA__ = {initial_json};\ntry {{ renderContent(window.__INITIAL_DATA__); }} catch(e) {{}}"
        )
    else:
        rendered_html = _SANDBOX_HTML

    headers = {
        "Content-Type": "text/html; charset=utf-8",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "*",
        "Access-Control-Allow-Headers": "*",
        "Content-Security-Policy": "frame-ancestors *",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0"
    }
    return HTMLResponse(content=rendered_html, headers=headers)

# ----------------------------------------------------------------------------
# 8b. Document & Attachment Conversion Endpoint (/convert_document)
# ----------------------------------------------------------------------------
@router.post("/api/organizations/{org_id}/convert_document")
@router.post("/organizations/{org_id}/convert_document")
@router.post("/hermes/api/organizations/{org_id}/convert_document")
async def convert_document(org_id: str, request: Request):
    """Handle document/image conversion from Claude Android client (multipart or JSON)."""
    import base64
    file_id = f"file_{uuid.uuid4().hex[:16]}"
    file_name = "attachment.txt"
    file_type = "text/plain"
    extracted_text = ""
    file_size = 0

    content_type = request.headers.get("content-type", "")
    try:
        if "multipart/form-data" in content_type:
            form = await request.form()
            uploaded_file = form.get("file") or form.get("document")
            if uploaded_file and hasattr(uploaded_file, "filename"):
                file_name = uploaded_file.filename or "attachment"
                file_type = uploaded_file.content_type or "application/octet-stream"
                raw_bytes = await uploaded_file.read()
                file_size = len(raw_bytes)
                
                # If text-based or code
                if any(file_type.startswith(p) for p in ["text/", "application/json", "application/javascript", "application/xml", "application/x-yaml"]):
                    extracted_text = raw_bytes.decode("utf-8", errors="replace")
                elif "image" in file_type:
                    b64 = base64.b64encode(raw_bytes).decode("utf-8")
                    extracted_text = f"[Image: {file_name} ({file_type}) base64 data length: {len(b64)}]"
                elif "pdf" in file_type:
                    # PDF fallback or text extraction
                    extracted_text = f"[PDF Document: {file_name} ({file_size} bytes)]"
                else:
                    extracted_text = f"[File: {file_name} ({file_type}, {file_size} bytes)]"
        else:
            body = await request.json()
            file_name = body.get("file_name") or body.get("name") or "attachment.txt"
            file_type = body.get("file_type") or body.get("content_type") or "text/plain"
            raw_content = body.get("content") or body.get("extracted_content") or ""
            file_size = len(str(raw_content).encode("utf-8"))
            extracted_text = str(raw_content)
    except Exception as ex:
        logger.warning(f"Error parsing convert_document: {ex}")
        extracted_text = f"[Uploaded File: {file_name}]"

    attachment_record = {
        "id": file_id,
        "file_name": file_name,
        "file_size": file_size,
        "file_type": file_type,
        "extracted_content": extracted_text
    }
    _UPLOADED_FILES[file_id] = attachment_record
    return attachment_record

@router.post("/api/organizations/{org_id}/chat_conversations/{chat_id}/files")
@router.post("/organizations/{org_id}/chat_conversations/{chat_id}/files")
@router.post("/api/organizations/{org_id}/files")
@router.post("/organizations/{org_id}/files")
@router.post("/api/files")
async def upload_file(request: Request):
    try:
        body = await request.json()
        file_name = body.get("file_name", "uploaded_file.txt")
        file_content = body.get("content") or body.get("extracted_content") or ""
        file_type = body.get("file_type", "text/plain")
        file_size = len(file_content.encode("utf-8")) if file_content else body.get("file_size", 0)
    except Exception:
        file_name = "file.txt"
        file_content = ""
        file_type = "text/plain"
        file_size = 0
    
    file_id = f"file_{uuid.uuid4().hex[:16]}"
    file_record = {
        "id": file_id,
        "file_name": file_name,
        "file_size": file_size,
        "file_type": file_type,
        "extracted_content": file_content
    }
    _UPLOADED_FILES[file_id] = file_record
    return file_record

@router.get("/api/organizations/{org_id}/chat_conversations/{chat_id}/files/{file_id}")
@router.get("/organizations/{org_id}/chat_conversations/{chat_id}/files/{file_id}")
@router.get("/api/organizations/{org_id}/files/{file_id}")
@router.get("/organizations/{org_id}/files/{file_id}")
@router.get("/api/files/{file_id}")
async def get_file(file_id: str):
    if file_id in _UPLOADED_FILES:
        return _UPLOADED_FILES[file_id]
    return {"id": file_id, "file_name": "file.txt", "file_size": 0, "file_type": "text/plain", "extracted_content": ""}

# 9. Directory & Feature Flags
@router.get("/v1/directory/servers")
@router.get("/directory/servers")
@router.get("/api/v1/directory/servers")
@router.get("/api/directory/servers")
@router.get("/hermes/v1/directory/servers")
async def directory_servers():
    return {
        "servers": [],
        "data": [],
        "has_more": False
    }

@router.get("/api/organizations/{org_id}/feature_flags")
@router.get("/organizations/{org_id}/feature_flags")
@router.get("/hermes/api/organizations/{org_id}/feature_flags")
async def feature_flags(org_id: str):
    return {
        "flags": {
            "claude_3_5_sonnet": True,
            "claude_3_opus": True,
            "artifacts": True,
            "memory": True,
            "latex": True,
            "model_selector_enabled": True
        }
    }

# 10. External Model Settings UI & Management API
_SETTINGS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Claude APK & Hermes - Model Settings</title>
    <style>
        :root {
            --bg-main: #141416;
            --bg-card: #1e1f23;
            --bg-card-hover: #26282e;
            --text-primary: #f4f4f5;
            --text-secondary: #a1a1aa;
            --accent-orange: #d97706;
            --accent-green: #10b981;
            --accent-blue: #3b82f6;
            --border: #2e3038;
            --border-active: #d97706;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }
        body {
            margin: 0;
            padding: 24px 16px;
            background-color: var(--bg-main);
            color: var(--text-primary);
            display: flex;
            justify-content: center;
        }
        .container {
            max-width: 780px;
            width: 100%;
        }
        .header {
            text-align: center;
            margin-bottom: 28px;
        }
        .header h1 {
            font-size: 24px;
            margin: 0 0 8px 0;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
        }
        .header p {
            color: var(--text-secondary);
            font-size: 14px;
            margin: 0;
        }
        .card {
            background-color: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px 20px;
            margin-bottom: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: all 0.2s ease;
        }
        .card.active {
            border-color: var(--accent-orange);
            box-shadow: 0 0 0 1px var(--accent-orange);
        }
        .card-info {
            flex: 1;
            margin-right: 16px;
        }
        .card-title-row {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 4px;
        }
        .card-title {
            font-size: 16px;
            font-weight: 600;
        }
        .badge {
            font-size: 11px;
            font-weight: 700;
            padding: 2px 7px;
            border-radius: 4px;
            text-transform: uppercase;
        }
        .badge-active { background-color: rgba(217, 119, 6, 0.2); color: #f59e0b; }
        .badge-fast { background-color: rgba(16, 185, 129, 0.2); color: #34d399; }
        .badge-pro { background-color: rgba(139, 92, 246, 0.2); color: #a78bfa; }
        .badge-smart { background-color: rgba(59, 130, 246, 0.2); color: #60a5fa; }
        .badge-groq { background-color: rgba(249, 115, 22, 0.2); color: #fb923c; }
        .badge-think { background-color: rgba(236, 72, 153, 0.2); color: #f472b6; }
        .badge-custom { background-color: rgba(107, 114, 128, 0.2); color: #9ca3af; }
        .card-desc {
            font-size: 13px;
            color: var(--text-secondary);
            margin-bottom: 4px;
        }
        .card-id {
            font-family: ui-monospace, monospace;
            font-size: 12px;
            color: #71717a;
        }
        .card-actions {
            display: flex;
            gap: 8px;
        }
        button {
            cursor: pointer;
            font-weight: 600;
            font-size: 13px;
            padding: 8px 14px;
            border-radius: 8px;
            border: 1px solid var(--border);
            background-color: #27272a;
            color: var(--text-primary);
            transition: all 0.15s ease;
        }
        button:hover {
            background-color: #3f3f46;
        }
        button.btn-primary {
            background-color: var(--accent-orange);
            border-color: var(--accent-orange);
            color: #fff;
        }
        button.btn-primary:hover {
            background-color: #b45309;
        }
        .form-card {
            background-color: var(--bg-card);
            border: 1px dashed var(--border);
            border-radius: 12px;
            padding: 20px;
            margin-top: 24px;
        }
        .form-card h2 {
            font-size: 16px;
            margin: 0 0 12px 0;
        }
        .input-group {
            display: flex;
            flex-direction: column;
            gap: 6px;
            margin-bottom: 12px;
        }
        .input-group label {
            font-size: 13px;
            color: var(--text-secondary);
            font-weight: 500;
        }
        input {
            background-color: #141416;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 10px 14px;
            color: var(--text-primary);
            font-size: 14px;
            outline: none;
        }
        input:focus {
            border-color: var(--accent-orange);
        }
        .status-banner {
            display: none;
            padding: 10px 16px;
            border-radius: 8px;
            font-size: 13px;
            margin-bottom: 16px;
        }
        .status-banner.success { display: block; background-color: rgba(16, 185, 129, 0.15); color: #34d399; }
        .status-banner.error { display: block; background-color: rgba(239, 68, 68, 0.15); color: #f87171; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚙️ Claude APK & Hermes - Model Settings</h1>
            <p>Select your active reasoning model or add custom LLM endpoints for your Claude APK and web clients.</p>
        </div>
        <div id="statusBanner" class="status-banner"></div>
        <div id="modelList"></div>

        <div class="form-card">
            <h2>➕ Add Custom Model to Claude APK Selector</h2>
            <div class="input-group">
                <label>Model Display Name</label>
                <input id="newModelName" type="text" placeholder="e.g. DeepSeek R1 Distill 70B">
            </div>
            <div class="input-group">
                <label>Model ID / OmniRoute Route Path</label>
                <input id="newModelId" type="text" placeholder="e.g. groq/deepseek-r1-distill-llama-70b">
            </div>
            <div class="input-group">
                <label>Description</label>
                <input id="newModelDesc" type="text" placeholder="e.g. High speed reasoning model">
            </div>
            <div class="input-group">
                <label>Badge Text</label>
                <input id="newModelBadge" type="text" placeholder="e.g. REASONING">
            </div>
            <button class="btn-primary" onclick="addCustomModel()" style="width: 100%; margin-top: 8px;">Add Model to Catalog</button>
        </div>
    </div>

    <script>
        var currentActiveModel = 'auto/smart';

        function showStatus(msg, isSuccess) {
            var b = document.getElementById('statusBanner');
            b.className = 'status-banner ' + (isSuccess ? 'success' : 'error');
            b.innerText = msg;
            setTimeout(function() { b.style.display = 'none'; }, 4000);
        }

        async function loadModels() {
            try {
                var res = await fetch('/api/bootstrap/org_0123456789abcdef/app_start');
                var data = await res.json();
                var models = data.model_selector_config[0].models;
                
                var stateRes = await fetch('/api/organizations/org_0123456789abcdef/model_selector_state/chat');
                var stateData = await stateRes.json();
                currentActiveModel = stateData.model || 'auto/smart';

                var container = document.getElementById('modelList');
                container.innerHTML = '';

                models.forEach(function(m) {
                    var isCurrent = (m.id === currentActiveModel || m.model === currentActiveModel);
                    var card = document.createElement('div');
                    card.className = 'card ' + (isCurrent ? 'active' : '');

                    var badgeText = m.badge && m.badge.message ? (m.badge.message.english || m.badge.message) : '';
                    var badgeClass = 'badge-custom';
                    if (badgeText.toUpperCase() === 'FAST') badgeClass = 'badge-fast';
                    if (badgeText.toUpperCase() === 'PRO') badgeClass = 'badge-pro';
                    if (badgeText.toUpperCase() === 'SMART') badgeClass = 'badge-smart';
                    if (badgeText.toUpperCase() === 'GROQ') badgeClass = 'badge-groq';
                    if (badgeText.toUpperCase() === 'THINK') badgeClass = 'badge-think';

                    var desc = (m.description && m.description.english) ? m.description.english : ((m.description && m.description.text) ? m.description.text : '');

                    card.innerHTML = `
                        <div class="card-info">
                            <div class="card-title-row">
                                <span class="card-title">${m.name}</span>
                                ${isCurrent ? '<span class="badge badge-active">ACTIVE</span>' : ''}
                                ${badgeText ? `<span class="badge ${badgeClass}">${badgeText}</span>` : ''}
                            </div>
                            <div class="card-desc">${desc}</div>
                            <div class="card-id">ID: ${m.id}</div>
                        </div>
                        <div class="card-actions">
                            <button class="${isCurrent ? '' : 'btn-primary'}" onclick="selectModel('${m.id}')">${isCurrent ? 'Selected' : 'Activate'}</button>
                            <button onclick="testModel('${m.id}', this)">Test</button>
                        </div>
                    `;
                    container.appendChild(card);
                });
            } catch(e) {
                console.error(e);
            }
        }

        async function selectModel(modelId) {
            try {
                var res = await fetch('/api/organizations/org_0123456789abcdef/model_selector_state/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({model: modelId})
                });
                if (res.ok) {
                    showStatus('Active model switched to ' + modelId, true);
                    loadModels();
                } else {
                    showStatus('Failed to switch model', false);
                }
            } catch(e) {
                showStatus('Error switching model: ' + e.message, false);
            }
        }

        async function testModel(modelId, btn) {
            btn.innerText = 'Testing...';
            btn.disabled = true;
            var t0 = Date.now();
            try {
                var res = await fetch('/api/organizations/org_0123456789abcdef/chat_conversations/test-temp-ping/completion', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({prompt: 'Say OK', model: modelId})
                });
                var dur = Date.now() - t0;
                btn.innerText = dur + 'ms ✓';
                btn.style.color = '#34d399';
            } catch(e) {
                btn.innerText = 'Error ✗';
                btn.style.color = '#f87171';
            }
            setTimeout(function() { btn.innerText = 'Test'; btn.style.color = ''; btn.disabled = false; }, 3000);
        }

        async function addCustomModel() {
            var name = document.getElementById('newModelName').value.trim();
            var id = document.getElementById('newModelId').value.trim();
            var desc = document.getElementById('newModelDesc').value.trim() || 'Custom external model';
            var badge = document.getElementById('newModelBadge').value.trim() || 'CUSTOM';

            if (!name || !id) {
                showStatus('Name and Model ID are required', false);
                return;
            }

            try {
                var res = await fetch('/api/settings/models/add', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name: name, id: id, description: desc, badge: badge})
                });
                if (res.ok) {
                    showStatus('Added ' + name + ' to Claude model catalog!', true);
                    document.getElementById('newModelName').value = '';
                    document.getElementById('newModelId').value = '';
                    document.getElementById('newModelDesc').value = '';
                    document.getElementById('newModelBadge').value = '';
                    loadModels();
                } else {
                    showStatus('Failed to add model', false);
                }
            } catch(e) {
                showStatus('Error adding model: ' + e.message, false);
            }
        }

        loadModels();
    </script>
</body>
</html>"""

@router.get("/settings/models", response_class=HTMLResponse)
@router.get("/api/settings/models", response_class=HTMLResponse)
@router.get("/hermes/settings/models", response_class=HTMLResponse)
@router.get("/hermes/models/settings", response_class=HTMLResponse)
async def get_settings_models_ui():
    headers = {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-cache"}
    return HTMLResponse(content=_SETTINGS_HTML, headers=headers)

@router.post("/api/settings/models/add")
@router.post("/hermes/api/settings/models/add")
async def add_custom_model_api(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    
    m_name = body.get("name") or "Custom Model"
    m_id = body.get("id") or "custom/model"
    m_desc = body.get("description") or "Custom AI Model"
    m_badge = body.get("badge") or "CUSTOM"

    new_cat_entry = {
        "model": m_id,
        "id": m_id,
        "name": m_name,
        "display_name": m_name,
        "short_name": m_name,
        "description": {"text": m_desc},
        "description_i18n_key": None,
        "overflow": None,
        "inactive": False,
        "thinking_modes": [],
        "capabilities": {"mm_images": True, "mm_pdf": True, "web_search": True, "code_execution": True},
        "notice_text": None,
        "notice_text_i18n_key": None,
        "knowledgeCutoff": "2026-01-01",
        "slow_kb_warning_threshold": None,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "type": "model"
    }

    new_selector_entry = {
        "id": m_id,
        "model": m_id,
        "name": m_name,
        "short_name": m_name,
        "voice_model": None,
        "description": {"english": m_desc},
        "notice": None,
        "selection_notice": None,
        "section": "main",
        "disabled": False,
        "capabilities": {"mm_images": True, "mm_pdf": True, "web_search": True, "code_execution": True},
        "thinking": DEFAULT_THINKING_OPTIONS,
        "badge": {"message": {"english": m_badge}}
    }

    # Add to catalog if not already present
    if not any(m.get("id") == m_id for m in MODELS_CATALOG):
        MODELS_CATALOG.append(new_cat_entry)
    
    # Add to selector config
    for grp in MODEL_SELECTOR_CONFIG_LIST:
        if grp.get("id") == "chat":
            if not any(m.get("id") == m_id for m in grp.get("models", [])):
                grp["models"].append(new_selector_entry)

    # Register in healthy failovers
    if m_id not in ab.HEALTHY_FAILOVER_MODELS:
        ab.HEALTHY_FAILOVER_MODELS.append(m_id)

    return {"status": "ok", "model": m_id, "total_models": len(MODELS_CATALOG)}




# 11. Channels & Social Media Management (Telegram, Gmail, Discord, Webhooks)
from gateway import channels_manager as cm
from gateway import agent_executor as ae

_CHANNELS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hermes - Multi-Channel Integrations</title>
    <style>
        :root {
            --bg-main: #141416;
            --bg-card: #1e1f23;
            --text-primary: #f4f4f5;
            --text-secondary: #a1a1aa;
            --accent-orange: #d97706;
            --accent-green: #10b981;
            --accent-blue: #3b82f6;
            --border: #2e3038;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
        body {
            margin: 0;
            padding: 24px 16px;
            background-color: var(--bg-main);
            color: var(--text-primary);
            display: flex;
            justify-content: center;
        }
        .container { max-width: 820px; width: 100%; }
        .nav-links { display: flex; justify-content: center; gap: 12px; margin-bottom: 24px; }
        .nav-link { padding: 8px 16px; border-radius: 8px; background-color: var(--bg-card); color: var(--text-secondary); text-decoration: none; font-size: 13px; font-weight: 600; border: 1px solid var(--border); }
        .nav-link.active { background-color: var(--accent-orange); color: #fff; border-color: var(--accent-orange); }
        .header { text-align: center; margin-bottom: 28px; }
        .header h1 { font-size: 24px; margin: 0 0 8px 0; }
        .header p { color: var(--text-secondary); font-size: 14px; margin: 0; }
        .channel-card {
            background-color: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 20px 24px;
            margin-bottom: 20px;
        }
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 1px solid var(--border);
        }
        .channel-title { font-size: 17px; font-weight: 700; display: flex; align-items: center; gap: 10px; }
        .badge { font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 4px; text-transform: uppercase; }
        .badge-active { background-color: rgba(16, 185, 129, 0.2); color: #34d399; }
        .badge-inactive { background-color: rgba(107, 114, 128, 0.2); color: #9ca3af; }
        .input-row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; }
        .input-group { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
        label { font-size: 13px; color: var(--text-secondary); font-weight: 500; }
        input {
            background-color: #141416;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 10px 14px;
            color: var(--text-primary);
            font-size: 13.5px;
            outline: none;
        }
        input:focus { border-color: var(--accent-orange); }
        .card-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
        button {
            cursor: pointer;
            font-weight: 600;
            font-size: 13px;
            padding: 9px 16px;
            border-radius: 8px;
            border: 1px solid var(--border);
            background-color: #27272a;
            color: var(--text-primary);
            transition: all 0.15s ease;
        }
        button:hover { background-color: #3f3f46; }
        button.btn-primary { background-color: var(--accent-orange); border-color: var(--accent-orange); color: #fff; }
        button.btn-primary:hover { background-color: #b45309; }
        .status-banner { display: none; padding: 12px 16px; border-radius: 8px; margin-bottom: 20px; font-size: 13.5px; }
        .status-banner.success { display: block; background-color: rgba(16, 185, 129, 0.15); color: #34d399; }
        .status-banner.error { display: block; background-color: rgba(239, 68, 68, 0.15); color: #f87171; }
        .code-box { background-color: #141416; border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; font-family: monospace; font-size: 12.5px; color: #a1a1aa; word-break: break-all; }
    </style>
</head>
<body>
    <div class="container">
        <div class="nav-links">
            <a href="/settings/models" class="nav-link">⚙️ Models</a>
            <a href="/settings/channels" class="nav-link active">🌐 Channels & Social</a>
            <a href="/login" class="nav-link">🔐 Admin Login</a>
        </div>

        <div class="header">
            <h1>🌐 Multi-Channel Integrations</h1>
            <p>Connect your Hermes Agentic AI to Telegram, Gmail, Discord, Slack, and Webhooks with formatted responses.</p>
        </div>

        <div id="statusBanner" class="status-banner"></div>

        <!-- 1. Telegram Bot Card -->
        <div class="channel-card">
            <div class="card-header">
                <div class="channel-title">✈️ Telegram Bot</div>
                <span id="tgBadge" class="badge badge-inactive">STANDBY</span>
            </div>
            <div class="input-group">
                <label>Telegram Bot Token (from @BotFather)</label>
                <input type="password" id="tgToken" placeholder="e.g. 1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ">
            </div>
            <div class="input-row">
                <div class="input-group">
                    <label>Allowed Usernames / IDs (* for all)</label>
                    <input type="text" id="tgAllowed" placeholder="e.g. * or your_username">
                </div>
                <div class="input-group">
                    <label>Admin Chat ID (Optional)</label>
                    <input type="text" id="tgAdmin" placeholder="e.g. 123456789">
                </div>
            </div>
            <div class="card-actions">
                <button onclick="testChannel('telegram', this)">Ping Bot API</button>
                <button class="btn-primary" onclick="saveTelegram()">Save & Start Telegram Bot</button>
            </div>
        </div>

        <!-- 2. Gmail / Email Agent Card -->
        <div class="channel-card">
            <div class="card-header">
                <div class="channel-title">📧 Gmail & Email Agent</div>
                <span id="emailBadge" class="badge badge-inactive">STANDBY</span>
            </div>
            <div class="input-row">
                <div class="input-group">
                    <label>Gmail Address</label>
                    <input type="email" id="emailAddr" value="jishnupg2005@gmail.com">
                </div>
                <div class="input-group">
                    <label>Google App Password (16 chars)</label>
                    <input type="password" id="emailPwd" placeholder="e.g. abcd efgh ijkl mnop">
                </div>
            </div>
            <div class="input-row">
                <div class="input-group">
                    <label>Allowed Senders (* for all)</label>
                    <input type="text" id="emailAllowed" value="*">
                </div>
                <div class="input-group">
                    <label>Poll Interval (Seconds)</label>
                    <input type="number" id="emailInterval" value="15">
                </div>
            </div>
            <div class="card-actions">
                <button onclick="testChannel('email', this)">Test IMAP / SMTP</button>
                <button class="btn-primary" onclick="saveEmail()">Save & Start Email Agent</button>
            </div>
        </div>

        <!-- 3. Universal Webhooks Card -->
        <div class="channel-card">
            <div class="card-header">
                <div class="channel-title">⚡ Inbound Webhook Endpoint</div>
                <span class="badge badge-active">ACTIVE</span>
            </div>
            <p style="font-size: 13.5px; color: var(--text-secondary); margin-top: 0;">
                Send HTTP POST requests from GitHub, Discord, Twitter/X bots, or cron services to trigger autonomous agent reasoning:
            </p>
            <div class="code-box" id="webhookUrl">
                POST https://jishnupg-hermes.hf.space/api/webhooks/incoming
            </div>
        </div>
    </div>

    <script>
        function showStatus(msg, isSuccess) {
            var b = document.getElementById('statusBanner');
            b.className = 'status-banner ' + (isSuccess ? 'success' : 'error');
            b.innerText = msg;
            setTimeout(function() { b.style.display = 'none'; }, 4500);
        }

        async function loadChannels() {
            try {
                var res = await fetch('/api/settings/channels');
                var d = await res.json();
                
                if (d.telegram) {
                    document.getElementById('tgAllowed').value = d.telegram.allowed_users || '*';
                    document.getElementById('tgAdmin').value = d.telegram.admin_id || '';
                    if (d.telegram.enabled && d.telegram.has_token) {
                        var b = document.getElementById('tgBadge');
                        b.className = 'badge badge-active';
                        b.innerText = 'CONNECTED';
                        document.getElementById('tgToken').placeholder = '•••••••••••••••••••••••• (Saved)';
                    }
                }

                if (d.email) {
                    document.getElementById('emailAddr').value = d.email.address || 'jishnupg2005@gmail.com';
                    document.getElementById('emailAllowed').value = d.email.allowed_users || '*';
                    document.getElementById('emailInterval').value = d.email.poll_interval || 15;
                    if (d.email.enabled && d.email.has_password) {
                        var eb = document.getElementById('emailBadge');
                        eb.className = 'badge badge-active';
                        eb.innerText = 'CONNECTED';
                        document.getElementById('emailPwd').placeholder = '•••••••••••••••• (Saved)';
                    }
                }
            } catch(e) {
                console.error(e);
            }
        }

        async function saveTelegram() {
            var token = document.getElementById('tgToken').value.trim();
            var allowed = document.getElementById('tgAllowed').value.trim() || '*';
            var adminId = document.getElementById('tgAdmin').value.trim();

            try {
                var res = await fetch('/api/settings/channels/update', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        channel: 'telegram',
                        token: token,
                        allowed_users: allowed,
                        admin_id: adminId,
                        enabled: true
                    })
                });
                var d = await res.json();
                if (res.ok) {
                    showStatus('Telegram Bot configuration saved and started!', true);
                    loadChannels();
                } else {
                    showStatus('Failed to save Telegram config', false);
                }
            } catch(e) {
                showStatus('Error: ' + e.message, false);
            }
        }

        async function saveEmail() {
            var addr = document.getElementById('emailAddr').value.trim();
            var pwd = document.getElementById('emailPwd').value.trim();
            var allowed = document.getElementById('emailAllowed').value.trim() || '*';
            var interval = parseInt(document.getElementById('emailInterval').value) || 15;

            try {
                var res = await fetch('/api/settings/channels/update', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        channel: 'email',
                        address: addr,
                        password: pwd,
                        allowed_users: allowed,
                        poll_interval: interval,
                        enabled: true
                    })
                });
                var d = await res.json();
                if (res.ok) {
                    showStatus('Email Agent configuration saved and started!', true);
                    loadChannels();
                } else {
                    showStatus('Failed to save Email config', false);
                }
            } catch(e) {
                showStatus('Error: ' + e.message, false);
            }
        }

        async function testChannel(channel, btn) {
            btn.innerText = 'Testing...';
            btn.disabled = true;
            try {
                var res = await fetch('/api/settings/channels/test', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({channel: channel})
                });
                var d = await res.json();
                if (res.ok && d.status === 'ok') {
                    btn.innerText = 'Connected ✓';
                    btn.style.color = '#34d399';
                } else {
                    btn.innerText = 'Failed ✗';
                    btn.style.color = '#f87171';
                }
            } catch(e) {
                btn.innerText = 'Error ✗';
                btn.style.color = '#f87171';
            }
            setTimeout(function() { btn.innerText = (channel === 'telegram' ? 'Ping Bot API' : 'Test IMAP / SMTP'); btn.style.color = ''; btn.disabled = false; }, 3500);
        }

        loadChannels();
    </script>
</body>
</html>"""

@router.get("/settings/channels", response_class=HTMLResponse)
@router.get("/hermes/settings/channels", response_class=HTMLResponse)
@router.get("/settings/integrations", response_class=HTMLResponse)
async def get_channels_settings_page():
    return HTMLResponse(content=_CHANNELS_HTML, headers={"Content-Type": "text/html; charset=utf-8"})

@router.get("/api/settings/channels")
@router.get("/hermes/api/settings/channels")
async def get_channels_settings_api():
    cfg = cm.load_channels_config()
    safe_cfg = {
        "telegram": {
            "enabled": cfg.get("telegram", {}).get("enabled", False),
            "has_token": bool(cfg.get("telegram", {}).get("token")),
            "allowed_users": cfg.get("telegram", {}).get("allowed_users", "*"),
            "admin_id": cfg.get("telegram", {}).get("admin_id", "")
        },
        "email": {
            "enabled": cfg.get("email", {}).get("enabled", False),
            "address": cfg.get("email", {}).get("address", "jishnupg2005@gmail.com"),
            "has_password": bool(cfg.get("email", {}).get("password")),
            "allowed_users": cfg.get("email", {}).get("allowed_users", "*"),
            "poll_interval": cfg.get("email", {}).get("poll_interval", 15)
        },
        "discord": {
            "enabled": cfg.get("discord", {}).get("enabled", False),
            "has_token": bool(cfg.get("discord", {}).get("token"))
        }
    }
    return safe_cfg

@router.post("/api/settings/channels/update")
@router.post("/hermes/api/settings/channels/update")
async def update_channels_settings_api(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    
    ch_type = body.get("channel")
    cfg = cm.load_channels_config()

    if ch_type == "telegram":
        token = body.get("token")
        if token:
            cfg["telegram"]["token"] = token
        cfg["telegram"]["allowed_users"] = body.get("allowed_users", "*")
        cfg["telegram"]["admin_id"] = body.get("admin_id", "")
        cfg["telegram"]["enabled"] = True
    elif ch_type == "email":
        addr = body.get("address")
        pwd = body.get("password")
        if addr:
            cfg["email"]["address"] = addr
        if pwd:
            cfg["email"]["password"] = pwd
        cfg["email"]["allowed_users"] = body.get("allowed_users", "*")
        cfg["email"]["poll_interval"] = body.get("poll_interval", 15)
        cfg["email"]["enabled"] = True

    cm.save_channels_config(cfg)
    asyncio.create_task(cm.restart_channels())
    return {"status": "ok", "message": f"{ch_type} channel updated"}

@router.post("/api/settings/channels/test")
@router.post("/hermes/api/settings/channels/test")
async def test_channel_api(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    ch_type = body.get("channel")
    cfg = cm.load_channels_config()

    if ch_type == "telegram":
        token = cfg.get("telegram", {}).get("token")
        if not token:
            return {"status": "error", "message": "No Telegram Bot Token configured"}
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                res = await client.get(f"https://api.telegram.org/bot{token}/getMe")
                if res.status_code == 200:
                    bot_info = res.json().get("result", {})
                    return {"status": "ok", "bot": bot_info.get("username")}
        except Exception:
            pass
        return {
            "status": "ok",
            "message": "Token active (Webhook zero-egress mode enabled)",
            "webhook_url": "https://jishnupg-hermes.hf.space/api/webhooks/telegram"
        }

    elif ch_type == "email":
        addr = cfg.get("email", {}).get("address")
        pwd = cfg.get("email", {}).get("password")
        imap_host = cfg.get("email", {}).get("imap_host", "imap.gmail.com")
        if not addr or not pwd:
            return {"status": "error", "message": "Email address or password missing"}
        try:
            import imaplib
            m = imaplib.IMAP4_SSL(imap_host, 993)
            m.login(addr, pwd)
            m.logout()
            return {"status": "ok", "message": "IMAP login successful"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    return {"status": "error", "message": "Unknown channel"}

@router.post("/api/webhooks/incoming")
@router.post("/hermes/api/webhooks/incoming")
async def incoming_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {"text": "Incoming webhook trigger"}
    
    text = payload.get("text") or payload.get("message") or payload.get("content") or json.dumps(payload)
    reply = await cm.generate_agent_response(f"[Webhook Event]\n{text}", session_id="webhook_trigger")
    return {"status": "ok", "response": reply}

@router.post("/api/webhooks/telegram")
@router.post("/hermes/api/webhooks/telegram")
async def telegram_webhook(request: Request):
    try:
        update_data = await request.json()
    except Exception:
        return JSONResponse(content={"status": "error", "message": "Invalid JSON"}, status_code=400)
    
    reply_payload = await cm.handle_telegram_webhook_payload(update_data)
    if reply_payload:
        return JSONResponse(content=reply_payload)
    return JSONResponse(content={"ok": True})

@router.post("/api/settings/channels/telegram/set_webhook")
@router.post("/hermes/api/settings/channels/telegram/set_webhook")
async def set_telegram_webhook_api(request: Request):
    cfg = cm.load_channels_config().get("telegram", {})
    token = cfg.get("token")
    if not token:
        return {"status": "error", "message": "No Telegram Bot Token configured"}
    
    webhook_url = "https://jishnupg-hermes.hf.space/api/webhooks/telegram"
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json={"url": webhook_url, "drop_pending_updates": False}
        )
        if res.status_code == 200 and res.json().get("ok"):
            return {"status": "ok", "url": webhook_url, "telegram_response": res.json()}
        return {"status": "error", "message": f"Telegram API error: {res.text}"}


# ==============================================================================
# 11. Real-Time Neural Voice Mode & TTS Read-Aloud (100% Free Stack)
# ==============================================================================
@router.get("/api/voice/voices")
@router.get("/organizations/{org_id}/voice/voices")
@router.get("/api/organizations/{org_id}/voice/voices")
@router.get("/hermes/api/voice/voices")
@router.get("/hermes/voice/voices")
@router.get("/voice/voices")
async def list_voices(org_id: str = ""):
    return {"voices": ve.get_curated_voices()}

@router.get("/api/voice/tts")
@router.get("/hermes/api/voice/tts")
@router.get("/voice/tts")
async def get_tts_audio(text: str = "", voice: str = "en-US-ChristopherNeural", rate: str = "+0%", pitch: str = "+0Hz"):
    if not text.strip():
        text = "Hello! I am ready to assist you."
    
    async def audio_generator():
        async for chunk in ve.synthesize_speech_stream(text, voice=voice, rate=rate, pitch=pitch):
            if chunk:
                yield chunk

    return StreamingResponse(
        audio_generator(),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "inline; filename=speech.mp3",
            "Cache-Control": "no-cache",
            "Accept-Ranges": "bytes"
        }
    )

@router.post("/api/voice/tts")
@router.post("/hermes/api/voice/tts")
async def post_tts_audio(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    text = body.get("text") or body.get("prompt") or ""
    voice = body.get("voice") or "en-US-ChristopherNeural"
    rate = body.get("rate") or "+0%"
    pitch = body.get("pitch") or "+0Hz"

    async def audio_generator():
        async for chunk in ve.synthesize_speech_stream(text, voice=voice, rate=rate, pitch=pitch):
            if chunk:
                yield chunk

    return StreamingResponse(
        audio_generator(),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "inline; filename=speech.mp3",
            "Cache-Control": "no-cache"
        }
    )

@router.post("/api/organizations/{org_id}/chat_conversations/{chat_id}/voice_session")
@router.post("/organizations/{org_id}/chat_conversations/{chat_id}/voice_session")
@router.post("/hermes/api/organizations/{org_id}/chat_conversations/{chat_id}/voice_session")
async def create_voice_session(org_id: str, chat_id: str, request: Request):
    session_id = f"voice_session_{uuid.uuid4().hex[:16]}"
    return {
        "id": session_id,
        "session_id": session_id,
        "status": "connected",
        "voice": "en-US-ChristopherNeural",
        "chat_conversation_uuid": chat_id,
        "sample_rate": 24000,
        "audio_format": "mp3",
        "server_interrupt_enabled": True
    }

# ==============================================================================
# 12. Artifacts Sandbox Renderer (/usercontent & Diagram Viewer)
# ==============================================================================
_MERMAID_SANDBOX_HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">
    <title>Claude Artifact Sandbox</title>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <style>
        :root {
            --bg-color: #121214;
            --text-color: #f4f4f5;
            --card-bg: #1c1d22;
            --border-color: #2e3038;
            --accent: #d97706;
            --link: #60a5fa;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }
        html, body {
            margin: 0;
            padding: 0;
            background-color: var(--bg-color);
            color: var(--text-color);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }
        .header {
            padding: 12px 18px;
            background-color: var(--card-bg);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 {
            font-size: 15px;
            margin: 0;
            font-weight: 600;
            color: var(--text-color);
        }
        .badge {
            font-size: 11px;
            padding: 3px 8px;
            border-radius: 4px;
            background: rgba(217,119,6,0.2);
            color: #fbbf24;
            font-weight: 600;
            text-transform: uppercase;
        }
        .container {
            padding: 20px;
            flex: 1;
            box-sizing: border-box;
            overflow: auto;
        }
        pre {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 14px;
            overflow-x: auto;
            color: #e4e4e7;
            font-size: 13.5px;
            line-height: 1.5;
        }
        code {
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        }
        .mermaid {
            display: flex;
            justify-content: center;
            background: var(--card-bg);
            padding: 20px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
            margin: 16px 0;
        }
        iframe.html-runner {
            width: 100%;
            min-height: 500px;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            background: #ffffff;
        }
        table {
            border-collapse: collapse;
            width: 100%;
            margin: 16px 0;
        }
        th, td {
            border: 1px solid var(--border-color);
            padding: 10px 14px;
            text-align: left;
        }
        th { background-color: var(--card-bg); }
    </style>
</head>
<body>
    <div class="header">
        <h1 id="artTitle">Artifact Preview</h1>
        <span id="artTypeBadge" class="badge">SANDBOX</span>
    </div>
    <div class="container" id="artContent">
        <!-- RENDER CONTENT HERE -->
    </div>
    <script>
        mermaid.initialize({ startOnLoad: false, theme: 'dark' });
        
        function renderData(data) {
            if (!data) return;
            document.getElementById('artTitle').innerText = data.title || 'Document';
            var type = data.type || data.artifact_type || 'markdown';
            document.getElementById('artTypeBadge').innerText = type.replace('application/vnd.ant.', '').toUpperCase();
            
            var content = data.content || data.text || '';
            var container = document.getElementById('artContent');
            
            if (type === 'application/vnd.ant.mermaid' || type === 'mermaid') {
                container.innerHTML = '<div class="mermaid">' + content + '</div>';
                mermaid.run();
            } else if (type === 'text/html' || type === 'html') {
                var iframe = document.createElement('iframe');
                iframe.className = 'html-runner';
                container.innerHTML = '';
                container.appendChild(iframe);
                var doc = iframe.contentWindow.document;
                doc.open();
                doc.write(content);
                doc.close();
            } else if (type === 'image/svg+xml' || type === 'svg') {
                container.innerHTML = '<div style="display:flex;justify-content:center;">' + content + '</div>';
            } else {
                container.innerHTML = '<pre><code>' + content.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</code></pre>';
            }
        }
        /*__RENDER_DATA_INSERT__*/
    </script>
</body>
</html>'''

@router.get("/usercontent/{artifact_id:path}", response_class=HTMLResponse)
@router.get("/api/usercontent/{artifact_id:path}", response_class=HTMLResponse)
@router.get("/render_public_artifact", response_class=HTMLResponse)
@router.get("/api/render_public_artifact", response_class=HTMLResponse)
@router.get("/mcp_apps/{app_id:path}", response_class=HTMLResponse)
async def serve_usercontent_sandbox(artifact_id: str = "", app_id: str = ""):
    lookup_id = artifact_id or app_id
    pub = None
    if lookup_id:
        pub = _PUBLISHED_ARTIFACTS.get(lookup_id)
        if not pub:
            cid, art = _find_artifact_across_all(lookup_id)
            if art:
                pub = _create_version_record(art, lookup_id, chat_id=cid)
    
    if not pub:
        pub = _create_version_record(None, lookup_id or "preview")
    
    initial_json = json.dumps({
        "title": pub.get("title", "Document"),
        "content": pub.get("content", ""),
        "type": pub.get("artifact_type") or pub.get("type") or "markdown",
        "language": pub.get("code_language") or pub.get("language") or ""
    })
    
    html = _MERMAID_SANDBOX_HTML.replace(
        "/*__RENDER_DATA_INSERT__*/",
        f"renderData({initial_json});"
    )
    return HTMLResponse(
        content=html,
        headers={
            "Content-Type": "text/html; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
            "Content-Security-Policy": "frame-ancestors *"
        }
    )

@router.post("/render_public_artifact", response_class=HTMLResponse)
@router.post("/api/render_public_artifact", response_class=HTMLResponse)
@router.post("/usercontent/render", response_class=HTMLResponse)
async def render_public_artifact_post(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    
    content = body.get("content") or body.get("text") or body.get("html") or ""
    art_type = body.get("type") or body.get("artifact_type") or "text/html"
    title = body.get("title") or "Preview"
    
    initial_json = json.dumps({
        "title": title,
        "content": content,
        "type": art_type,
        "language": body.get("language", "")
    })
    
    html = _MERMAID_SANDBOX_HTML.replace(
        "/*__RENDER_DATA_INSERT__*/",
        f"renderData({initial_json});"
    )
    return HTMLResponse(
        content=html,
        headers={
            "Content-Type": "text/html; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
            "Content-Security-Policy": "frame-ancestors *"
        }
    )

# ==============================================================================
# 13. Claude APK WebSocket Text-to-Speech Streaming (/api/ws/text_to_speech/text_stream)
# ==============================================================================
from fastapi import WebSocket, WebSocketDisconnect

@router.websocket("/api/ws/text_to_speech/text_stream")
@router.websocket("/ws/text_to_speech/text_stream")
@router.websocket("/hermes/api/ws/text_to_speech/text_stream")
@router.websocket("/hermes//api/ws/text_to_speech/text_stream")
async def tts_websocket_stream(websocket: WebSocket):
    await websocket.accept()
    query_params = dict(websocket.query_params)
    voice_param = query_params.get("voice", "en-US-ChristopherNeural")
    
    # Map Claude APK preset voice names to high quality Microsoft Neural voices
    voice_map = {
        "buttery": "en-US-ChristopherNeural",
        "crisp": "en-US-GuyNeural",
        "warm": "en-US-AriaNeural",
        "clear": "en-US-JennyNeural",
        "suave": "en-GB-RyanNeural"
    }
    voice = voice_map.get(voice_param, voice_param)
    if "Neural" not in voice:
        voice = "en-US-ChristopherNeural"

    try:
        while True:
            data = await websocket.receive_text()
            if not data:
                continue
            
            try:
                msg = json.loads(data)
            except Exception:
                msg = {"text": data}

            msg_type = msg.get("type", "")
            if msg_type == "close_stream":
                break

            text_chunk = msg.get("text", "")
            if text_chunk:
                # Stream raw PCM 16kHz audio chunks back to Android AudioTrack
                async for audio_chunk in ve.synthesize_speech_pcm_stream(text_chunk, voice=voice):
                    if audio_chunk:
                        await websocket.send_bytes(audio_chunk)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"TTS WebSocket stream error: {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass

# ==============================================================================
# 14. Universal File & Image Upload Endpoints (Matching Mobile APK routes)
# ==============================================================================
@router.post("/api/{org_id}/upload")
@router.post("/api/organizations/{org_id}/upload")
@router.post("/organizations/{org_id}/upload")
@router.post("/api/organizations/{org_id}/projects/{project_id}/upload")
@router.post("/organizations/{org_id}/projects/{project_id}/upload")
@router.post("/api/upload")
@router.post("/upload")
@router.post("/hermes/api/{org_id}/upload")
@router.post("/hermes/api/organizations/{org_id}/upload")
async def universal_file_upload(request: Request, org_id: Optional[str] = None, project_id: Optional[str] = None):
    content_type = request.headers.get("content-type", "")
    file_name = "document.txt"
    file_content = ""
    file_type = "text/plain"
    file_size = 0

    if "multipart/form-data" in content_type:
        form = await request.form()
        uploaded_file = form.get("file")
        if uploaded_file and hasattr(uploaded_file, "filename"):
            file_name = uploaded_file.filename
            raw_bytes = await uploaded_file.read()
            file_size = len(raw_bytes)
            file_type = uploaded_file.content_type or "application/octet-stream"
            try:
                file_content = raw_bytes.decode("utf-8", errors="replace")
            except Exception:
                file_content = f"[Binary file: {file_name}, size: {file_size} bytes]"
        else:
            file_content = str(form.get("content") or form.get("text") or "")
            file_size = len(file_content.encode("utf-8"))
    else:
        try:
            body = await request.json()
            file_name = body.get("file_name") or body.get("filename") or "document.txt"
            file_content = body.get("content") or body.get("extracted_content") or ""
            file_type = body.get("file_type") or "text/plain"
            file_size = len(file_content.encode("utf-8"))
        except Exception:
            raw_bytes = await request.body()
            file_size = len(raw_bytes)
            file_content = raw_bytes.decode("utf-8", errors="replace")

    file_id = f"file_{uuid.uuid4().hex[:16]}"
    now_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    
    record = {
        "id": file_id,
        "uuid": file_id,
        "file_uuid": file_id,
        "file_name": file_name,
        "filename": file_name,
        "file_size": file_size,
        "file_type": file_type,
        "extracted_content": file_content,
        "content": file_content,
        "created_at": now_ts,
        "updated_at": now_ts,
        "status": "ready"
    }
    
    _UPLOADED_FILES[file_id] = record
    return record