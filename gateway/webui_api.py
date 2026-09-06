"""Hermes WebUI compatibility adapter.

This module deliberately owns only /api/* WebUI routes. The existing /v1/*
proxy and Anthropic-compatible routes are not changed.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from gateway import sessions_api as session_store

router = APIRouter(tags=["Hermes WebUI"])
logger = logging.getLogger("hermes.webui")

# The WebUI preference/project state is small metadata. Conversation messages
# continue to use the existing sessions_api JSON store at /data/sessions.
_DATA_ROOT = Path(os.getenv("HERMES_WEBUI_DATA_DIR", "/data/hermes/webui"))
if not Path("/data").exists() and "HERMES_WEBUI_DATA_DIR" not in os.environ:
    _DATA_ROOT = Path("/tmp/hermes_webui")
_DATA_ROOT.mkdir(parents=True, exist_ok=True)
_STREAMS_DIR = _DATA_ROOT / "streams"
_STREAMS_DIR.mkdir(parents=True, exist_ok=True)
_STATE_FILE = _DATA_ROOT / "state.json"
_STATE_LOCK = asyncio.Lock()
_STREAM_LOCKS: Dict[str, asyncio.Lock] = {}
_STREAM_TASKS: Dict[str, asyncio.Task] = {}

MAX_UPLOAD_BYTES = int(os.getenv("HERMES_WEBUI_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
MAX_PREVIEW_BYTES = 2 * 1024 * 1024
MAX_REPLAY_EVENTS = 4096
SESSION_TOKEN_MAX_AGE = 60 * 60 * 24 * 30
STREAM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SENSITIVE_NAMES = {
    ".env", ".env.local", ".env.production", ".git", ".gitconfig",
    "id_rsa", "id_ed25519", "credentials", "credentials.json",
    "service-account.json", "service_account.json", "authorized_keys",
}
_EXECUTABLE_SUFFIXES = {
    ".apk", ".bat", ".cmd", ".com", ".dll", ".dylib", ".exe", ".jar",
    ".js", ".msi", ".php", ".pl", ".py", ".rb", ".sh", ".so",
}

# Authentication credentials are deliberately separate from the principal
# used for resource ownership. This deployment is single-user today, so all
# valid credentials resolve to one durable principal.
WEBUI_PRINCIPAL = "webui-user"

_DEFAULT_STATE: Dict[str, Any] = {
    "projects": [],
    "memory": [],
    "goals": [],
    "tasks": [],
    "files": [],
    "workspaces": [],
    "default_model": None,
    "reasoning_effort": "medium",
    "reasoning_display": "off",
    "settings": {
        "show_cli_sessions": False,
        "show_claude_code_sessions": False,
    },
    "profiles": [],
}


def _load_state() -> Dict[str, Any]:
    try:
        if _STATE_FILE.exists():
            raw = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                state = json.loads(json.dumps(_DEFAULT_STATE))
                state.update(raw)
                # Phase 3 collections were added to the existing WebUI state
                # file. Keeping defaults here makes the migration safe for
                # installations that already have state.json.
                for key in ("projects", "memory", "goals", "tasks", "files", "workspaces", "profiles"):
                    if not isinstance(state.get(key), list):
                        state[key] = []
                return state
    except (OSError, ValueError, TypeError):
        pass
    return json.loads(json.dumps(_DEFAULT_STATE))


_WEBUI_STATE = _load_state()


def _save_state() -> None:
    temporary = _STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(_WEBUI_STATE, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, _STATE_FILE)


def _now() -> float:
    return time.time()


def _iso(ts: Optional[float] = None) -> str:
    return datetime.fromtimestamp(ts or _now(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return _now()


def _json_error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


async def _body(request: Request) -> Dict[str, Any]:
    try:
        value = await request.json()
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def _password() -> str:
    return os.getenv("HERMES_WEBUI_PASSWORD", "").strip()


def _api_key() -> str:
    """Return the optional pre-shared key without ever exposing it."""
    return os.getenv("HERMES_WEBUI_API_KEY", "").strip() or os.getenv("API_SERVER_KEY", "").strip()


def _auth_enabled() -> bool:
    return bool(_password() or _api_key())


def _make_session_token() -> str:
    issued = str(int(_now()))
    nonce = secrets.token_urlsafe(24)
    payload = f"{issued}.{nonce}"
    signature = hmac.new(_password().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _valid_session_token(token: Optional[str]) -> bool:
    if not _auth_enabled() or not token:
        return not _auth_enabled()
    configured_key = _api_key()
    if configured_key and hmac.compare_digest(token, configured_key):
        return True
    password = _password()
    if not password:
        return False
    parts = token.split(".")
    if len(parts) != 3:
        return False
    issued, nonce, signature = parts
    try:
        if _now() - int(issued) > SESSION_TOKEN_MAX_AGE or int(issued) > _now() + 60:
            return False
    except ValueError:
        return False
    expected = hmac.new(password.encode(), f"{issued}.{nonce}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def _request_token(request: Request) -> Optional[str]:
    token = request.cookies.get("hermes_webui_session")
    if token:
        return token
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def _require_access(request: Request) -> str:
    origin = request.headers.get("origin")
    if origin:
        allowed = {
            value.strip().rstrip("/")
            for value in os.getenv("HERMES_WEBUI_ALLOWED_ORIGINS", "").split(",")
            if value.strip()
        }
        forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",", 1)[0].strip()
        forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc)).split(",", 1)[0].strip()
        request_origin = f"{forwarded_proto}://{forwarded_host}"
        if origin.rstrip("/") != request_origin.rstrip("/") and origin.rstrip("/") not in allowed:
            raise HTTPException(status_code=403, detail="Request origin is not allowed")
    token = _request_token(request)
    if not _valid_session_token(token):
        raise HTTPException(status_code=401, detail="WebUI authentication required")
    if not _auth_enabled():
        return "anonymous"
    # A password login issues a fresh credential on every login. Never derive
    # ownership from that credential or logout/re-login would orphan data.
    return WEBUI_PRINCIPAL


@router.get("/api/auth/status")
async def auth_status(request: Request):
    enabled = _auth_enabled()
    return {
        "auth_enabled": enabled,
        "password_auth_enabled": bool(_password()),
        "api_key_auth_enabled": bool(_api_key()),
        "logged_in": (not enabled) or _valid_session_token(_request_token(request)),
    }


@router.post("/api/auth/login")
async def auth_login(request: Request, response: Response):
    password = _password()
    if not _auth_enabled():
        return {"ok": True, "authenticated": True}
    if not password:
        raise HTTPException(status_code=503, detail="Password login is not configured; use the configured bearer key")
    payload = await _body(request)
    supplied = payload.get("password")
    if not isinstance(supplied, str) or not hmac.compare_digest(supplied, password):
        logger.warning("WebUI authentication failure")
        raise HTTPException(status_code=401, detail="Invalid password")
    token = _make_session_token()
    response.set_cookie(
        key="hermes_webui_session",
        value=token,
        max_age=SESSION_TOKEN_MAX_AGE,
        httponly=True,
        secure=os.getenv("HERMES_WEBUI_COOKIE_SECURE", "true").lower() not in {"0", "false", "no"},
        samesite="lax",
        path="/",
    )
    return {"ok": True, "authenticated": True}


@router.post("/api/auth/logout")
async def auth_logout(response: Response):
    response.delete_cookie("hermes_webui_session", path="/")
    return {"ok": True, "authenticated": False}


# ---------------------------------------------------------------------------
# Existing session store adapter
# ---------------------------------------------------------------------------


def _session(session_id: str) -> Dict[str, Any]:
    if not SESSION_ID_RE.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="Invalid session id")
    value = session_store._SESSIONS.get(session_id)
    if not value:
        raise HTTPException(status_code=404, detail="Session not found")
    return value


def _owned_session(session_id: str, owner: str) -> Dict[str, Any]:
    """Load a WebUI session and enforce its resource ownership.

    Sessions created before ownership metadata existed are claimed by the
    current single-user principal on first WebUI access. Sessions created by
    this adapter are always tagged at creation time.
    """
    sess = _session(session_id)
    stored_owner = sess.get("webui_owner")
    if stored_owner is None:
        sess["webui_owner"] = owner
        session_store._save_data()
    elif stored_owner != owner:
        raise HTTPException(status_code=404, detail="Session not found")
    return sess


def _session_owner(session_id: str) -> Optional[str]:
    try:
        return _session(session_id).get("webui_owner")
    except HTTPException:
        return None


def _message_text(message: Dict[str, Any]) -> str:
    content = message.get("content", message.get("text", ""))
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", item.get("content", ""))))
            elif item is not None:
                parts.append(str(item))
        return "".join(parts)
    return str(content or "")


def _chat_text(payload: Dict[str, Any]) -> str:
    value = payload.get("message")
    if value is None:
        value = payload.get("prompt", payload.get("text", payload.get("content")))
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return _message_text({"content": value})
    if isinstance(value, dict):
        return _message_text(value)
    return ""


def _messages(session_id: str) -> List[Dict[str, Any]]:
    return session_store._MESSAGES.setdefault(session_id, [])


def _summary(session_id: str) -> Dict[str, Any]:
    sess = _session(session_id)
    messages = _messages(session_id)
    created = _epoch(sess.get("created_at"))
    updated = _epoch(sess.get("updated_at"))
    stream_id = sess.get("active_stream_id")
    stream_meta = _read_stream_meta(stream_id) if stream_id else None
    is_streaming = bool(stream_meta and stream_meta.get("status") in {"starting", "running"})
    return {
        "session_id": session_id,
        "title": sess.get("title") or "Chat",
        "workspace": sess.get("workspace"),
        "model": sess.get("model") or _default_model(),
        "model_provider": sess.get("model_provider") or "omniroute",
        "message_count": len(messages),
        "created_at": created,
        "updated_at": updated,
        "last_message_at": updated if messages else None,
        "pinned": bool(sess.get("pinned", False)),
        "archived": bool(sess.get("archived", False)),
        "project_id": sess.get("project_id"),
        "profile": sess.get("profile"),
        "input_tokens": sess.get("input_tokens", 0),
        "output_tokens": sess.get("output_tokens", 0),
        "estimated_cost": sess.get("estimated_cost", 0.0),
        "active_stream_id": stream_id if is_streaming else None,
        "is_streaming": is_streaming,
        "is_cli_session": False,
        "session_source": "webui",
        "parent_session_id": sess.get("parent_session_id"),
        "read_only": False,
    }


def _detail(session_id: str, include_messages: bool = True, limit: Optional[int] = 50, before: Optional[int] = None) -> Dict[str, Any]:
    sess = _session(session_id)
    result = dict(_summary(session_id))
    all_messages = _messages(session_id)
    if include_messages:
        selected = all_messages
        offset = 0
        if before is not None:
            before = max(0, before)
            selected = selected[:before]
        if limit is not None:
            limit = max(1, min(limit, 200))
            offset = max(0, len(selected) - limit)
            selected = selected[offset:]
        result["messages"] = selected
        result["_messages_offset"] = offset
        result["_messages_truncated"] = offset > 0
    else:
        result["messages"] = []
    return result


def _touch(session_id: str) -> None:
    sess = _session(session_id)
    sess["updated_at"] = _iso()
    session_store._save_data()


def _new_session(payload: Optional[Dict[str, Any]] = None, owner: str = WEBUI_PRINCIPAL) -> str:
    payload = payload or {}
    raw_id = payload.get("session_id") or payload.get("id")
    session_id = str(raw_id) if raw_id else f"sess_{secrets.token_hex(12)}"
    if not SESSION_ID_RE.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="Invalid session id")
    if session_id in session_store._SESSIONS:
        existing = session_store._SESSIONS[session_id]
        if existing.get("webui_owner") not in {None, owner}:
            raise HTTPException(status_code=404, detail="Session not found")
        existing.setdefault("webui_owner", owner)
        session_store._save_data()
        return session_id
    project_id = payload.get("project_id")
    if project_id is not None:
        _owned_project(str(project_id), owner)
    now = _iso()
    session_store._SESSIONS[session_id] = {
        "id": session_id,
        "conversation_uuid": session_id,
        "title": payload.get("title") or "Chat",
        "created_at": now,
        "updated_at": now,
        "workspace": payload.get("workspace"),
        "model": payload.get("model") or _default_model(),
        "model_provider": payload.get("model_provider") or "omniroute",
        "profile": payload.get("profile"),
        "project_id": str(project_id) if project_id is not None else None,
        "pinned": False,
        "archived": False,
        "webui_owner": owner,
    }
    session_store._MESSAGES[session_id] = []
    session_store._CONV_TO_SESSION[session_id] = session_id
    session_store._save_data()
    return session_id


@router.get("/api/sessions")
async def list_webui_sessions(
    request: Request,
    include_archived: int = 0,
    archived_limit: Optional[int] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    order: str = "created",
):
    owner = _require_access(request)
    values = []
    for sid in list(session_store._SESSIONS):
        if _session_owner(sid) not in {None, owner}:
            continue
        _owned_session(sid, owner)
        summary = _summary(sid)
        if summary["archived"] and not include_archived:
            continue
        values.append(summary)
    values.sort(key=lambda item: (item.get("pinned", False), item.get("updated_at", 0)), reverse=True)
    if include_archived and archived_limit:
        values = values[: max(1, min(archived_limit, 200))]
    # The official Hermes dashboard uses the same resource path with
    # pagination parameters. Preserve the Hermex adapter response for its
    # existing client, and return the upstream contract when those parameters
    # are present.
    if limit is not None:
        page_limit = max(1, min(limit, 100))
        ordered = sorted(
            values,
            key=lambda item: item.get("created_at", 0) if order == "created" else item.get("updated_at", 0),
            reverse=order != "created",
        )
        return {
            "sessions": [
                {
                    "id": item["session_id"],
                    "source": "webui",
                    "model": item.get("model"),
                    "title": item.get("title"),
                    "started_at": item.get("created_at", 0),
                    "ended_at": None,
                    "last_active": item.get("updated_at", 0),
                    "is_active": bool(item.get("is_streaming")),
                    "message_count": item.get("message_count", 0),
                    "tool_call_count": 0,
                    "input_tokens": item.get("input_tokens", 0),
                    "output_tokens": item.get("output_tokens", 0),
                    "preview": _message_text(_messages(item["session_id"])[-1]) if _messages(item["session_id"]) else None,
                }
                for item in ordered[offset : offset + page_limit]
            ],
            "total": len(ordered),
            "limit": page_limit,
            "offset": max(0, offset),
        }
    return {
        "sessions": values,
        "cli_count": 0,
        "archived_count": sum(
            bool(session_store._SESSIONS[sid].get("archived", False))
            for sid in session_store._SESSIONS
            if session_store._SESSIONS[sid].get("webui_owner") in {None, owner}
        ),
        "server_time": _now(),
        "server_tz": "UTC",
    }


@router.get("/api/sessions/search")
async def search_webui_sessions(request: Request, q: str = "", content: int = 0, depth: int = 1):
    owner = _require_access(request)
    needle = q.strip().lower()
    found = []
    for sid in session_store._SESSIONS:
        if _session_owner(sid) not in {None, owner}:
            continue
        _owned_session(sid, owner)
        summary = _summary(sid)
        haystack = summary["title"].lower()
        if content:
            haystack += " " + " ".join(_message_text(m).lower() for m in _messages(sid))
        if not needle or needle in haystack:
            summary["match_type"] = "content" if content and needle in haystack else "title"
            found.append(summary)
    official_results = []
    for item in found:
        session_id = item["session_id"]
        official_results.append({
            "id": session_id,
            "source": "webui",
            "model": item.get("model"),
            "title": item.get("title"),
            "started_at": item.get("created_at", 0),
            "ended_at": None,
            "last_active": item.get("updated_at", 0),
            "is_active": bool(item.get("is_streaming")),
            "message_count": item.get("message_count", 0),
            "tool_call_count": 0,
            "input_tokens": item.get("input_tokens", 0),
            "output_tokens": item.get("output_tokens", 0),
            "preview": _message_text(_messages(session_id)[-1]) if _messages(session_id) else None,
            "session_id": session_id,
            "snippet": _message_text(_messages(session_id)[-1]) if _messages(session_id) else "",
            "role": _messages(session_id)[-1].get("role") if _messages(session_id) else None,
            "session_started": item.get("created_at", 0),
        })
    return {"sessions": found, "results": official_results, "query": q, "count": len(found)}


@router.get("/api/session")
async def get_webui_session(request: Request, session_id: str, messages: int = 1, msg_limit: Optional[int] = 50, msg_before: Optional[int] = None, expand_renderable: int = 0):
    owner = _require_access(request)
    _owned_session(session_id, owner)
    return {"session": _detail(session_id, messages != 0, msg_limit, msg_before)}


@router.get("/api/session/status")
async def session_status(request: Request, session_id: str):
    owner = _require_access(request)
    sess = _owned_session(session_id, owner)
    stream_id = sess.get("active_stream_id")
    meta = _read_stream_meta(stream_id) if stream_id else None
    active = bool(meta and meta.get("status") in {"starting", "running"})
    return {
        "active": active,
        "session_id": session_id,
        "stream_id": stream_id if active else None,
        "active_stream_id": stream_id if active else None,
        "is_streaming": active,
        "replay_available": bool(meta and meta.get("seq", 0) > 0),
    }


@router.get("/api/session/usage")
async def session_usage(request: Request, session_id: str):
    owner = _require_access(request)
    sess = _owned_session(session_id, owner)
    return {
        "input_tokens": sess.get("input_tokens", 0),
        "output_tokens": sess.get("output_tokens", 0),
        "total_tokens": sess.get("input_tokens", 0) + sess.get("output_tokens", 0),
        "estimated_cost": sess.get("estimated_cost", 0.0),
        "model": sess.get("model") or _default_model(),
    }


@router.post("/api/session/new")
async def create_webui_session(request: Request):
    owner = _require_access(request)
    payload = await _body(request)
    session_id = _new_session(payload, owner)
    logger.info("WebUI session created: %s", session_id)
    return {"ok": True, "session": _summary(session_id)}


@router.post("/api/session/rename")
async def rename_webui_session(request: Request):
    owner = _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    sess = _owned_session(sid, owner)
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        return _json_error("title is required")
    sess["title"] = title.strip()[:200]
    _touch(sid)
    return {"ok": True, "session": _summary(sid)}


@router.post("/api/session/delete")
async def delete_webui_session(request: Request):
    owner = _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    _owned_session(sid, owner)
    session_store._SESSIONS.pop(sid, None)
    session_store._MESSAGES.pop(sid, None)
    session_store._save_data()
    logger.info("WebUI session deleted: %s", sid)
    return {"ok": True, "session": None}


@router.post("/api/session/clear")
async def clear_webui_session(request: Request):
    owner = _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    _owned_session(sid, owner)
    session_store._MESSAGES[sid] = []
    _touch(sid)
    return {"ok": True, "session": _detail(sid)}


@router.post("/api/session/pin")
async def pin_webui_session(request: Request):
    owner = _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    sess = _owned_session(sid, owner)
    sess["pinned"] = bool(payload.get("pinned", True))
    _touch(sid)
    return {"ok": True, "session": _summary(sid)}


@router.post("/api/session/archive")
async def archive_webui_session(request: Request):
    owner = _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    sess = _owned_session(sid, owner)
    sess["archived"] = bool(payload.get("archived", True))
    _touch(sid)
    return {"ok": True, "session": _summary(sid)}


@router.post("/api/session/move")
async def move_webui_session(request: Request):
    owner = _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    sess = _owned_session(sid, owner)
    project_id = payload.get("project_id")
    if project_id is not None:
        _owned_project(str(project_id), owner)
    sess["project_id"] = project_id
    _touch(sid)
    return {"ok": True, "session": _summary(sid)}


@router.post("/api/session/branch")
async def branch_webui_session(request: Request):
    owner = _require_access(request)
    payload = await _body(request)
    parent_id = str(payload.get("session_id", ""))
    parent = _owned_session(parent_id, owner)
    keep_count = payload.get("keep_count")
    source = list(_messages(parent_id))
    if keep_count is not None:
        try:
            source = source[: max(0, int(keep_count))]
        except (TypeError, ValueError):
            return _json_error("keep_count must be an integer")
    child_id = _new_session({
        "title": payload.get("title") or f"Branch of {parent.get('title') or 'Chat'}",
        "workspace": parent.get("workspace"),
        "model": parent.get("model"),
        "model_provider": parent.get("model_provider"),
        "profile": parent.get("profile"),
    }, owner)
    session_store._MESSAGES[child_id] = [dict(item) for item in source]
    session_store._SESSIONS[child_id]["parent_session_id"] = parent_id
    session_store._save_data()
    return {"session_id": child_id, "title": session_store._SESSIONS[child_id]["title"], "parent_session_id": parent_id}


@router.post("/api/session/truncate")
async def truncate_webui_session(request: Request):
    owner = _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    _owned_session(sid, owner)
    try:
        keep_count = max(0, int(payload.get("keep_count")))
    except (TypeError, ValueError):
        return _json_error("keep_count is required")
    session_store._MESSAGES[sid] = _messages(sid)[:keep_count]
    _touch(sid)
    return {"ok": True, "session": _detail(sid)}


@router.post("/api/session/update")
async def update_webui_session(request: Request):
    owner = _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    sess = _owned_session(sid, owner)
    for key in ("workspace", "model", "model_provider", "profile"):
        if key in payload:
            sess[key] = payload[key]
    _touch(sid)
    return {"ok": True, "session": _detail(sid, include_messages=False)}


@router.post("/api/session/compress")
async def compress_webui_session(request: Request):
    owner = _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    _owned_session(sid, owner)
    return JSONResponse(
        {
            "ok": False,
            "error": {
                "code": "compression_unsupported",
                "message": "The configured Hermes session store does not support compression",
            },
            "session": _detail(sid),
        },
        status_code=409,
    )


@router.post("/api/session/undo")
async def undo_webui_session(request: Request):
    owner = _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    _owned_session(sid, owner)
    items = _messages(sid)
    removed_items = []
    while items and items[-1].get("role") == "assistant":
        removed_items.append(items.pop())
    if items and items[-1].get("role") == "user":
        removed_items.append(items.pop())
    _touch(sid)
    preview = next((_message_text(item) for item in removed_items if item.get("role") == "user"), "")
    return {"ok": True, "removed_count": len(removed_items), "removed_preview": preview[:200]}


@router.post("/api/session/retry")
async def retry_webui_session(request: Request):
    owner = _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    _owned_session(sid, owner)
    items = _messages(sid)
    while items and items[-1].get("role") == "assistant":
        items.pop()
    last_user = next((_message_text(item) for item in reversed(items) if item.get("role") == "user"), "")
    if not last_user:
        return _json_error("No user message is available to retry", 400)
    _touch(sid)
    stream_id = _queue_chat_stream(sid, owner)
    return {"ok": True, "session_id": sid, "stream_id": stream_id, "last_user_text": last_user, "removed_count": 0}


@router.api_route("/api/session/yolo", methods=["GET", "POST"])
async def session_yolo(request: Request, session_id: Optional[str] = None):
    owner = _require_access(request)
    if request.method == "POST":
        payload = await _body(request)
        session_id = str(payload.get("session_id", ""))
        _owned_session(session_id, owner)["yolo"] = bool(payload.get("enabled", False))
        _touch(session_id)
    if not session_id:
        return {"enabled": False}
    return {"session_id": session_id, "enabled": bool(_owned_session(session_id, owner).get("yolo", False))}


@router.get("/api/session/export")
async def export_webui_session(request: Request, session_id: str, format: str = "json"):
    owner = _require_access(request)
    _owned_session(session_id, owner)
    detail = _detail(session_id)
    if format == "json":
        return Response(json.dumps(detail, ensure_ascii=False, indent=2), media_type="application/json")
    if format in {"md", "markdown", "txt"}:
        lines = [f"# {detail.get('title') or 'Chat'}", ""]
        for item in detail.get("messages", []):
            lines.extend([f"## {item.get('role', 'message').title()}", _message_text(item), ""])
        return Response("\n".join(lines), media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="{quote(session_id)}.md"'})
    return _json_error("Unsupported export format")


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


def _project(project_id: str) -> Dict[str, Any]:
    for project in _WEBUI_STATE["projects"]:
        if project.get("project_id") == project_id:
            return project
    raise HTTPException(status_code=404, detail="Project not found")


def _owned_project(project_id: str, owner: str) -> Dict[str, Any]:
    project = _project(project_id)
    stored_owner = project.get("webui_owner")
    if stored_owner is None:
        project["webui_owner"] = owner
        _save_state()
    elif stored_owner != owner:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/api/projects")
async def list_projects(request: Request):
    owner = _require_access(request)
    projects = []
    for project in _WEBUI_STATE["projects"]:
        if project.get("webui_owner") not in {None, owner}:
            continue
        projects.append(_project_summary(_owned_project(project["project_id"], owner), owner))
    return {"projects": projects}


@router.post("/api/projects")
@router.post("/api/projects/create")
async def create_project(request: Request):
    owner = _require_access(request)
    payload = await _body(request)
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        return _json_error("name is required")
    project = {
        "project_id": f"proj_{secrets.token_hex(10)}",
        "name": name.strip()[:120],
        "description": str(payload.get("description") or "")[:20000],
        "instructions": str(payload.get("instructions") or "")[:20000],
        "color": payload.get("color"),
        "archived": False,
        "created_at": _now(),
        "updated_at": _now(),
        "webui_owner": owner,
    }
    async with _STATE_LOCK:
        _WEBUI_STATE["projects"].append(project)
        _save_state()
    return {"ok": True, "project": _project_summary(project, owner)}


@router.post("/api/projects/rename")
async def rename_project(request: Request):
    owner = _require_access(request)
    payload = await _body(request)
    project = _owned_project(str(payload.get("project_id", "")), owner)
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        return _json_error("name is required")
    project["name"] = name.strip()[:120]
    if "color" in payload:
        project["color"] = payload["color"]
    project["updated_at"] = _now()
    _save_state()
    return {"ok": True, "project": _project_summary(project, owner)}


@router.post("/api/projects/delete")
async def delete_project(request: Request):
    owner = _require_access(request)
    payload = await _body(request)
    pid = str(payload.get("project_id", ""))
    _owned_project(pid, owner)
    _WEBUI_STATE["projects"] = [p for p in _WEBUI_STATE["projects"] if p.get("project_id") != pid]
    _WEBUI_STATE["memory"] = [
        item for item in _WEBUI_STATE.get("memory", [])
        if not (item.get("project_id") == pid and item.get("webui_owner") == owner)
    ]
    goal_ids = {
        item.get("id") for item in _WEBUI_STATE.get("goals", [])
        if item.get("project_id") == pid and item.get("webui_owner") == owner
    }
    _WEBUI_STATE["goals"] = [
        item for item in _WEBUI_STATE.get("goals", [])
        if item.get("id") not in goal_ids
    ]
    _WEBUI_STATE["tasks"] = [
        item for item in _WEBUI_STATE.get("tasks", [])
        if item.get("project_id") != pid and item.get("goal_id") not in goal_ids
    ]
    _WEBUI_STATE["files"] = [
        item for item in _WEBUI_STATE.get("files", [])
        if not (item.get("project_id") == pid and item.get("webui_owner") == owner)
    ]
    for sess in session_store._SESSIONS.values():
        if sess.get("project_id") == pid:
            sess["project_id"] = None
    _save_state()
    session_store._save_data()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Phase 3: project detail, persistent memory, goals, and task graphs
# ---------------------------------------------------------------------------

MEMORY_TYPES = {"personal", "project", "session", "goal", "task", "general"}
GOAL_STATUSES = {"PLANNED", "ACTIVE", "BLOCKED", "PAUSED", "COMPLETED", "CANCELLED"}
TASK_STATUSES = {"PENDING", "READY", "RUNNING", "BLOCKED", "WAITING_APPROVAL", "COMPLETED", "FAILED", "CANCELLED"}
TASK_TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}


def _phase3_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(10)}"


def _phase3_item(collection: str, item_id: str, owner: str) -> Dict[str, Any]:
    for item in _WEBUI_STATE.get(collection, []):
        if item.get("id") != item_id:
            continue
        stored_owner = item.get("webui_owner")
        if stored_owner is None:
            item["webui_owner"] = owner
            _save_state()
        elif stored_owner != owner:
            raise HTTPException(status_code=404, detail=f"{collection[:-1].title()} not found")
        return item
    raise HTTPException(status_code=404, detail=f"{collection[:-1].title()} not found")


def _project_summary(project: Dict[str, Any], owner: str) -> Dict[str, Any]:
    pid = project["project_id"]
    sessions = [
        item for item in session_store._SESSIONS.values()
        if item.get("project_id") == pid and item.get("webui_owner") in {None, owner}
    ]
    files = [
        item for item in _WEBUI_STATE.get("files", [])
        if item.get("project_id") == pid and item.get("webui_owner") in {None, owner}
    ]
    goals = [
        item for item in _WEBUI_STATE.get("goals", [])
        if item.get("project_id") == pid and item.get("webui_owner") in {None, owner}
    ]
    tasks = [
        item for item in _WEBUI_STATE.get("tasks", [])
        if item.get("project_id") == pid and item.get("webui_owner") in {None, owner}
    ]
    result = dict(project)
    result.update({
        "session_count": len(sessions),
        "file_count": len(files),
        "goal_count": len(goals),
        "active_goal_count": sum(item.get("status") == "ACTIVE" for item in goals),
        "task_count": len(tasks),
        "completed_task_count": sum(item.get("status") == "COMPLETED" for item in tasks),
    })
    return result


def _project_detail(project: Dict[str, Any], owner: str) -> Dict[str, Any]:
    result = _project_summary(project, owner)
    pid = project["project_id"]
    result["sessions"] = [
        _summary(session_id)
        for session_id, item in session_store._SESSIONS.items()
        if item.get("project_id") == pid and item.get("webui_owner") in {None, owner}
    ]
    result["files"] = [
        dict(item) for item in _WEBUI_STATE.get("files", [])
        if item.get("project_id") == pid and item.get("webui_owner") in {None, owner}
    ]
    result["memory"] = [
        dict(item) for item in _WEBUI_STATE.get("memory", [])
        if item.get("project_id") == pid and item.get("webui_owner") in {None, owner}
    ]
    result["goals"] = [_goal_summary(item, owner) for item in _WEBUI_STATE.get("goals", []) if item.get("project_id") == pid and item.get("webui_owner") in {None, owner}]
    result["tasks"] = [
        dict(item) for item in _WEBUI_STATE.get("tasks", [])
        if item.get("project_id") == pid and item.get("webui_owner") in {None, owner}
    ]
    return result


@router.get("/api/projects/{project_id}")
async def get_project(request: Request, project_id: str):
    owner = _require_access(request)
    return {"project": _project_detail(_owned_project(project_id, owner), owner)}


@router.patch("/api/projects/{project_id}")
async def update_project(request: Request, project_id: str):
    owner = _require_access(request)
    project = _owned_project(project_id, owner)
    payload = await _body(request)
    if "name" in payload:
        if not isinstance(payload["name"], str) or not payload["name"].strip():
            return _json_error("name is required")
        project["name"] = payload["name"].strip()[:120]
    for key in ("description", "instructions", "color"):
        if key in payload:
            value = payload[key]
            if key in {"description", "instructions"} and value is not None and not isinstance(value, str):
                return _json_error(f"{key} must be a string")
            project[key] = value[:20000] if isinstance(value, str) else value
    if "archived" in payload:
        project["archived"] = bool(payload["archived"])
    project["updated_at"] = _now()
    _save_state()
    return {"ok": True, "project": _project_summary(project, owner)}


@router.delete("/api/projects/{project_id}")
async def delete_project_resource(request: Request, project_id: str):
    owner = _require_access(request)
    _owned_project(project_id, owner)
    _WEBUI_STATE["projects"] = [p for p in _WEBUI_STATE["projects"] if p.get("project_id") != project_id]
    goal_ids = {
        item.get("id") for item in _WEBUI_STATE.get("goals", [])
        if item.get("project_id") == project_id and item.get("webui_owner") == owner
    }
    for key in ("memory", "files"):
        _WEBUI_STATE[key] = [
            item for item in _WEBUI_STATE.get(key, [])
            if not (item.get("project_id") == project_id and item.get("webui_owner") == owner)
        ]
    _WEBUI_STATE["goals"] = [item for item in _WEBUI_STATE.get("goals", []) if item.get("id") not in goal_ids]
    _WEBUI_STATE["tasks"] = [
        item for item in _WEBUI_STATE.get("tasks", [])
        if item.get("project_id") != project_id and item.get("goal_id") not in goal_ids
    ]
    for sess in session_store._SESSIONS.values():
        if sess.get("project_id") == project_id:
            sess["project_id"] = None
    _save_state()
    session_store._save_data()
    return {"ok": True, "deleted_id": project_id}


@router.get("/api/projects/{project_id}/sessions")
async def project_sessions(request: Request, project_id: str):
    owner = _require_access(request)
    _owned_project(project_id, owner)
    return {"sessions": [
        _summary(session_id) for session_id, item in session_store._SESSIONS.items()
        if item.get("project_id") == project_id and item.get("webui_owner") in {None, owner}
    ]}


@router.get("/api/projects/{project_id}/files")
async def project_files(request: Request, project_id: str):
    owner = _require_access(request)
    _owned_project(project_id, owner)
    return {"files": [
        dict(item) for item in _WEBUI_STATE.get("files", [])
        if item.get("project_id") == project_id and item.get("webui_owner") in {None, owner}
    ]}


def _memory_summary(item: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(item)
    result.pop("webui_owner", None)
    return result


def _memory_matches(item: Dict[str, Any], query: str) -> bool:
    if not query:
        return True
    haystack = " ".join(str(item.get(key, "")) for key in ("content", "category", "type", "source", "session_id", "project_id"))
    return query.lower() in haystack.lower()


def _new_memory(payload: Dict[str, Any], owner: str, project_id: Optional[str] = None) -> Dict[str, Any]:
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(status_code=400, detail="content is required")
    resolved_project_id = project_id or payload.get("project_id")
    if resolved_project_id:
        _owned_project(str(resolved_project_id), owner)
    memory_type = str(payload.get("type") or ("project" if resolved_project_id else "personal")).lower()
    if memory_type not in MEMORY_TYPES:
        raise HTTPException(status_code=400, detail=f"type must be one of {sorted(MEMORY_TYPES)}")
    session_id = payload.get("session_id")
    if session_id:
        _owned_session(str(session_id), owner)
    now = _now()
    item = {
        "id": _phase3_id("mem"),
        "content": content.strip()[:50000],
        "category": str(payload.get("category") or memory_type)[:100],
        "type": memory_type,
        "source": str(payload.get("source") or "WebUI")[:200],
        "created_at": now,
        "updated_at": now,
        "project_id": str(resolved_project_id) if resolved_project_id else None,
        "session_id": str(session_id) if session_id else None,
        "goal_id": payload.get("goal_id"),
        "confidence": payload.get("confidence"),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        "webui_owner": owner,
    }
    _WEBUI_STATE.setdefault("memory", []).append(item)
    _save_state()
    # Keep the existing Hermes semantic index aware of WebUI-created memory.
    try:
        from hermes_core.tools.memory_tools import index_document_vector
        index_document_vector(
            source=f"webui_{memory_type}",
            title=item["id"],
            content=item["content"],
            metadata={"memory_id": item["id"], "project_id": resolved_project_id, "owner": owner},
        )
    except Exception:
        logger.debug("Semantic memory indexing unavailable", exc_info=True)
    return item


@router.get("/api/memory")
async def list_memory(request: Request, q: str = "", project_id: Optional[str] = None, memory_type: Optional[str] = None, limit: int = 100):
    owner = _require_access(request)
    if project_id:
        _owned_project(project_id, owner)
    values = []
    for item in _WEBUI_STATE.get("memory", []):
        if item.get("webui_owner") not in {None, owner}:
            continue
        if project_id is not None and item.get("project_id") != project_id:
            continue
        if memory_type and item.get("type") != memory_type.lower():
            continue
        if _memory_matches(item, q.strip()):
            values.append(_memory_summary(item))
    values.sort(key=lambda item: item.get("updated_at", 0), reverse=True)
    return {"memory": values[: max(1, min(limit, 500))], "count": len(values), "query": q}


@router.post("/api/memory")
async def create_memory(request: Request):
    owner = _require_access(request)
    return {"ok": True, "memory": _memory_summary(_new_memory(await _body(request), owner))}


@router.get("/api/projects/{project_id}/memory")
async def list_project_memory(request: Request, project_id: str, q: str = "", limit: int = 100):
    owner = _require_access(request)
    _owned_project(project_id, owner)
    result = await list_memory(request, q=q, project_id=project_id, limit=limit)
    return result


@router.post("/api/projects/{project_id}/memory")
async def create_project_memory(request: Request, project_id: str):
    owner = _require_access(request)
    return {"ok": True, "memory": _memory_summary(_new_memory(await _body(request), owner, project_id))}


@router.patch("/api/memory/{memory_id}")
async def update_memory(request: Request, memory_id: str):
    owner = _require_access(request)
    item = _phase3_item("memory", memory_id, owner)
    payload = await _body(request)
    for key in ("content", "category", "type", "source", "confidence", "metadata"):
        if key not in payload:
            continue
        if key == "content":
            if not isinstance(payload[key], str) or not payload[key].strip():
                return _json_error("content is required")
            item[key] = payload[key].strip()[:50000]
        elif key == "type":
            value = str(payload[key]).lower()
            if value not in MEMORY_TYPES:
                return _json_error(f"type must be one of {sorted(MEMORY_TYPES)}")
            item[key] = value
        elif key == "metadata":
            if not isinstance(payload[key], dict):
                return _json_error("metadata must be an object")
            item[key] = payload[key]
        else:
            item[key] = payload[key]
    item["updated_at"] = _now()
    _save_state()
    return {"ok": True, "memory": _memory_summary(item)}


@router.delete("/api/memory/{memory_id}")
async def delete_memory(request: Request, memory_id: str):
    owner = _require_access(request)
    _phase3_item("memory", memory_id, owner)
    _WEBUI_STATE["memory"] = [
        item for item in _WEBUI_STATE.get("memory", [])
        if item.get("id") != memory_id
    ]
    _save_state()
    return {"ok": True, "deleted_id": memory_id}


def _goal_tasks(goal_id: str, owner: str) -> List[Dict[str, Any]]:
    return [
        item for item in _WEBUI_STATE.get("tasks", [])
        if item.get("goal_id") == goal_id and item.get("webui_owner") in {None, owner}
    ]


def _goal_summary(goal: Dict[str, Any], owner: str) -> Dict[str, Any]:
    tasks = _goal_tasks(goal["id"], owner)
    completed = sum(item.get("status") == "COMPLETED" for item in tasks)
    result = {key: value for key, value in goal.items() if key != "webui_owner"}
    result.update({
        "task_count": len(tasks),
        "completed_task_count": completed,
        "progress": round((completed / len(tasks)) * 100) if tasks else 0,
    })
    return result


@router.get("/api/goals")
async def list_goals(request: Request, project_id: Optional[str] = None, status: Optional[str] = None):
    owner = _require_access(request)
    if project_id:
        _owned_project(project_id, owner)
    values = [
        _goal_summary(item, owner) for item in _WEBUI_STATE.get("goals", [])
        if item.get("webui_owner") in {None, owner}
        and (project_id is None or item.get("project_id") == project_id)
        and (status is None or item.get("status") == status)
    ]
    values.sort(key=lambda item: item.get("updated_at", 0), reverse=True)
    return {"goals": values}


def _new_goal(payload: Dict[str, Any], owner: str, project_id: Optional[str] = None) -> Dict[str, Any]:
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        raise HTTPException(status_code=400, detail="title is required")
    if project_id:
        _owned_project(project_id, owner)
    status = str(payload.get("status") or "PLANNED").upper()
    if status not in GOAL_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(GOAL_STATUSES)}")
    now = _now()
    goal = {
        "id": _phase3_id("goal"),
        "title": title.strip()[:240],
        "description": str(payload.get("description") or "")[:20000],
        "status": status,
        "priority": str(payload.get("priority") or "normal")[:40],
        "deadline": payload.get("deadline"),
        "project_id": project_id or payload.get("project_id"),
        "created_at": now,
        "updated_at": now,
        "webui_owner": owner,
    }
    _WEBUI_STATE.setdefault("goals", []).append(goal)
    _save_state()
    return goal


@router.post("/api/goals")
async def create_goal(request: Request):
    owner = _require_access(request)
    return {"ok": True, "goal": _goal_summary(_new_goal(await _body(request), owner), owner)}


@router.get("/api/goals/{goal_id}")
async def get_goal(request: Request, goal_id: str):
    owner = _require_access(request)
    goal = _phase3_item("goals", goal_id, owner)
    result = _goal_summary(goal, owner)
    result["tasks"] = [dict(item) for item in _goal_tasks(goal_id, owner)]
    return {"goal": result}


@router.patch("/api/goals/{goal_id}")
async def update_goal(request: Request, goal_id: str):
    owner = _require_access(request)
    goal = _phase3_item("goals", goal_id, owner)
    payload = await _body(request)
    for key in ("title", "description", "priority", "deadline"):
        if key in payload:
            if key == "title" and (not isinstance(payload[key], str) or not payload[key].strip()):
                return _json_error("title is required")
            goal[key] = payload[key].strip()[:240] if key == "title" else (payload[key][:20000] if key == "description" and isinstance(payload[key], str) else payload[key])
    if "status" in payload:
        status = str(payload["status"]).upper()
        if status not in GOAL_STATUSES:
            return _json_error(f"status must be one of {sorted(GOAL_STATUSES)}")
        goal["status"] = status
    goal["updated_at"] = _now()
    _save_state()
    return {"ok": True, "goal": _goal_summary(goal, owner)}


@router.delete("/api/goals/{goal_id}")
async def delete_goal(request: Request, goal_id: str):
    owner = _require_access(request)
    _phase3_item("goals", goal_id, owner)
    _WEBUI_STATE["goals"] = [item for item in _WEBUI_STATE.get("goals", []) if item.get("id") != goal_id]
    _WEBUI_STATE["tasks"] = [item for item in _WEBUI_STATE.get("tasks", []) if item.get("goal_id") != goal_id]
    _save_state()
    return {"ok": True, "deleted_id": goal_id}


@router.get("/api/projects/{project_id}/goals")
async def list_project_goals(request: Request, project_id: str):
    return await list_goals(request, project_id=project_id)


@router.post("/api/projects/{project_id}/goals")
async def create_project_goal(request: Request, project_id: str):
    owner = _require_access(request)
    return {"ok": True, "goal": _goal_summary(_new_goal(await _body(request), owner, project_id), owner)}


def _task_summary(task: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in task.items() if key != "webui_owner"}


def _owned_task(task_id: str, owner: str) -> Dict[str, Any]:
    return _phase3_item("tasks", task_id, owner)


def _dependency_status(task: Dict[str, Any], owner: str) -> Tuple[bool, bool]:
    dependencies = task.get("dependencies") or []
    records = []
    for dep_id in dependencies:
        dep = _owned_task(str(dep_id), owner)
        records.append(dep)
    return all(item.get("status") == "COMPLETED" for item in records), any(item.get("status") in {"FAILED", "CANCELLED", "BLOCKED"} for item in records)


def _refresh_task_readiness(owner: str) -> None:
    for _ in range(max(1, len(_WEBUI_STATE.get("tasks", [])))):
        changed = False
        for task in _WEBUI_STATE.get("tasks", []):
            if task.get("webui_owner") not in {None, owner} or task.get("status") in TASK_TERMINAL_STATUSES or task.get("status") in {"RUNNING", "WAITING_APPROVAL"}:
                continue
            ready, failed = _dependency_status(task, owner)
            next_status = "READY" if ready else ("BLOCKED" if failed else "PENDING")
            if task.get("status") != next_status:
                task["status"] = next_status
                task["updated_at"] = _now()
                changed = True
        if not changed:
            break


def _would_cycle(task_id: str, dependencies: List[str], owner: str) -> bool:
    graph = {
        item["id"]: list(item.get("dependencies") or [])
        for item in _WEBUI_STATE.get("tasks", [])
        if item.get("webui_owner") in {None, owner}
    }
    graph[task_id] = dependencies
    visiting = set()
    visited = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(dep) for dep in graph.get(node, [])):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return visit(task_id)


def _new_task(payload: Dict[str, Any], owner: str, project_id: Optional[str] = None, goal_id: Optional[str] = None) -> Dict[str, Any]:
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        raise HTTPException(status_code=400, detail="title is required")
    resolved_project = project_id or payload.get("project_id")
    resolved_goal = goal_id or payload.get("goal_id")
    if resolved_project:
        _owned_project(str(resolved_project), owner)
    if resolved_goal:
        goal = _phase3_item("goals", str(resolved_goal), owner)
        if resolved_project and goal.get("project_id") != resolved_project:
            raise HTTPException(status_code=400, detail="Goal does not belong to project")
        resolved_project = goal.get("project_id") or resolved_project
    dependencies = [str(value) for value in (payload.get("dependencies") or [])]
    if len(set(dependencies)) != len(dependencies):
        raise HTTPException(status_code=400, detail="dependencies must be unique")
    for dep_id in dependencies:
        dep = _owned_task(dep_id, owner)
        if resolved_project and dep.get("project_id") != resolved_project:
            raise HTTPException(status_code=400, detail="Dependencies must belong to the same project")
    task_id = _phase3_id("task")
    if _would_cycle(task_id, dependencies, owner):
        raise HTTPException(status_code=400, detail="Task dependencies cannot contain a cycle")
    requested = str(payload.get("status") or ("READY" if not dependencies else "PENDING")).upper()
    if requested not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(TASK_STATUSES)}")
    now = _now()
    task = {
        "id": task_id,
        "title": title.strip()[:240],
        "description": str(payload.get("description") or "")[:20000],
        "status": requested,
        "priority": str(payload.get("priority") or "normal")[:40],
        "goal_id": resolved_goal,
        "project_id": resolved_project,
        "dependencies": dependencies,
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "completed_at": None,
        "error": None,
        "result": None,
        "summary": None,
        "session_id": payload.get("session_id"),
        "webui_owner": owner,
    }
    _WEBUI_STATE.setdefault("tasks", []).append(task)
    _refresh_task_readiness(owner)
    _save_state()
    return task


@router.get("/api/tasks")
async def list_tasks(request: Request, project_id: Optional[str] = None, goal_id: Optional[str] = None, status: Optional[str] = None):
    owner = _require_access(request)
    if project_id:
        _owned_project(project_id, owner)
    if goal_id:
        _phase3_item("goals", goal_id, owner)
    _refresh_task_readiness(owner)
    values = [
        _task_summary(item) for item in _WEBUI_STATE.get("tasks", [])
        if item.get("webui_owner") in {None, owner}
        and (project_id is None or item.get("project_id") == project_id)
        and (goal_id is None or item.get("goal_id") == goal_id)
        and (status is None or item.get("status") == status)
    ]
    values.sort(key=lambda item: item.get("created_at", 0))
    return {"tasks": values}


@router.post("/api/tasks")
async def create_task(request: Request):
    owner = _require_access(request)
    return {"ok": True, "task": _task_summary(_new_task(await _body(request), owner))}


@router.get("/api/tasks/{task_id}")
async def get_task(request: Request, task_id: str):
    owner = _require_access(request)
    _refresh_task_readiness(owner)
    return {"task": _task_summary(_owned_task(task_id, owner))}


@router.patch("/api/tasks/{task_id}")
async def update_task(request: Request, task_id: str):
    owner = _require_access(request)
    task = _owned_task(task_id, owner)
    payload = await _body(request)
    for key in ("title", "description", "priority", "error", "result", "summary", "session_id"):
        if key in payload:
            if key == "title" and (not isinstance(payload[key], str) or not payload[key].strip()):
                return _json_error("title is required")
            task[key] = payload[key].strip()[:240] if key == "title" else payload[key]
    if "dependencies" in payload:
        dependencies = [str(value) for value in (payload.get("dependencies") or [])]
        if task_id in dependencies or len(set(dependencies)) != len(dependencies):
            return _json_error("Task dependencies must be unique and cannot include the task itself")
        for dep_id in dependencies:
            dep = _owned_task(dep_id, owner)
            if task.get("project_id") and dep.get("project_id") != task.get("project_id"):
                return _json_error("Dependencies must belong to the same project")
        if _would_cycle(task_id, dependencies, owner):
            return _json_error("Task dependencies cannot contain a cycle")
        task["dependencies"] = dependencies
    if "status" in payload:
        status = str(payload["status"]).upper()
        if status not in TASK_STATUSES:
            return _json_error(f"status must be one of {sorted(TASK_STATUSES)}")
        if status in {"READY", "RUNNING"}:
            ready, _ = _dependency_status(task, owner)
            if not ready:
                return JSONResponse({"error": "Task dependencies have not completed"}, status_code=409)
        task["status"] = status
        if status == "RUNNING" and not task.get("started_at"):
            task["started_at"] = _now()
        if status == "COMPLETED":
            task["completed_at"] = _now()
            if not task.get("started_at"):
                task["started_at"] = task["completed_at"]
        if status in {"FAILED", "CANCELLED"}:
            task["completed_at"] = _now()
    task["updated_at"] = _now()
    _refresh_task_readiness(owner)
    _save_state()
    return {"ok": True, "task": _task_summary(task)}


@router.delete("/api/tasks/{task_id}")
async def delete_task(request: Request, task_id: str):
    owner = _require_access(request)
    _owned_task(task_id, owner)
    _WEBUI_STATE["tasks"] = [item for item in _WEBUI_STATE.get("tasks", []) if item.get("id") != task_id]
    for task in _WEBUI_STATE.get("tasks", []):
        if task_id in (task.get("dependencies") or []):
            task["dependencies"] = [value for value in task["dependencies"] if value != task_id]
    _refresh_task_readiness(owner)
    _save_state()
    return {"ok": True, "deleted_id": task_id}


@router.post("/api/tasks/{task_id}/start")
async def start_task(request: Request, task_id: str):
    owner = _require_access(request)
    task = _owned_task(task_id, owner)
    ready, _ = _dependency_status(task, owner)
    if not ready:
        return JSONResponse({"error": "Task dependencies have not completed"}, status_code=409)
    task["status"] = "RUNNING"
    task["started_at"] = task.get("started_at") or _now()
    task["updated_at"] = _now()
    _save_state()
    return {"ok": True, "task": _task_summary(task)}


@router.get("/api/projects/{project_id}/tasks")
async def list_project_tasks(request: Request, project_id: str):
    return await list_tasks(request, project_id=project_id)


@router.post("/api/projects/{project_id}/tasks")
async def create_project_task(request: Request, project_id: str):
    owner = _require_access(request)
    return {"ok": True, "task": _task_summary(_new_task(await _body(request), owner, project_id))}

@router.get("/api/goals/{goal_id}/tasks")
async def list_goal_tasks(request: Request, goal_id: str):
    return await list_tasks(request, goal_id=goal_id)

@router.post("/api/goals/{goal_id}/tasks")
async def create_goal_task(request: Request, goal_id: str):
    owner = _require_access(request)
    return {"ok": True, "task": _task_summary(_new_task(await _body(request), owner, goal_id=goal_id))}


# ---------------------------------------------------------------------------
# Chat and file-backed SSE streams
# ---------------------------------------------------------------------------


def _queue_chat_stream(session_id: str, owner: str) -> str:
    sess = _owned_session(session_id, owner)
    existing_stream = sess.get("active_stream_id")
    existing_meta = _read_stream_meta(existing_stream) if existing_stream else None
    if existing_meta and existing_meta.get("status") in {"starting", "running"}:
        raise HTTPException(status_code=409, detail="A response is already running for this session")
    stream_id = secrets.token_urlsafe(24)
    sess["active_stream_id"] = stream_id
    meta = {
        "stream_id": stream_id,
        "session_id": session_id,
        "owner": owner,
        "status": "starting",
        "seq": 0,
        "cancel_requested": False,
        "created_at": _now(),
    }
    _write_stream_meta(stream_id, meta)
    _stream_events_path(stream_id).write_text("", encoding="utf-8")
    _touch(session_id)
    task = asyncio.create_task(_chat_worker(stream_id, owner), name=f"hermes-webui-stream-{stream_id}")
    _STREAM_TASKS[stream_id] = task
    logger.info("WebUI stream queued: %s", stream_id)
    return stream_id


def _stream_path(stream_id: str, suffix: str) -> Path:
    if not STREAM_ID_RE.fullmatch(stream_id):
        raise HTTPException(status_code=400, detail="Invalid stream id")
    # The persistent /data mount can be attached after module import, and a
    # user-managed volume can also lose empty subdirectories. Recreate the
    # stream directory at the point of use so chat startup is self-healing.
    _STREAMS_DIR.mkdir(parents=True, exist_ok=True)
    return _STREAMS_DIR / f"{stream_id}{suffix}"


def _stream_meta_path(stream_id: str) -> Path:
    return _stream_path(stream_id, ".json")


def _stream_events_path(stream_id: str) -> Path:
    return _stream_path(stream_id, ".events")


def _read_stream_meta(stream_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not stream_id:
        return None
    try:
        return json.loads(_stream_meta_path(stream_id).read_text(encoding="utf-8"))
    except (OSError, ValueError, HTTPException):
        return None


def _write_stream_meta(stream_id: str, meta: Dict[str, Any]) -> None:
    target = _stream_meta_path(stream_id)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, target)


def _stream_owner(request: Request) -> str:
    return _require_access(request)


async def _publish(stream_id: str, event: str, payload: Dict[str, Any], status: Optional[str] = None) -> None:
    lock = _STREAM_LOCKS.setdefault(stream_id, asyncio.Lock())
    async with lock:
        meta = _read_stream_meta(stream_id)
        if not meta:
            return
        meta["seq"] = int(meta.get("seq", 0)) + 1
        event_record = {"seq": meta["seq"], "event": event, "data": payload}
        with _stream_events_path(stream_id).open("a", encoding="utf-8") as output:
            output.write(json.dumps(event_record, ensure_ascii=False, separators=(",", ":")) + "\n")
            output.flush()
        # Replay is durable, but it must remain bounded for long-running
        # streams. Sequence numbers remain monotonic even when old records
        # are trimmed.
        try:
            events_file = _stream_events_path(stream_id)
            lines = events_file.read_text(encoding="utf-8").splitlines()
            if len(lines) > MAX_REPLAY_EVENTS:
                temporary = events_file.with_suffix(".tmp")
                temporary.write_text("\n".join(lines[-MAX_REPLAY_EVENTS:]) + "\n", encoding="utf-8")
                os.replace(temporary, events_file)
        except OSError:
            logger.warning("Unable to trim WebUI replay state: %s", stream_id)
        if status:
            meta["status"] = status
        _write_stream_meta(stream_id, meta)


def _cancel_requested(stream_id: str) -> bool:
    meta = _read_stream_meta(stream_id)
    return bool(meta and meta.get("cancel_requested"))


def _stream_id_from_last_event(request: Request) -> Optional[int]:
    """Read an SSE Last-Event-ID of the form stream_id:sequence."""
    value = request.headers.get("last-event-id", "")
    if ":" in value:
        value = value.rsplit(":", 1)[-1]
    try:
        return max(0, int(value)) if value else None
    except ValueError:
        return None


def _agent_messages(session_id: str) -> List[Dict[str, str]]:
    result = []
    for item in _messages(session_id):
        role = item.get("role")
        if role not in {"user", "assistant", "system"}:
            continue
        result.append({"role": role, "content": _message_text(item)})
    return result


async def _chat_worker(stream_id: str, owner: str) -> None:
    meta = _read_stream_meta(stream_id)
    if not meta:
        return
    session_id = meta["session_id"]
    sess = _owned_session(session_id, owner)
    assistant_text = []
    reasoning_text = []
    had_error = False
    cancelled = False
    try:
        logger.info("WebUI stream started: %s", stream_id)
        meta["status"] = "running"
        _write_stream_meta(stream_id, meta)
        # Use the existing Hermes runtime by default so WebUI chats get the
        # same tools, fallback model logic, and upstream behavior as /v1/chat.
        backend = os.getenv("HERMES_WEBUI_CHAT_BACKEND", "hermes").strip().lower()
        request_body = {
            "messages": _agent_messages(session_id),
            "model": sess.get("model") or _default_model(),
            "temperature": 0.7,
        }
        if sess.get("system"):
            request_body["system"] = str(sess["system"])
        headers = {}
        gateway_key = os.getenv("HERMES_WEBUI_GATEWAY_API_KEY", os.getenv("API_SERVER_KEY", "")).strip()
        if gateway_key:
            headers["Authorization"] = f"Bearer {gateway_key}"
        if backend == "gateway":
            gateway_base = os.getenv("HERMES_WEBUI_GATEWAY_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
            endpoint = f"{gateway_base}/chat/completions" if gateway_base.endswith("/v1") else f"{gateway_base}/v1/chat/completions"
            request_body["stream"] = True
        else:
            internal_port = int(os.getenv("HERMES_INTERNAL_PORT", "8642"))
            endpoint = f"http://127.0.0.1:{internal_port}/v1/chat"
        timeout = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", endpoint, json=request_body, headers=headers) as upstream:
                if upstream.status_code >= 400:
                    had_error = True
                    await _publish(stream_id, "error", {"error": "Hermes agent request failed", "session_id": session_id})
                else:
                    async for line in upstream.aiter_lines():
                        if _cancel_requested(stream_id):
                            cancelled = True
                            break
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            item = json.loads(raw)
                        except ValueError:
                            continue
                        if backend == "gateway":
                            choices = item.get("choices") or []
                            delta = choices[0].get("delta", {}) if choices else {}
                            text = delta.get("content")
                            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                            if text:
                                assistant_text.append(str(text))
                                await _publish(stream_id, "token", {"text": str(text)})
                            if reasoning:
                                reasoning_text.append(str(reasoning))
                                await _publish(stream_id, "reasoning", {"text": str(reasoning)})
                            if delta.get("tool_calls"):
                                for tool_call in delta["tool_calls"]:
                                    await _publish(stream_id, "tool_call", tool_call)
                            continue
                        kind = item.get("type")
                        if kind in {"text", "token"}:
                            text = str(item.get("content", item.get("text", "")))
                            if text:
                                assistant_text.append(text)
                                await _publish(stream_id, "token", {"text": text})
                        elif kind in {"thinking", "reasoning"}:
                            text = str(item.get("content", item.get("text", "")))
                            if text:
                                reasoning_text.append(text)
                                await _publish(stream_id, "reasoning", {"text": text})
                        elif kind in {"tool", "tool_call"}:
                            await _publish(stream_id, "tool_call", {k: v for k, v in item.items() if k != "type"})
                        elif kind in {"tool_complete", "tool_result"}:
                            await _publish(stream_id, "tool_result", {k: v for k, v in item.items() if k != "type"})
                        elif kind == "error":
                            had_error = True
                            await _publish(stream_id, "error", {"error": str(item.get("error", "Agent error")), "session_id": session_id})
                            break
    except asyncio.CancelledError:
        cancelled = True
    except Exception:
        had_error = True
        logger.exception("WebUI stream failed: %s", stream_id)
        await _publish(stream_id, "error", {"error": "Hermes agent is temporarily unavailable", "session_id": session_id})
    finally:
        if assistant_text or reasoning_text:
            message: Dict[str, Any] = {
                "id": f"msg_{secrets.token_hex(12)}",
                "role": "assistant",
                "content": "".join(assistant_text),
                "timestamp": _now(),
                "model": sess.get("model") or _default_model(),
            }
            if reasoning_text:
                message["reasoning"] = [{"text": "".join(reasoning_text)}]
            _messages(session_id).append(message)
        sess["active_stream_id"] = None
        _touch(session_id)
        if cancelled or _cancel_requested(stream_id):
            await _publish(stream_id, "cancel", {"session_id": session_id})
        elif not had_error:
            detail = _detail(session_id, include_messages=False)
            await _publish(stream_id, "done", {"session_id": session_id, "session": detail, "usage": _session_usage_payload(sess)})
        terminal_status = "cancelled" if (cancelled or _cancel_requested(stream_id)) else ("error" if had_error else "completed")
        if not had_error and not cancelled:
            await _publish(stream_id, "stream_end", {"session_id": session_id}, terminal_status)
        elif cancelled:
            await _publish(stream_id, "stream_end", {"session_id": session_id}, terminal_status)
        else:
            await _publish(stream_id, "stream_end", {"session_id": session_id}, terminal_status)
        meta = _read_stream_meta(stream_id) or meta
        meta["status"] = terminal_status
        meta["finished_at"] = _now()
        _write_stream_meta(stream_id, meta)
        _STREAM_TASKS.pop(stream_id, None)
        _STREAM_LOCKS.pop(stream_id, None)
        logger.info("WebUI stream finished: %s (%s)", stream_id, meta.get("status"))


def _session_usage_payload(sess: Dict[str, Any]) -> Dict[str, Any]:
    return {"input_tokens": sess.get("input_tokens", 0), "output_tokens": sess.get("output_tokens", 0), "total_tokens": sess.get("input_tokens", 0) + sess.get("output_tokens", 0)}


@router.post("/api/chat/start")
async def start_webui_chat(request: Request):
    owner = _stream_owner(request)
    payload = await _body(request)
    message = _chat_text(payload)
    if not message.strip():
        return _json_error("message is required")
    session_id = str(payload.get("session_id") or payload.get("conversation_id") or "")
    if not session_id:
        session_id = _new_session(payload, owner)
    sess = _owned_session(session_id, owner)
    existing_stream = sess.get("active_stream_id")
    existing_meta = _read_stream_meta(existing_stream) if existing_stream else None
    if existing_meta and existing_meta.get("status") in {"starting", "running"}:
        return _json_error("A response is already running for this session", 409)
    if payload.get("workspace") is not None:
        sess["workspace"] = payload.get("workspace")
    for key in ("model", "model_provider", "profile"):
        if payload.get(key) is not None:
            sess[key] = payload[key]
    attachments = payload.get("attachments") or []
    text = message.strip()
    if attachments:
        names = [str(item.get("filename") or item.get("path") or "attachment") for item in attachments if isinstance(item, dict)]
        if names:
            text += "\n\n[Attached files: " + ", ".join(names) + "]"
    _messages(session_id).append({"id": f"msg_{secrets.token_hex(12)}", "role": "user", "content": text, "timestamp": _now(), "attachments": attachments})
    stream_id = _queue_chat_stream(session_id, owner)
    return {"stream_id": stream_id, "session_id": session_id}


@router.get("/api/chat/stream")
async def stream_webui_chat(request: Request, stream_id: str, replay: int = 0, after_seq: Optional[int] = None):
    owner = _stream_owner(request)
    meta = _read_stream_meta(stream_id)
    if not meta or meta.get("owner") != owner:
        raise HTTPException(status_code=404, detail="Stream not found")
    requested_seq = after_seq if after_seq is not None else _stream_id_from_last_event(request)
    starting_seq = max(0, int(requested_seq or 0))

    async def event_generator():
        last_seq = starting_seq
        heartbeat_at = _now()
        while True:
            if await request.is_disconnected():
                return
            records: List[Dict[str, Any]] = []
            try:
                with _stream_events_path(stream_id).open("r", encoding="utf-8") as source:
                    for line in source:
                        try:
                            record = json.loads(line)
                            if int(record.get("seq", 0)) > last_seq:
                                records.append(record)
                        except ValueError:
                            continue
            except OSError:
                pass
            for record in records:
                last_seq = int(record["seq"])
                yield f"id: {stream_id}:{last_seq}\nevent: {record['event']}\ndata: {json.dumps(record['data'], ensure_ascii=False, separators=(',', ':'))}\n\n"
            latest = _read_stream_meta(stream_id) or {}
            latest_seq = int(latest.get("seq", 0))
            if latest.get("status") in {"done", "completed", "error", "cancelled"} and last_seq >= latest_seq:
                return
            if _now() - heartbeat_at >= 15:
                heartbeat_at = _now()
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.api_route("/api/chat/cancel", methods=["GET", "POST"])
async def cancel_webui_chat(request: Request, stream_id: str):
    owner = _stream_owner(request)
    meta = _read_stream_meta(stream_id)
    if not meta or meta.get("owner") != owner:
        raise HTTPException(status_code=404, detail="Stream not found")
    meta["cancel_requested"] = True
    _write_stream_meta(stream_id, meta)
    task = _STREAM_TASKS.get(stream_id)
    if task and not task.done():
        task.cancel()
    logger.info("WebUI stream cancellation requested: %s", stream_id)
    return {"ok": True, "cancelled": True}


@router.get("/api/chat/stream/status")
async def chat_stream_status(request: Request, stream_id: str):
    owner = _stream_owner(request)
    meta = _read_stream_meta(stream_id)
    if not meta or meta.get("owner") != owner:
        raise HTTPException(status_code=404, detail="Stream not found")
    active = meta.get("status") in {"starting", "running"}
    return {"active": active, "status": meta.get("status"), "session_id": meta.get("session_id"), "stream_id": stream_id, "active_stream_id": stream_id if active else None, "is_streaming": active, "replay_available": int(meta.get("seq", 0)) > 0, "finished_at": meta.get("finished_at")}


@router.post("/api/chat/steer")
async def steer_webui_chat(request: Request):
    owner = _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    sess = _owned_session(sid, owner)
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return _json_error("text is required")
    stream_id = sess.get("active_stream_id")
    meta = _read_stream_meta(stream_id)
    if not meta or meta.get("status") not in {"starting", "running"}:
        return {"accepted": False, "fallback": "No active stream"}
    return JSONResponse(
        {
            "accepted": False,
            "error": {
                "code": "steering_unsupported",
                "message": "The configured Hermes runtime does not support mid-stream steering",
            },
        },
        status_code=409,
    )


# ---------------------------------------------------------------------------
# Workspace, file, and upload APIs
# ---------------------------------------------------------------------------


def _workspace_base() -> Path:
    value = os.getenv("HERMES_WEBUI_WORKSPACE_BASE")
    return Path(value).expanduser().resolve() if value else (Path("/data").resolve() if Path("/data").exists() else Path.cwd().resolve())


def _configured_roots() -> List[Path]:
    configured = os.getenv("HERMES_WEBUI_WORKSPACES", "")
    values = [item for item in configured.split(os.pathsep) if item.strip()]
    if not values:
        values = ["/data/obsidian/vault", "/data/hermes"] if Path("/data").exists() else [str(Path.cwd())]
    roots: List[Path] = []
    for value in values + [str(item.get("path")) for item in _WEBUI_STATE.get("workspaces", []) if item.get("path")]:
        try:
            candidate = Path(value).expanduser().resolve()
            if _within(candidate, _workspace_base()) and candidate not in roots:
                roots.append(candidate)
        except (OSError, RuntimeError):
            continue
    return roots or [_workspace_base()]


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_sensitive_name(name: str) -> bool:
    lowered = name.lower()
    return lowered in _SENSITIVE_NAMES or lowered.startswith(".env.") or lowered.endswith((".pem", ".key", ".p12", ".pfx"))


def _safe_upload_name(raw_name: Any) -> str:
    filename = Path(str(raw_name or "upload.bin")).name.replace("\x00", "")
    if (
        not filename
        or filename in {".", ".."}
        or filename.startswith(".")
        or _is_sensitive_name(filename)
        or Path(filename).suffix.lower() in _EXECUTABLE_SUFFIXES
    ):
        raise HTTPException(status_code=415, detail="This filename is not allowed")
    return filename


def _safe_upload_target(root: Path, filename: str) -> Path:
    destination = root / "uploads"
    destination.mkdir(parents=True, exist_ok=True)
    resolved_destination = destination.resolve()
    if destination.is_symlink() or not _within(resolved_destination, root):
        raise HTTPException(status_code=403, detail="Upload directory is outside the workspace")
    target = destination / filename
    if not _within(target.resolve(), root):
        raise HTTPException(status_code=403, detail="Upload path is outside the workspace")
    return target


def _check_upload_length(request: Request) -> None:
    raw_length = request.headers.get("content-length")
    try:
        if raw_length and int(raw_length) > MAX_UPLOAD_BYTES + 1024 * 1024:
            raise HTTPException(status_code=413, detail="Upload exceeds the configured size limit")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Content-Length header")


def _legacy_upload_record(
    file_name: str,
    content: str,
    file_type: str,
    file_size: int,
) -> Dict[str, Any]:
    """Keep the pre-WebUI /api/upload response and /api/files lookup working."""
    file_id = f"file_{secrets.token_hex(8)}"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {
        "id": file_id,
        "uuid": file_id,
        "file_uuid": file_id,
        "file_name": file_name,
        "filename": file_name,
        "file_size": file_size,
        "file_type": file_type,
        "extracted_content": content,
        "content": content,
        "created_at": now,
        "updated_at": now,
        "status": "ready",
    }
    try:
        from Backend.gateway import claude_rest_api as legacy
        legacy._UPLOADED_FILES[file_id] = record
    except Exception:
        # The standalone WebUI deployment does not necessarily ship the
        # optional Claude bridge; the durable workspace copy still succeeds.
        pass
    return record


def _workspace_path(session_id: Optional[str], raw_path: Optional[str] = None, must_exist: bool = False) -> Path:
    roots = _configured_roots()
    session_root = None
    if session_id:
        sess = _session(session_id)
        raw_workspace = sess.get("workspace")
        if raw_workspace:
            candidate = Path(str(raw_workspace)).expanduser().resolve()
            if any(_within(candidate, root) for root in roots):
                session_root = candidate
    root = session_root or roots[0]
    raw = str(raw_path or "").replace("\\", "/")
    parts = Path(raw).parts
    if ".." in parts:
        raise HTTPException(status_code=400, detail="Path traversal is not allowed")
    if Path(raw).is_absolute():
        raise HTTPException(status_code=400, detail="Absolute paths are not allowed")
    if any(_is_sensitive_name(part) or part.startswith(".") for part in parts if part not in {".", "/"}):
        raise HTTPException(status_code=403, detail="Access to private files is not allowed")
    candidate = root / raw
    candidate = candidate.resolve()
    if not any(_within(candidate, allowed) for allowed in roots):
        raise HTTPException(status_code=403, detail="Path is outside the workspace")
    if must_exist and not candidate.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if candidate.is_file() and _is_sensitive_name(candidate.name):
        raise HTTPException(status_code=403, detail="Access to private files is not allowed")
    return candidate


def _workspace_entries() -> List[Dict[str, Any]]:
    result = []
    for root in _configured_roots():
        result.append({"path": str(root), "name": root.name or str(root), "exists": root.exists()})
    return result


@router.get("/api/workspaces")
async def list_workspaces(request: Request):
    _require_access(request)
    entries = _workspace_entries()
    return {"workspaces": entries, "roots": entries, "last": entries[0]["path"] if entries else None}


@router.get("/api/workspaces/suggest")
async def suggest_workspaces(request: Request, prefix: str = ""):
    _require_access(request)
    needle = prefix.lower()
    suggestions = [item["path"] for item in _workspace_entries() if not needle or needle in item["path"].lower() or needle in item["name"].lower()]
    return {"suggestions": suggestions, "prefix": prefix}


@router.post("/api/workspaces/add")
async def add_workspace(request: Request):
    _require_access(request)
    payload = await _body(request)
    raw = payload.get("path")
    if not isinstance(raw, str) or not raw.strip():
        return _json_error("path is required")
    candidate = Path(raw).expanduser().resolve()
    if not _within(candidate, _workspace_base()):
        return _json_error("Workspace must be inside the configured workspace base", 403)
    if payload.get("create"):
        candidate.mkdir(parents=True, exist_ok=True)
    if not candidate.exists() or not candidate.is_dir():
        return _json_error("Workspace directory does not exist", 404)
    current = [item for item in _WEBUI_STATE["workspaces"] if item.get("path") != str(candidate)]
    current.append({"path": str(candidate), "name": payload.get("name") or candidate.name, "exists": True})
    _WEBUI_STATE["workspaces"] = current
    _save_state()
    return {"ok": True, "workspaces": _workspace_entries()}


@router.post("/api/workspaces/remove")
async def remove_workspace(request: Request):
    _require_access(request)
    payload = await _body(request)
    path = str(payload.get("path", ""))
    _WEBUI_STATE["workspaces"] = [item for item in _WEBUI_STATE["workspaces"] if item.get("path") != path]
    _save_state()
    return {"ok": True, "workspaces": _workspace_entries()}


@router.post("/api/workspaces/rename")
async def rename_workspace(request: Request):
    _require_access(request)
    payload = await _body(request)
    path = str(payload.get("path", ""))
    for item in _WEBUI_STATE["workspaces"]:
        if item.get("path") == path:
            item["name"] = str(payload.get("name") or item.get("name") or Path(path).name)[:120]
    _save_state()
    return {"ok": True, "workspaces": _workspace_entries()}


@router.post("/api/workspaces/reorder")
async def reorder_workspaces(request: Request):
    _require_access(request)
    payload = await _body(request)
    order = payload.get("paths") or []
    known = {item.get("path"): item for item in _WEBUI_STATE["workspaces"]}
    _WEBUI_STATE["workspaces"] = [known[path] for path in order if path in known]
    _save_state()
    return {"ok": True, "workspaces": _workspace_entries()}


@router.get("/api/list")
async def list_workspace_directory(request: Request, session_id: str, path: Optional[str] = None):
    owner = _require_access(request)
    _owned_session(session_id, owner)
    directory = _workspace_path(session_id, path, must_exist=True)
    if not directory.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")
    entries = []
    for child in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        try:
            resolved_child = child.resolve()
        except OSError:
            continue
        if child.name.startswith(".") or _is_sensitive_name(child.name) or not any(_within(resolved_child, root) for root in _configured_roots()):
            continue
        entries.append({"name": child.name, "path": str(child.relative_to(_workspace_path(session_id))), "type": "directory" if child.is_dir() else "file", "size": child.stat().st_size if child.is_file() else None, "modified_at": child.stat().st_mtime})
    return {"entries": entries, "path": str(directory)}


@router.get("/api/file")
async def read_workspace_file(request: Request, session_id: str, path: str):
    owner = _require_access(request)
    _owned_session(session_id, owner)
    target = _workspace_path(session_id, path, must_exist=True)
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")
    if target.stat().st_size > MAX_PREVIEW_BYTES:
        return {"path": str(target), "content": "", "encoding": "utf-8", "language": target.suffix.lstrip("."), "size": target.stat().st_size, "error": "File is too large for inline preview"}
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"path": str(target), "content": base64.b64encode(target.read_bytes()).decode(), "encoding": "base64", "language": target.suffix.lstrip("."), "size": target.stat().st_size}
    return {"path": str(target), "content": content, "encoding": "utf-8", "language": target.suffix.lstrip("."), "size": target.stat().st_size}


@router.get("/api/file/raw")
async def raw_workspace_file(request: Request, session_id: str, path: str):
    owner = _require_access(request)
    _owned_session(session_id, owner)
    target = _workspace_path(session_id, path, must_exist=True)
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")
    return FileResponse(target, media_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream")


@router.post("/api/upload")
async def upload_workspace_file(request: Request):
    owner = _require_access(request)
    _check_upload_length(request)
    if not request.headers.get("content-type", "").startswith("multipart/"):
        payload = await _body(request)
        content = str(payload.get("content") or payload.get("extracted_content") or "")
        file_name = _safe_upload_name(payload.get("file_name") or payload.get("filename") or "document.txt")
        file_type = str(payload.get("file_type") or "text/plain")
        project_id = payload.get("project_id")
        if project_id:
            _owned_project(str(project_id), owner)
        record = _legacy_upload_record(file_name, content, file_type, len(content.encode("utf-8")))
        _WEBUI_STATE.setdefault("files", []).append({
            "id": record["id"],
            "filename": file_name,
            "file_type": file_type,
            "size": record["file_size"],
            "created_at": _now(),
            "project_id": str(project_id) if project_id else None,
            "session_id": payload.get("session_id"),
            "webui_owner": owner,
        })
        _save_state()
        return record
    form = await request.form()
    uploaded = form.get("file")
    if not isinstance(uploaded, UploadFile) and not hasattr(uploaded, "filename"):
        return _json_error("file is required")
    session_id = str(form.get("session_id") or "")
    if not session_id:
        session_id = _new_session({}, owner)
    _owned_session(session_id, owner)
    session = _session(session_id)
    root = _workspace_path(session_id)
    filename = _safe_upload_name(uploaded.filename)
    target = _safe_upload_target(root, filename)
    counter = 1
    while target.exists():
        target = _safe_upload_target(root, f"{Path(filename).stem}-{counter}{Path(filename).suffix}")
        counter += 1
    total = 0
    try:
        with target.open("wb") as output:
            while True:
                chunk = await uploaded.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    target.unlink(missing_ok=True)
                    logger.warning("WebUI upload rejected for size: %s", target.name)
                    return _json_error("Upload exceeds the configured size limit", 413)
                output.write(chunk)
    finally:
        await uploaded.close()
    relative = str(target.relative_to(root))
    mime = getattr(uploaded, "content_type", None) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    record = _legacy_upload_record(target.name, "", mime, total)
    _WEBUI_STATE.setdefault("files", []).append({
        "id": record["id"],
        "filename": target.name,
        "path": relative,
        "file_type": mime,
        "size": total,
        "created_at": _now(),
        "project_id": session.get("project_id"),
        "session_id": session_id,
        "webui_owner": owner,
    })
    _save_state()
    return {**record, "filename": target.name, "path": relative, "mime": mime, "size": total, "is_image": mime.startswith("image/")}


@router.post("/api/upload/extract")
async def extract_uploaded_file(request: Request):
    owner = _require_access(request)
    _check_upload_length(request)
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/"):
        form = await request.form()
        uploaded = form.get("file")
        if not isinstance(uploaded, UploadFile) and not hasattr(uploaded, "filename"):
            return _json_error("file is required")
        session_id = str(form.get("session_id") or "")
        if not session_id:
            session_id = _new_session({}, owner)
        _owned_session(session_id, owner)
        root = _workspace_path(session_id)
        filename = _safe_upload_name(uploaded.filename)
        target = _safe_upload_target(root, filename)
        counter = 1
        while target.exists():
            target = _safe_upload_target(root, f"{Path(filename).stem}-{counter}{Path(filename).suffix}")
            counter += 1
        total = 0
        with target.open("wb") as output:
            while True:
                chunk = await uploaded.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    target.unlink(missing_ok=True)
                    return _json_error("Upload exceeds the configured size limit", 413)
                output.write(chunk)
        await uploaded.close()
        result = {"path": str(target.relative_to(root))}
    else:
        payload = await _body(request)
        session_id = str(payload.get("session_id", ""))
        _owned_session(session_id, owner)
        target = _workspace_path(session_id, str(payload.get("path", "")), must_exist=True)
        result = {"path": str(target)}
    if target.stat().st_size > MAX_PREVIEW_BYTES:
        return _json_error("File is too large for extraction", 413)
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return _json_error("Only UTF-8 text files can be extracted", 415)
    return {"ok": True, "path": result.get("path", str(target)), "text": text}


# ---------------------------------------------------------------------------
# Models, providers, settings, reasoning, and profiles
# ---------------------------------------------------------------------------


def _default_model() -> str:
    return str(_WEBUI_STATE.get("default_model") or os.getenv("HERMES_DEFAULT_MODEL") or os.getenv("HERMES_MODEL") or "auto/best-coding")


def _model_ids() -> List[str]:
    configured = os.getenv("HERMES_AVAILABLE_MODELS", "")
    values = [_default_model()] + [item.strip() for item in configured.split(",") if item.strip()]
    return list(dict.fromkeys(item for item in values if item))


def _model_rows() -> List[Dict[str, Any]]:
    return [{"id": item, "name": item, "label": item, "provider": "omniroute", "provider_id": "omniroute"} for item in _model_ids()]


def _provider_rows() -> List[Dict[str, Any]]:
    base = os.getenv("OMNIROUTE_BASE_URL", os.getenv("UPSTREAM_OMNIROUTE_URL", ""))
    parsed = urlsplit(base)
    safe_base = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")) if parsed.scheme else ""
    models = _model_ids()
    return [{"id": "omniroute", "name": "OmniRoute", "display_name": "OmniRoute", "configured": bool(base), "has_key": bool(os.getenv("OMNIROUTE_API_KEY") or os.getenv("UPSTREAM_API_KEY") or os.getenv("API_SERVER_KEY")), "configurable": False, "is_self_hosted": False, "base_url": safe_base, "models": [{"id": item, "label": item} for item in models], "models_total": len(models)}]


@router.get("/api/commands")
async def webui_commands(request: Request):
    _require_access(request)
    return {"commands": []}


@router.get("/api/personalities")
async def webui_personalities(request: Request):
    _require_access(request)
    return {"personalities": []}


@router.post("/api/personality/set")
async def set_webui_personality(request: Request):
    owner = _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    _owned_session(sid, owner)
    return {"ok": True, "personality": payload.get("name")}


@router.get("/api/media")
async def media_workspace_file(request: Request, session_id: str, path: str):
    return await raw_workspace_file(request, session_id, path)


@router.get("/api/models")
async def webui_models(request: Request):
    _require_access(request)
    rows = _model_rows()
    # /api/models existed in the Claude-compatible router before WebUI was
    # added. Preserve its collection fields while exposing the WebUI view.
    try:
        from gateway.claude_rest_api import MODELS_CATALOG
        legacy_models = list(MODELS_CATALOG)
    except Exception:
        legacy_models = []
    return {
        "models": rows,
        "data": legacy_models,
        "has_more": False,
        "first_id": (legacy_models[0].get("model") if legacy_models else None),
        "last_id": (legacy_models[-1].get("model") if legacy_models else None),
        "providers": _provider_rows(),
        "groups": [],
        "active_provider": "omniroute",
        "default_model": _default_model(),
    }


@router.get("/api/models/live")
async def webui_models_live(request: Request):
    _require_access(request)
    models = _model_rows()
    return {"provider": "omniroute", "models": models, "count": len(models)}


@router.get("/api/providers")
async def webui_providers(request: Request):
    _require_access(request)
    return {"providers": _provider_rows(), "active_provider": "omniroute"}


@router.api_route("/api/settings", methods=["GET", "POST"])
async def webui_settings(request: Request):
    _require_access(request)
    if request.method == "POST":
        payload = await _body(request)
        for key in ("show_cli_sessions", "show_claude_code_sessions"):
            if key in payload:
                _WEBUI_STATE["settings"][key] = bool(payload[key])
        _save_state()
    return {"webui_version": "adapter-1", "bot_name": "Hermes", "theme": "system", **_WEBUI_STATE["settings"], "default_model": _default_model(), "default_model_provider": "omniroute"}


@router.post("/api/default-model")
async def set_default_model(request: Request):
    _require_access(request)
    payload = await _body(request)
    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        return _json_error("model is required")
    _WEBUI_STATE["default_model"] = model.strip()[:200]
    _save_state()
    return {"ok": True, "model": _default_model(), "provider": payload.get("provider") or "omniroute"}


@router.api_route("/api/reasoning", methods=["GET", "POST"])
async def webui_reasoning(request: Request, model: Optional[str] = None, provider: Optional[str] = None):
    _require_access(request)
    if request.method == "POST":
        payload = await _body(request)
        if payload.get("effort") in {"low", "medium", "high", "max"}:
            _WEBUI_STATE["reasoning_effort"] = payload["effort"]
        if payload.get("display") in {"off", "auto", "on"}:
            _WEBUI_STATE["reasoning_display"] = payload["display"]
        _save_state()
    effort = _WEBUI_STATE.get("reasoning_effort", "medium")
    display = _WEBUI_STATE.get("reasoning_display", "off")
    return {"effort": effort, "reasoning_effort": effort, "supported_efforts": ["low", "medium", "high", "max"], "supports_reasoning_effort": True, "display": display, "reasoning_display": display}


@router.get("/api/profiles")
async def webui_profiles(request: Request):
    _require_access(request)
    profiles = list(_WEBUI_STATE.get("profiles", []))
    if not profiles:
        profiles = [{"name": "default", "display_name": "Default", "path": str(_DATA_ROOT), "is_default": True, "is_active": True, "gateway_running": True, "model": _default_model(), "provider": "omniroute", "has_env": bool(os.getenv("OMNIROUTE_API_KEY")), "skill_count": 0}]
    return {"profiles": profiles, "active": "default", "single_profile_mode": len(profiles) == 1}


@router.post("/api/profile/switch")
async def switch_profile(request: Request):
    _require_access(request)
    payload = await _body(request)
    name = str(payload.get("name", "default"))
    profiles = await webui_profiles(request)
    if not any(item.get("name") == name for item in profiles["profiles"]):
        return _json_error("Profile not found", 404)
    return {"profiles": profiles["profiles"], "active": name, "default_model": _default_model(), "default_model_provider": "omniroute", "default_workspace": None}


@router.post("/api/profile/create")
async def create_profile(request: Request):
    _require_access(request)
    payload = await _body(request)
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        return _json_error("name is required")
    profile = {"name": name.strip()[:80], "display_name": name.strip()[:80], "path": str(_DATA_ROOT / "profiles" / name.strip()[:80]), "is_default": False, "is_active": False, "gateway_running": True, "model": payload.get("default_model") or _default_model(), "provider": payload.get("model_provider") or "omniroute", "has_env": False, "skill_count": 0}
    _WEBUI_STATE.setdefault("profiles", []).append(profile)
    _save_state()
    return {"ok": True, "profile": profile}
