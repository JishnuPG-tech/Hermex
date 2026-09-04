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

MAX_UPLOAD_BYTES = int(os.getenv("HERMES_WEBUI_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
MAX_PREVIEW_BYTES = 2 * 1024 * 1024
SESSION_TOKEN_MAX_AGE = 60 * 60 * 24 * 30
STREAM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

_DEFAULT_STATE: Dict[str, Any] = {
    "projects": [],
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
                state = dict(_DEFAULT_STATE)
                state.update(raw)
                return state
    except (OSError, ValueError, TypeError):
        pass
    return dict(_DEFAULT_STATE)


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


def _auth_enabled() -> bool:
    return bool(_password())


def _make_session_token() -> str:
    issued = str(int(_now()))
    nonce = secrets.token_urlsafe(24)
    payload = f"{issued}.{nonce}"
    signature = hmac.new(_password().encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _valid_session_token(token: Optional[str]) -> bool:
    if not _auth_enabled() or not token:
        return not _auth_enabled()
    parts = token.split(".")
    if len(parts) != 3:
        return False
    issued, nonce, signature = parts
    try:
        if _now() - int(issued) > SESSION_TOKEN_MAX_AGE or int(issued) > _now() + 60:
            return False
    except ValueError:
        return False
    expected = hmac.new(_password().encode(), f"{issued}.{nonce}".encode(), hashlib.sha256).hexdigest()
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
    token = _request_token(request)
    if not _valid_session_token(token):
        raise HTTPException(status_code=401, detail="WebUI authentication required")
    if not _auth_enabled():
        return "anonymous"
    return hashlib.sha256((token or "").encode()).hexdigest()[:24]


@router.get("/api/auth/status")
async def auth_status(request: Request):
    enabled = _auth_enabled()
    return {
        "auth_enabled": enabled,
        "password_auth_enabled": enabled,
        "logged_in": (not enabled) or _valid_session_token(_request_token(request)),
    }


@router.post("/api/auth/login")
async def auth_login(request: Request, response: Response):
    if not _auth_enabled():
        return {"ok": True, "authenticated": True}
    payload = await _body(request)
    supplied = payload.get("password")
    if not isinstance(supplied, str) or not hmac.compare_digest(supplied, _password()):
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


def _new_session(payload: Optional[Dict[str, Any]] = None) -> str:
    payload = payload or {}
    raw_id = payload.get("session_id") or payload.get("id")
    session_id = str(raw_id) if raw_id else f"sess_{secrets.token_hex(12)}"
    if not SESSION_ID_RE.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="Invalid session id")
    if session_id in session_store._SESSIONS:
        return session_id
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
        "pinned": False,
        "archived": False,
    }
    session_store._MESSAGES[session_id] = []
    session_store._CONV_TO_SESSION[session_id] = session_id
    session_store._save_data()
    return session_id


@router.get("/api/sessions")
async def list_webui_sessions(request: Request, include_archived: int = 0, archived_limit: Optional[int] = None):
    _require_access(request)
    values = []
    for sid in list(session_store._SESSIONS):
        summary = _summary(sid)
        if summary["archived"] and not include_archived:
            continue
        values.append(summary)
    values.sort(key=lambda item: (item.get("pinned", False), item.get("updated_at", 0)), reverse=True)
    if include_archived and archived_limit:
        values = values[: max(1, min(archived_limit, 200))]
    return {
        "sessions": values,
        "cli_count": 0,
        "archived_count": sum(bool(s.get("archived", False)) for s in map(_summary, session_store._SESSIONS)),
        "server_time": _now(),
        "server_tz": "UTC",
    }


@router.get("/api/sessions/search")
async def search_webui_sessions(request: Request, q: str = "", content: int = 0, depth: int = 1):
    _require_access(request)
    needle = q.strip().lower()
    found = []
    for sid in session_store._SESSIONS:
        summary = _summary(sid)
        haystack = summary["title"].lower()
        if content:
            haystack += " " + " ".join(_message_text(m).lower() for m in _messages(sid))
        if not needle or needle in haystack:
            summary["match_type"] = "content" if content and needle in haystack else "title"
            found.append(summary)
    return {"sessions": found, "query": q, "count": len(found)}


@router.get("/api/session")
async def get_webui_session(request: Request, session_id: str, messages: int = 1, msg_limit: Optional[int] = 50, msg_before: Optional[int] = None, expand_renderable: int = 0):
    _require_access(request)
    return {"session": _detail(session_id, messages != 0, msg_limit, msg_before)}


@router.get("/api/session/status")
async def session_status(request: Request, session_id: str):
    _require_access(request)
    sess = _session(session_id)
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
    _require_access(request)
    sess = _session(session_id)
    return {
        "input_tokens": sess.get("input_tokens", 0),
        "output_tokens": sess.get("output_tokens", 0),
        "total_tokens": sess.get("input_tokens", 0) + sess.get("output_tokens", 0),
        "estimated_cost": sess.get("estimated_cost", 0.0),
        "model": sess.get("model") or _default_model(),
    }


@router.post("/api/session/new")
async def create_webui_session(request: Request):
    _require_access(request)
    payload = await _body(request)
    session_id = _new_session(payload)
    return {"ok": True, "session": _summary(session_id)}


@router.post("/api/session/rename")
async def rename_webui_session(request: Request):
    _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    sess = _session(sid)
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        return _json_error("title is required")
    sess["title"] = title.strip()[:200]
    _touch(sid)
    return {"ok": True, "session": _summary(sid)}


@router.post("/api/session/delete")
async def delete_webui_session(request: Request):
    _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    _session(sid)
    session_store._SESSIONS.pop(sid, None)
    session_store._MESSAGES.pop(sid, None)
    session_store._save_data()
    return {"ok": True, "session": None}


@router.post("/api/session/clear")
async def clear_webui_session(request: Request):
    _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    _session(sid)
    session_store._MESSAGES[sid] = []
    _touch(sid)
    return {"ok": True, "session": _detail(sid)}


@router.post("/api/session/pin")
async def pin_webui_session(request: Request):
    _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    sess = _session(sid)
    sess["pinned"] = bool(payload.get("pinned", True))
    _touch(sid)
    return {"ok": True, "session": _summary(sid)}


@router.post("/api/session/archive")
async def archive_webui_session(request: Request):
    _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    sess = _session(sid)
    sess["archived"] = bool(payload.get("archived", True))
    _touch(sid)
    return {"ok": True, "session": _summary(sid)}


@router.post("/api/session/move")
async def move_webui_session(request: Request):
    _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    sess = _session(sid)
    project_id = payload.get("project_id")
    if project_id is not None and not any(p.get("project_id") == project_id for p in _WEBUI_STATE["projects"]):
        return _json_error("Project not found", 404)
    sess["project_id"] = project_id
    _touch(sid)
    return {"ok": True, "session": _summary(sid)}


@router.post("/api/session/branch")
async def branch_webui_session(request: Request):
    _require_access(request)
    payload = await _body(request)
    parent_id = str(payload.get("session_id", ""))
    parent = _session(parent_id)
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
    })
    session_store._MESSAGES[child_id] = [dict(item) for item in source]
    session_store._SESSIONS[child_id]["parent_session_id"] = parent_id
    session_store._save_data()
    return {"session_id": child_id, "title": session_store._SESSIONS[child_id]["title"], "parent_session_id": parent_id}


@router.post("/api/session/truncate")
async def truncate_webui_session(request: Request):
    _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    _session(sid)
    try:
        keep_count = max(0, int(payload.get("keep_count")))
    except (TypeError, ValueError):
        return _json_error("keep_count is required")
    session_store._MESSAGES[sid] = _messages(sid)[:keep_count]
    _touch(sid)
    return {"ok": True, "session": _detail(sid)}


@router.post("/api/session/update")
async def update_webui_session(request: Request):
    _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    sess = _session(sid)
    for key in ("workspace", "model", "model_provider", "profile"):
        if key in payload:
            sess[key] = payload[key]
    _touch(sid)
    return {"ok": True, "session": _detail(sid, include_messages=False)}


@router.post("/api/session/compress")
async def compress_webui_session(request: Request):
    _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    detail = _detail(sid)
    return {"ok": True, "session": detail, "summary": {"headline": "No compression required", "token_line": ""}}


@router.post("/api/session/undo")
async def undo_webui_session(request: Request):
    _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    _session(sid)
    items = _messages(sid)
    removed = items.pop() if items else None
    _touch(sid)
    return {"ok": True, "removed_count": 1 if removed else 0, "removed_preview": _message_text(removed)[:200] if removed else ""}


@router.post("/api/session/retry")
async def retry_webui_session(request: Request):
    _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    _session(sid)
    items = _messages(sid)
    while items and items[-1].get("role") == "assistant":
        items.pop()
    last_user = next((_message_text(item) for item in reversed(items) if item.get("role") == "user"), "")
    _touch(sid)
    return {"ok": True, "last_user_text": last_user, "removed_count": 0}


@router.api_route("/api/session/yolo", methods=["GET", "POST"])
async def session_yolo(request: Request, session_id: Optional[str] = None):
    _require_access(request)
    if request.method == "POST":
        payload = await _body(request)
        session_id = str(payload.get("session_id", ""))
        _session(session_id)["yolo"] = bool(payload.get("enabled", False))
        _touch(session_id)
    if not session_id:
        return {"enabled": False}
    return {"session_id": session_id, "enabled": bool(_session(session_id).get("yolo", False))}


@router.get("/api/session/export")
async def export_webui_session(request: Request, session_id: str, format: str = "json"):
    _require_access(request)
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


@router.get("/api/projects")
async def list_projects(request: Request):
    _require_access(request)
    return {"projects": list(_WEBUI_STATE["projects"])}


@router.post("/api/projects/create")
async def create_project(request: Request):
    _require_access(request)
    payload = await _body(request)
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        return _json_error("name is required")
    project = {"project_id": f"proj_{secrets.token_hex(10)}", "name": name.strip()[:120], "color": payload.get("color"), "created_at": _now()}
    async with _STATE_LOCK:
        _WEBUI_STATE["projects"].append(project)
        _save_state()
    return {"ok": True, "project": project}


@router.post("/api/projects/rename")
async def rename_project(request: Request):
    _require_access(request)
    payload = await _body(request)
    project = _project(str(payload.get("project_id", "")))
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        return _json_error("name is required")
    project["name"] = name.strip()[:120]
    if "color" in payload:
        project["color"] = payload["color"]
    _save_state()
    return {"ok": True, "project": project}


@router.post("/api/projects/delete")
async def delete_project(request: Request):
    _require_access(request)
    payload = await _body(request)
    pid = str(payload.get("project_id", ""))
    _project(pid)
    _WEBUI_STATE["projects"] = [p for p in _WEBUI_STATE["projects"] if p.get("project_id") != pid]
    for sess in session_store._SESSIONS.values():
        if sess.get("project_id") == pid:
            sess["project_id"] = None
    _save_state()
    session_store._save_data()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Chat and file-backed SSE streams
# ---------------------------------------------------------------------------


def _stream_path(stream_id: str, suffix: str) -> Path:
    if not STREAM_ID_RE.fullmatch(stream_id):
        raise HTTPException(status_code=400, detail="Invalid stream id")
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
        if status:
            meta["status"] = status
        _write_stream_meta(stream_id, meta)


def _cancel_requested(stream_id: str) -> bool:
    meta = _read_stream_meta(stream_id)
    return bool(meta and meta.get("cancel_requested"))


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
    sess = _session(session_id)
    assistant_text = []
    reasoning_text = []
    had_error = False
    cancelled = False
    try:
        meta["status"] = "running"
        _write_stream_meta(stream_id, meta)
        backend = os.getenv("HERMES_WEBUI_CHAT_BACKEND", "gateway").strip().lower()
        request_body = {
            "messages": _agent_messages(session_id),
            "model": sess.get("model") or _default_model(),
            "temperature": 0.7,
        }
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
                    await _publish(stream_id, "error", {"error": "Hermes agent request failed", "session_id": session_id}, "error")
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
                                    await _publish(stream_id, "tool", tool_call)
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
                            await _publish(stream_id, "tool", {k: v for k, v in item.items() if k != "type"})
                        elif kind in {"tool_complete", "tool_result"}:
                            await _publish(stream_id, "tool_complete", {k: v for k, v in item.items() if k != "type"})
                        elif kind == "error":
                            had_error = True
                            await _publish(stream_id, "error", {"error": str(item.get("error", "Agent error")), "session_id": session_id}, "error")
                            break
    except asyncio.CancelledError:
        cancelled = True
    except Exception:
        had_error = True
        await _publish(stream_id, "error", {"error": "Hermes agent is temporarily unavailable", "session_id": session_id}, "error")
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
            await _publish(stream_id, "cancel", {"session_id": session_id}, "cancelled")
        elif not had_error:
            detail = _detail(session_id, include_messages=False)
            await _publish(stream_id, "done", {"session_id": session_id, "session": detail, "usage": _session_usage_payload(sess)}, "done")
        meta = _read_stream_meta(stream_id) or meta
        meta["status"] = "cancelled" if (cancelled or _cancel_requested(stream_id)) else ("error" if had_error else "done")
        meta["finished_at"] = _now()
        _write_stream_meta(stream_id, meta)
        if not had_error and not cancelled:
            await _publish(stream_id, "stream_end", {"session_id": session_id}, "done")
        elif cancelled:
            await _publish(stream_id, "stream_end", {"session_id": session_id}, "cancelled")
        else:
            await _publish(stream_id, "stream_end", {"session_id": session_id}, "error")
        _STREAM_LOCKS.pop(stream_id, None)


def _session_usage_payload(sess: Dict[str, Any]) -> Dict[str, Any]:
    return {"input_tokens": sess.get("input_tokens", 0), "output_tokens": sess.get("output_tokens", 0), "total_tokens": sess.get("input_tokens", 0) + sess.get("output_tokens", 0)}


@router.post("/api/chat/start")
async def start_webui_chat(request: Request):
    owner = _stream_owner(request)
    payload = await _body(request)
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        return _json_error("message is required")
    session_id = str(payload.get("session_id") or "")
    if not session_id:
        session_id = _new_session(payload)
    sess = _session(session_id)
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
    sess["active_stream_id"] = secrets.token_urlsafe(24)
    stream_id = sess["active_stream_id"]
    meta = {"stream_id": stream_id, "session_id": session_id, "owner": owner, "status": "starting", "seq": 0, "cancel_requested": False, "created_at": _now()}
    _write_stream_meta(stream_id, meta)
    _stream_events_path(stream_id).write_text("", encoding="utf-8")
    _touch(session_id)
    asyncio.create_task(_chat_worker(stream_id, owner))
    return {"stream_id": stream_id, "session_id": session_id}


@router.get("/api/chat/stream")
async def stream_webui_chat(request: Request, stream_id: str, replay: int = 0, after_seq: Optional[int] = None):
    owner = _stream_owner(request)
    meta = _read_stream_meta(stream_id)
    if not meta or meta.get("owner") != owner:
        raise HTTPException(status_code=404, detail="Stream not found")
    starting_seq = max(0, int(after_seq or 0))

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
                yield f"id: {stream_id}:{last_seq}\\nevent: {record['event']}\\ndata: {json.dumps(record['data'], ensure_ascii=False, separators=(',', ':'))}\\n\\n"
            latest = _read_stream_meta(stream_id) or {}
            latest_seq = int(latest.get("seq", 0))
            if latest.get("status") in {"done", "error", "cancelled"} and last_seq >= latest_seq:
                return
            if _now() - heartbeat_at >= 15:
                heartbeat_at = _now()
                yield ": heartbeat\\n\\n"
            await asyncio.sleep(0.2)

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-store", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@router.api_route("/api/chat/cancel", methods=["GET", "POST"])
async def cancel_webui_chat(request: Request, stream_id: str):
    owner = _stream_owner(request)
    meta = _read_stream_meta(stream_id)
    if not meta or meta.get("owner") != owner:
        raise HTTPException(status_code=404, detail="Stream not found")
    meta["cancel_requested"] = True
    _write_stream_meta(stream_id, meta)
    return {"ok": True, "cancelled": True}


@router.get("/api/chat/stream/status")
async def chat_stream_status(request: Request, stream_id: str):
    owner = _stream_owner(request)
    meta = _read_stream_meta(stream_id)
    if not meta or meta.get("owner") != owner:
        raise HTTPException(status_code=404, detail="Stream not found")
    return {"active": meta.get("status") in {"starting", "running"}, "session_id": meta.get("session_id"), "stream_id": stream_id, "active_stream_id": stream_id if meta.get("status") in {"starting", "running"} else None, "is_streaming": meta.get("status") in {"starting", "running"}, "replay_available": int(meta.get("seq", 0)) > 0}


@router.post("/api/chat/steer")
async def steer_webui_chat(request: Request):
    _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    sess = _session(sid)
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return _json_error("text is required")
    stream_id = sess.get("active_stream_id")
    meta = _read_stream_meta(stream_id)
    if not meta or meta.get("status") not in {"starting", "running"}:
        return {"accepted": False, "fallback": "No active stream"}
    await _publish(stream_id, "pending_steer_leftover", {"text": text.strip()})
    return {"accepted": True, "stream_id": stream_id}


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
    candidate = Path(raw).expanduser() if Path(raw).is_absolute() else root / raw
    candidate = candidate.resolve()
    if not any(_within(candidate, allowed) for allowed in roots):
        raise HTTPException(status_code=403, detail="Path is outside the workspace")
    if must_exist and not candidate.exists():
        raise HTTPException(status_code=404, detail="Path not found")
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
    _require_access(request)
    directory = _workspace_path(session_id, path, must_exist=True)
    if not directory.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")
    entries = []
    for child in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if child.name.startswith("."):
            continue
        entries.append({"name": child.name, "path": str(child.relative_to(_workspace_path(session_id))), "type": "directory" if child.is_dir() else "file", "size": child.stat().st_size if child.is_file() else None, "modified_at": child.stat().st_mtime})
    return {"entries": entries, "path": str(directory)}


@router.get("/api/file")
async def read_workspace_file(request: Request, session_id: str, path: str):
    _require_access(request)
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
    _require_access(request)
    target = _workspace_path(session_id, path, must_exist=True)
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")
    return FileResponse(target, media_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream")


@router.post("/api/upload")
async def upload_workspace_file(request: Request):
    _require_access(request)
    form = await request.form()
    uploaded = form.get("file")
    if not isinstance(uploaded, UploadFile) and not hasattr(uploaded, "filename"):
        return _json_error("file is required")
    session_id = str(form.get("session_id") or "")
    if not session_id:
        session_id = _new_session({})
    root = _workspace_path(session_id)
    destination = root / "uploads"
    destination.mkdir(parents=True, exist_ok=True)
    filename = Path(str(uploaded.filename or "upload.bin")).name.replace("\x00", "")
    if not filename or filename in {".", ".."}:
        return _json_error("Invalid filename")
    target = destination / filename
    counter = 1
    while target.exists():
        target = destination / f"{Path(filename).stem}-{counter}{Path(filename).suffix}"
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
                    return _json_error("Upload exceeds the configured size limit", 413)
                output.write(chunk)
    finally:
        await uploaded.close()
    relative = str(target.relative_to(root))
    return {"filename": target.name, "path": relative, "mime": getattr(uploaded, "content_type", None) or "application/octet-stream", "size": total, "is_image": (getattr(uploaded, "content_type", "") or "").startswith("image/")}


@router.post("/api/upload/extract")
async def extract_uploaded_file(request: Request):
    _require_access(request)
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/"):
        form = await request.form()
        uploaded = form.get("file")
        if not isinstance(uploaded, UploadFile) and not hasattr(uploaded, "filename"):
            return _json_error("file is required")
        session_id = str(form.get("session_id") or "")
        if not session_id:
            session_id = _new_session({})
        root = _workspace_path(session_id)
        destination = root / "uploads"
        destination.mkdir(parents=True, exist_ok=True)
        filename = Path(str(uploaded.filename or "upload.bin")).name.replace("\\x00", "")
        if not filename or filename in {".", ".."}:
            return _json_error("Invalid filename")
        target = destination / filename
        counter = 1
        while target.exists():
            target = destination / f"{Path(filename).stem}-{counter}{Path(filename).suffix}"
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
        target = _workspace_path(str(payload.get("session_id", "")), str(payload.get("path", "")), must_exist=True)
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
    values = [_default_model(), "auto/best-coding", "auto/best-reasoning", "auto/best-chat", "auto/fast"]
    return list(dict.fromkeys(item for item in values if item))


def _model_rows() -> List[Dict[str, Any]]:
    return [{"id": item, "name": item, "label": item, "provider": "omniroute", "provider_id": "omniroute"} for item in _model_ids()]


def _provider_rows() -> List[Dict[str, Any]]:
    base = os.getenv("OMNIROUTE_BASE_URL", os.getenv("UPSTREAM_OMNIROUTE_URL", ""))
    parsed = urlsplit(base)
    safe_base = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")) if parsed.scheme else ""
    return [{"id": "omniroute", "name": "OmniRoute", "display_name": "OmniRoute", "configured": bool(base), "has_key": bool(os.getenv("OMNIROUTE_API_KEY") or os.getenv("UPSTREAM_API_KEY")), "configurable": False, "is_self_hosted": False, "base_url": safe_base, "models": [{"id": item, "label": item} for item in _model_ids()], "models_total": len(_model_ids())}]


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
    _require_access(request)
    payload = await _body(request)
    sid = str(payload.get("session_id", ""))
    _session(sid)
    return {"ok": True, "personality": payload.get("name")}


@router.get("/api/media")
async def media_workspace_file(request: Request, session_id: str, path: str):
    return await raw_workspace_file(request, session_id, path)


@router.get("/api/models")
async def webui_models(request: Request):
    _require_access(request)
    return {"models": _model_rows(), "providers": _provider_rows(), "groups": [], "active_provider": "omniroute", "default_model": _default_model()}


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
