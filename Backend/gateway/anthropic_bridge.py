# ==============================================================================
# Anthropic Messages API bridge for the (patched) Claude Android app.
#
# The patched app POSTs Anthropic-format requests to /hermes/v1/messages.
# Upstream = Hermes agent API server (127.0.0.1:8642) which calls OmniRoute.
# Hermes agent produces rich content: thinking, artifacts, tool calls, text.
# This bridge translates:
#   Anthropic request -> OpenAI payload -> Hermes agent
#   Hermes agent SSE -> Anthropic Messages SSE with rich content blocks
# ==============================================================================

import json
import os
import uuid
import re
from typing import AsyncGenerator, Dict, List, Optional, Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter(tags=["AnthropicBridge"])

# Upstream = Internal Hermes Agent API server (runs on port 8642 inside container)
# The Hermes Agent internally calls OmniRoute for LLM inference
UPSTREAM_URL = os.getenv(
    "ANTHROPIC_BRIDGE_UPSTREAM_URL",
    "http://127.0.0.1:8642/v1/chat/completions"
)

UPSTREAM_KEY = os.getenv(
    "ANTHROPIC_BRIDGE_UPSTREAM_KEY",
    os.getenv("API_SERVER_KEY", os.getenv("OMNIROUTE_API_KEY", "sk-2e556e0437ee2958-7baf2d-b4133935")),
)
UPSTREAM_MODEL = os.getenv("ANTHROPIC_BRIDGE_UPSTREAM_MODEL", "antigravity/gemini-3.6-flash-medium")
DEFAULT_APP_MODEL = os.getenv("HERMES_ANTHROPIC_MODEL", "hermes-agent")


ARTIFACT_PATTERN = re.compile(
    r'<antArtifact\s+([^>]+)>(.*?)(?:</antArtifact>|$)',
    re.DOTALL | re.IGNORECASE
)

THINKING_PATTERN = re.compile(
    r'<thinking>(.*?)</thinking>',
    re.DOTALL | re.IGNORECASE
)

THINKING_SUMMARY_PATTERN = re.compile(
    r'<thinkingSummary>(.*?)</thinkingSummary>',
    re.DOTALL | re.IGNORECASE
)


def extract_artifacts(text: str) -> List[Dict[str, Any]]:
    """Extract artifact blocks from text."""
    artifacts = []
    for match in ARTIFACT_PATTERN.finditer(text):
        attrs_str = match.group(1)
        content = match.group(2).strip()
        attrs = dict(re.findall(r'([a-zA-Z0-9_]+)="([^"]+)"', attrs_str))
        art_id = attrs.get("identifier") or attrs.get("id") or f"art_{uuid.uuid4().hex[:12]}"
        title = attrs.get("title") or "Artifact"
        art_type = attrs.get("artifactType") or attrs.get("type") or "application/vnd.ant.markdown"
        artifacts.append({
            "identifier": art_id,
            "title": title,
            "artifactType": art_type,
            "content": content
        })
    return artifacts


def extract_thinking(text: str) -> List[str]:
    """Extract thinking blocks from text."""
    return [m.group(1).strip() for m in THINKING_PATTERN.finditer(text)]


def extract_thinking_summaries(text: str) -> List[str]:
    """Extract thinking summaries from text."""
    return [m.group(1).strip() for m in THINKING_SUMMARY_PATTERN.finditer(text)]


def remove_special_blocks(text: str) -> str:
    """Remove artifact, thinking, and thinkingSummary tags from text."""
    text = ARTIFACT_PATTERN.sub("", text)
    text = THINKING_PATTERN.sub("", text)
    text = THINKING_SUMMARY_PATTERN.sub("", text)
    return text.strip()


def messages_to_openai(anthropic_messages: list) -> list:
    out = []
    for m in anthropic_messages:
        content = m.get("content")
        if isinstance(content, list):
            text = "".join(
                b.get("text", "") for b in content if b.get("type") == "text"
            )
        else:
            text = content or ""
        out.append({"role": m.get("role", "user"), "content": text})
    return out


def system_to_openai(system) -> str:
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "".join(
            b.get("text", "") for b in system if b.get("type") == "text"
        )
    return str(system or "")


import time

# Verified Healthy Models (Ranked by speed, reliability, and capability)
HEALTHY_FAILOVER_MODELS = [
    "auto/smart",
    "auto/best-fast",
    "auto/fast",
    "auto/coding",
    "auto/best-coding",
    "auto/best-chat",
    "antigravity/gemini-2.5-flash-thinking",
    "groq/llama-3.3-70b-versatile"
]

MODEL_COOLDOWN_MAP: Dict[str, float] = {} # model_name -> expiration timestamp
ACTIVE_HERMES_MODEL = "auto/smart"
CONVERSATION_MODEL_MAP: Dict[str, str] = {} # chat_id -> model_name

def set_active_model(model_name: str, chat_id: Optional[str] = None):
    global ACTIVE_HERMES_MODEL
    if chat_id:
        CONVERSATION_MODEL_MAP[chat_id] = model_name
    else:
        ACTIVE_HERMES_MODEL = model_name

MODEL_ALIAS_MAP = {
    "claude-3-5-sonnet-20241022": "auto/smart",
    "claude-3-5-haiku-20241022": "auto/best-fast",
    "claude-3-opus-20240229": "auto/best-coding",
    "hermes-agent": "auto/smart",
    "default": "auto/smart"
}

def get_candidate_models(requested_model: Optional[str] = None, chat_id: Optional[str] = None) -> List[str]:
    candidates = []
    now = time.time()
    
    # 1. Check conversation-specific override
    if chat_id and chat_id in CONVERSATION_MODEL_MAP:
        conv_m = CONVERSATION_MODEL_MAP[chat_id]
        mapped = MODEL_ALIAS_MAP.get(conv_m, conv_m)
        if mapped not in candidates:
            candidates.append(mapped)
    
    # 2. Check requested model
    if requested_model:
        mapped_req = MODEL_ALIAS_MAP.get(requested_model, requested_model)
        if mapped_req not in candidates:
            candidates.append(mapped_req)
            
    # 3. Add global active model
    mapped_active = MODEL_ALIAS_MAP.get(ACTIVE_HERMES_MODEL, ACTIVE_HERMES_MODEL)
    if mapped_active not in candidates:
        candidates.append(mapped_active)
        
    # 4. Add all healthy failover models
    for m in HEALTHY_FAILOVER_MODELS:
        if m not in candidates:
            candidates.append(m)
            
    # Prioritize active models not in cooldown
    active = [m for m in candidates if MODEL_COOLDOWN_MAP.get(m, 0) < now]
    cooled = [m for m in candidates if MODEL_COOLDOWN_MAP.get(m, 0) >= now]
    return active + cooled

FALLBACK_URLS = [
    UPSTREAM_URL,
    "http://127.0.0.1:8642/v1/chat/completions",
]

async def stream_upstream(payload: dict, requested_model: Optional[str] = None, chat_id: Optional[str] = None):
    """Stream raw SSE data lines from upstream with automatic cascading model and endpoint fallback."""
    last_err = None
    urls_to_try = list(dict.fromkeys(FALLBACK_URLS))
    candidate_models = get_candidate_models(requested_model or payload.get("model"), chat_id)

    # Limit candidate attempts to the top 3 best models with a 6s stream connection timeout
    for model_name in candidate_models[:3]:
        payload_copy = dict(payload)
        payload_copy["model"] = model_name
        model_succeeded = False

        for url in urls_to_try:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=12.0, write=5.0, pool=5.0)) as client:
                    async with client.stream(
                        "POST",
                        url,
                        headers={
                            "Authorization": f"Bearer {UPSTREAM_KEY}",
                            "Content-Type": "application/json",
                        },
                        json=payload_copy,
                    ) as r:
                        if r.status_code == 200:
                            has_yielded = False
                            async for line in r.aiter_lines():
                                line = line.strip()
                                if not line:
                                    continue
                                if line == "data: [DONE]" or line == "[DONE]":
                                    if has_yielded:
                                        yield "[DONE]"
                                        model_succeeded = True
                                        return
                                    break
                                if line.startswith("data: "):
                                    data_content = line[6:].strip()
                                    if data_content == "[DONE]":
                                        if has_yielded:
                                            yield "[DONE]"
                                            model_succeeded = True
                                            return
                                        break
                                    try:
                                        chunk_obj = json.loads(data_content)
                                        if chunk_obj.get("id") == "omniroute-keepalive":
                                            continue
                                        finish_reason = chunk_obj.get("choices", [{}])[0].get("finish_reason")
                                        has_yielded = True
                                        yield data_content
                                        if finish_reason in ("stop", "end_turn", "length", "tool_calls"):
                                            yield "[DONE]"
                                            model_succeeded = True
                                            return
                                    except Exception:
                                        has_yielded = True
                                        yield data_content
                            if has_yielded:
                                model_succeeded = True
                                return
                        elif r.status_code == 429:
                            MODEL_COOLDOWN_MAP[model_name] = time.time() + 60
                            last_err = f"Model {model_name} rate limited (HTTP 429) from {url}"
                            break
                        else:
                            last_err = f"HTTP {r.status_code} from {url} for model {model_name}"
            except Exception as e:
                last_err = f"{url} ({model_name}): {e}"
                continue

        if model_succeeded:
            return
        else:
            MODEL_COOLDOWN_MAP[model_name] = time.time() + 60

    if last_err:
        raise RuntimeError(f"All upstream models failed: {last_err}")


async def assemble_upstream(payload: dict) -> tuple:
    """Consume upstream SSE and assemble full text + usage."""
    text_parts = []
    prompt_tokens = 0
    completion_tokens = 0
    async for data in stream_upstream(payload):
        data = data.strip()
        if not data or data == "[DONE]":
            continue
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        delta = chunk.get("choices", [{}])[0].get("delta", {}) or {}
        piece = delta.get("content")
        if piece:
            text_parts.append(piece)
        usage = chunk.get("usage") or {}
        if usage:
            prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
            completion_tokens = usage.get("completion_tokens", completion_tokens)
    return "".join(text_parts), {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }


class ContentBlockEmitter:
    """Manages emission of multiple content blocks in a single message."""
    
    def __init__(self, request_model: str):
        self.request_model = request_model
        self.message_id = "msg_" + uuid.uuid4().hex
        self.block_index = 0
        self.started = False
        self.blocks_emitted = []
    
    def _next_index(self) -> int:
        idx = self.block_index
        self.block_index += 1
        return idx
    
    async def emit_message_start(self) -> str:
        msg = {
            "type": "message_start",
            "message": {
                "id": self.message_id,
                "type": "message",
                "role": "assistant",
                "model": self.request_model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        }
        return "event: message_start\ndata: " + json.dumps(msg) + "\n\n"
    
    def emit_content_block_start(self, block_type: str, block_data: dict, index: Optional[int] = None) -> str:
        idx = index if index is not None else self._next_index()
        self.blocks_emitted.append({"index": idx, "type": block_type})
        inner = {
            "type": "content_block_start",
            "index": idx,
            "content_block": block_data,
        }
        return "event: content_block_start\ndata: " + json.dumps(inner) + "\n\n"
    
    def emit_content_block_delta(self, index: int, delta_type: str, delta_data: dict) -> str:
        inner = {
            "type": "content_block_delta",
            "index": index,
            "delta": {"type": delta_type, **delta_data},
        }
        return "event: content_block_delta\ndata: " + json.dumps(inner) + "\n\n"
    
    def emit_content_block_stop(self, index: int) -> str:
        inner = {"type": "content_block_stop", "index": index}
        return "event: content_block_stop\ndata: " + json.dumps(inner) + "\n\n"
    
    def emit_message_delta(self, stop_reason: str = "end_turn") -> str:
        inner = {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }
        return "event: message_delta\ndata: " + json.dumps(inner) + "\n\n"
    
    def emit_message_stop(self) -> str:
        return "event: message_stop\ndata: " + json.dumps({"type": "message_stop"}) + "\n\n"


async def anthropic_sse(request_model: str, payload: dict) -> AsyncGenerator[str, None]:
    """Stream standard Anthropic SSE with direct text and tool use blocks."""
    emitter = ContentBlockEmitter(request_model)
    message_started = False
    text_started = False

    try:
        async for data in stream_upstream(payload, requested_model=request_model):
            data = data.strip()
            if not data or data == "[DONE]":
                continue

            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue

            delta = chunk.get("choices", [{}])[0].get("delta", {}) or {}
            piece = delta.get("content")
            tool_calls = delta.get("tool_calls")

            # 1. Initialize message on first arrival
            if not message_started:
                message_started = True
                yield await emitter.emit_message_start()

            # 2. Tool calls
            if tool_calls:
                if text_started:
                    yield emitter.emit_content_block_stop(0)
                    text_started = False

                for tc in tool_calls:
                    func = tc.get("function", {})
                    tool_idx = emitter._next_index()
                    yield emitter.emit_content_block_start("tool_use", {
                        "type": "tool_use",
                        "id": tc.get("id", f"toolu_{uuid.uuid4().hex[:24]}"),
                        "name": func.get("name", "unknown"),
                        "input": json.loads(func.get("arguments", "{}")) if isinstance(func.get("arguments"), str) else {}
                    }, index=tool_idx)
                    if func.get("arguments"):
                        yield emitter.emit_content_block_delta(tool_idx, "input_json_delta", {
                            "partial_json": func["arguments"]
                        })
                    yield emitter.emit_content_block_stop(tool_idx)
                continue

            # 3. Direct clean text streaming
            if piece:
                if not text_started:
                    text_started = True
                    yield emitter.emit_content_block_start("text", {"type": "text", "text": ""}, index=0)

                yield emitter.emit_content_block_delta(0, "text_delta", {"text": piece})

    finally:
        if message_started:
            if text_started:
                yield emitter.emit_content_block_stop(0)
            yield emitter.emit_message_delta("end_turn")
            yield emitter.emit_message_stop()


def build_openai_payload(body: dict) -> tuple:
    model = body.get("model") or DEFAULT_APP_MODEL
    max_tokens = body.get("max_tokens", 4096)
    openai_messages = messages_to_openai(body.get("messages", []))
    system = body.get("system")
    system_text = ""
    if system:
        system_text = system_to_openai(system)
    
    hermes_persona = (
        "You are Hermes Agent, a powerful, fully autonomous open-source agentic AI assistant created by Nous Research and the open-source community. "
        "You run in a full container environment with autonomous server tool execution (bash, files, background scheduling, skills). "
        "When asked who you are, ALWAYS identify yourself as Hermes Agent."
    )
    if system_text:
        combined_system = f"{hermes_persona}\n\n{system_text}"
    else:
        combined_system = hermes_persona
    openai_messages.insert(0, {"role": "system", "content": combined_system})

    payload = {
        "model": UPSTREAM_MODEL,
        "messages": openai_messages,
        "max_tokens": max_tokens,
    }
    if body.get("temperature") is not None:
        payload["temperature"] = body["temperature"]
    if body.get("top_p") is not None:
        payload["top_p"] = body["top_p"]
    return model, payload


@router.get("/hermes/v1/models")
async def models():
    return JSONResponse({
        "data": [{"type": "model", "id": UPSTREAM_MODEL}],
        "has_more": False,
    })


@router.get("/hermes/v1/directory/servers")
async def directory_servers():
    return JSONResponse({
        "servers": [{
            "id": "hermes",
            "name": "Hermes Agent",
            "url": "/hermes/v1/messages",
            "capabilities": [
                "chat",
                "completion",
                "streaming",
                "artifacts",
                "thinking",
                "tools",
                "embeddings",
                "files"
            ]
        }]
    })


@router.post("/hermes/v1/messages")
async def messages(request: Request):
    body = await request.json()
    model = body.get("model") or DEFAULT_APP_MODEL
    app_model, payload = build_openai_payload(body)

    if body.get("stream"):
        payload["stream"] = True
        return StreamingResponse(
            anthropic_sse(app_model, payload),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    payload["stream"] = True
    text, usage = await assemble_upstream(payload)
    oc = {
        "id": str(uuid.uuid4()),
        "choices": [{"message": {"content": text}}],
        "usage": usage,
    }
    return JSONResponse({
        "id": "msg_" + oc.get("id", str(uuid.uuid4())),
        "type": "message",
        "role": "assistant",
        "model": app_model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    })


def create_message_start(message_id: str, model: str, input_tokens: int = 10) -> str:
    event = {
        "type": "message_start",
        "message": {
            "id": message_id,
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": 0
            }
        }
    }
    return f"event: message_start\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


def create_thinking_block_start(index: int = 0) -> str:
    event = {
        "type": "content_block_start",
        "index": index,
        "content_block": {
            "type": "thinking",
            "thinking": ""
        }
    }
    return f"event: content_block_start\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


def create_thinking_block_delta(thinking: str, index: int = 0) -> str:
    event = {
        "type": "content_block_delta",
        "index": index,
        "delta": {
            "type": "thinking_delta",
            "thinking": thinking
        }
    }
    return f"event: content_block_delta\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


def create_thinking_block_stop(index: int = 0) -> str:
    event = {
        "type": "content_block_stop",
        "index": index
    }
    return f"event: content_block_stop\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


def create_content_block_retract(from_index: int = 0) -> str:
    event = {
        "type": "content_block_retract",
        "from_index": from_index
    }
    return f"event: content_block_retract\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


def create_thinking_block_start(index: int = 0) -> str:
    event = {
        "type": "content_block_start",
        "index": index,
        "content_block": {
            "type": "thinking",
            "thinking": ""
        }
    }
    return f"event: content_block_start\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


def create_thinking_delta(thinking_text: str, index: int = 0) -> str:
    event = {
        "type": "content_block_delta",
        "index": index,
        "delta": {
            "type": "thinking_delta",
            "thinking": thinking_text
        }
    }
    return f"event: content_block_delta\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


def create_thinking_summary_start(summary: str = "Thinking...", index: int = 0) -> str:
    return create_thinking_block_start(index)


def create_thinking_summary_delta(summary: str, index: int = 0) -> str:
    return create_thinking_delta(summary, index)



def create_content_block_start(index: int = 0) -> str:
    event = {
        "type": "content_block_start",
        "index": index,
        "content_block": {
            "type": "text",
            "text": ""
        }
    }
    return f"event: content_block_start\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


def create_content_block_delta(text: str, index: int = 0) -> str:
    event = {
        "type": "content_block_delta",
        "index": index,
        "delta": {
            "type": "text_delta",
            "text": text
        }
    }
    return f"event: content_block_delta\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


def create_content_block_stop(index: int = 0) -> str:
    event = {
        "type": "content_block_stop",
        "index": index
    }
    return f"event: content_block_stop\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


def create_message_delta(stop_reason: str = "end_turn", output_tokens: int = 15) -> str:
    event = {
        "type": "message_delta",
        "delta": {
            "stop_reason": stop_reason,
            "stop_sequence": None
        },
        "usage": {
            "output_tokens": output_tokens
        }
    }
    return f"event: message_delta\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


def create_message_stop() -> str:
    event = {
        "type": "message_stop"
    }
    return f"event: message_stop\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


