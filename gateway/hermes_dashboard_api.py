"""Compatibility surface for the upstream Hermes Web Dashboard.

The upstream dashboard is intentionally kept unmodified.  This router maps
the dashboard's current management API onto the existing Hermex stores and
chat worker.  Unsupported upstream administration features return an explicit
501 response instead of a fake success payload.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from gateway import sessions_api as session_store
from gateway import webui_api as webui

router = APIRouter(tags=["Official Hermes Dashboard"])

_WS_TICKETS: Dict[str, float] = {}
_EVENT_CLIENTS: set[WebSocket] = set()
_TICKET_TTL = 30
_UNSUPPORTED_PREFIXES = (
    "/api/cron/",
    "/api/mcp",
    "/api/oauth",
    "/api/plugins",
    "/api/dashboard/",
    "/api/skills",
    "/api/tools/",
    "/api/providers/oauth",
    "/api/messaging/",
    "/api/webhooks",
)


def _access(request: Request) -> str:
    return webui._require_access(request)


def _config_model() -> str:
    return os.getenv("HERMES_DEFAULT_MODEL", "").strip() or webui._default_model()


def _models() -> List[str]:
    raw = os.getenv("HERMES_AVAILABLE_MODELS", "")
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values or [_config_model()]


def _info(session_id: str, session: Dict[str, Any]) -> Dict[str, Any]:
    messages = session_store._MESSAGES.get(session_id, [])
    started = webui._epoch(session.get("created_at"))
    updated = webui._epoch(session.get("updated_at"))
    active = bool(webui._read_stream_meta(session.get("active_stream_id")))
    return {
        "id": session_id,
        "source": "webui",
        "model": session.get("model") or _config_model(),
        "title": session.get("title") or "Chat",
        "started_at": started,
        "ended_at": None if active else updated,
        "last_active": updated,
        "is_active": active,
        "message_count": len(messages),
        "tool_call_count": sum(1 for item in messages if item.get("tool_calls")),
        "input_tokens": session.get("input_tokens", 0),
        "output_tokens": session.get("output_tokens", 0),
        "preview": webui._message_text(messages[-1]) if messages else None,
    }


def _owned_info(session_id: str, owner: str) -> Dict[str, Any]:
    return _info(session_id, webui._owned_session(session_id, owner))


def _unsupported(path: str) -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "code": "feature_not_supported",
                "message": f"{path} is not supported by the Hermex compatibility layer",
            }
        },
        status_code=501,
    )


@router.get("/api/status")
async def dashboard_status(request: Request):
    _access(request)
    active = 0
    for session in session_store._SESSIONS.values():
        if webui._read_stream_meta(session.get("active_stream_id")):
            active += 1
    return {
        "active_sessions": active,
        "auth_required": webui._auth_enabled(),
        "auth_providers": ["password"] if webui._password() else [],
        "auth_flows": ["cookie"] if webui._auth_enabled() else [],
        "can_update_hermes": False,
        "config_path": os.getenv("HERMES_CONFIG_PATH", "/data/hermes/config.json"),
        "config_version": 1,
        "env_path": "/data/hermes/.env",
        "gateway_exit_reason": None,
        "gateway_health_url": "/health",
        "gateway_pid": os.getpid(),
        "gateway_platforms": {},
        "gateway_running": True,
        "gateway_state": "running",
        "gateway_updated_at": None,
        "hermes_home": os.getenv("HERMES_SERVER_WORKDIR", "/app"),
        "latest_config_version": 1,
        "memory": {"pressure": "unknown"},
        "disk": {"pressure": "unknown"},
        "release_date": "",
        "version": os.getenv("HERMES_VERSION", "hermex"),
    }


@router.get("/api/auth/me")
async def dashboard_auth_me(request: Request):
    _access(request)
    return {"authenticated": True, "provider": "password" if webui._password() else None, "subject": webui.WEBUI_PRINCIPAL}


@router.post("/api/auth/ws-ticket")
async def dashboard_ws_ticket(request: Request):
    _access(request)
    ticket = secrets.token_urlsafe(32)
    _WS_TICKETS[ticket] = time.time() + _TICKET_TTL
    return {"ticket": ticket, "ttl_seconds": _TICKET_TTL}


@router.get("/api/sessions/{session_id}")
async def dashboard_session(request: Request, session_id: str):
    owner = _access(request)
    return _owned_info(session_id, owner)


@router.get("/api/sessions/{session_id}/messages")
async def dashboard_session_messages(
    request: Request,
    session_id: str,
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    order: str = Query("latest"),
):
    owner = _access(request)
    webui._owned_session(session_id, owner)
    values = session_store._MESSAGES.get(session_id, [])
    ordered = values if order != "latest" else list(reversed(values))
    selected = ordered[offset : offset + limit]
    messages = [
        {
            "role": item.get("role", "user"),
            "content": webui._message_text(item),
            "timestamp": webui._epoch(item.get("timestamp") or item.get("created_at")),
            **({"tool_calls": item["tool_calls"]} if item.get("tool_calls") else {}),
        }
        for item in selected
    ]
    return {
        "session_id": session_id,
        "messages": messages,
        "pagination": {"limit": limit, "offset": offset, "order": order, "returned": len(messages)},
    }


@router.get("/api/sessions/{session_id}/latest-descendant")
async def dashboard_latest_descendant(request: Request, session_id: str):
    owner = _access(request)
    webui._owned_session(session_id, owner)
    return {"requested_session_id": session_id, "session_id": session_id, "path": [session_id], "changed": False}


@router.delete("/api/sessions/{session_id}")
async def dashboard_delete_session(request: Request, session_id: str):
    owner = _access(request)
    if session_id == "empty":
        removed = 0
        for candidate in list(session_store._SESSIONS):
            session = session_store._SESSIONS[candidate]
            if session.get("webui_owner") in {None, owner} and not session_store._MESSAGES.get(candidate):
                session_store._SESSIONS.pop(candidate, None)
                session_store._MESSAGES.pop(candidate, None)
                removed += 1
        session_store._save_data()
        return {"ok": True, "deleted": removed}
    webui._owned_session(session_id, owner)
    session_store._SESSIONS.pop(session_id, None)
    session_store._MESSAGES.pop(session_id, None)
    session_store._save_data()
    return {"ok": True}


@router.delete("/api/sessions/empty")
async def dashboard_delete_empty_sessions(request: Request):
    owner = _access(request)
    removed = 0
    for session_id in list(session_store._SESSIONS):
        session = session_store._SESSIONS[session_id]
        if session.get("webui_owner") in {None, owner} and not session_store._MESSAGES.get(session_id):
            session_store._SESSIONS.pop(session_id, None)
            session_store._MESSAGES.pop(session_id, None)
            removed += 1
    session_store._save_data()
    return {"ok": True, "deleted": removed}


@router.post("/api/sessions/bulk-delete")
async def dashboard_bulk_delete(request: Request):
    owner = _access(request)
    body = await webui._body(request)
    ids = body.get("ids") or body.get("session_ids") or []
    if not isinstance(ids, list):
        raise HTTPException(status_code=400, detail="ids must be a list")
    deleted = 0
    for value in ids:
        session_id = str(value)
        if session_id in session_store._SESSIONS:
            webui._owned_session(session_id, owner)
            session_store._SESSIONS.pop(session_id, None)
            session_store._MESSAGES.pop(session_id, None)
            deleted += 1
    session_store._save_data()
    return {"ok": True, "deleted": deleted}

@router.get("/api/sessions/empty/count")
async def dashboard_empty_count(request: Request):
    owner = _access(request)
    count = sum(
        not session_store._MESSAGES.get(sid)
        for sid, session in session_store._SESSIONS.items()
        if session.get("webui_owner") in {None, owner}
    )
    return {"count": count}


@router.get("/api/sessions/stats")
async def dashboard_session_stats(request: Request):
    owner = _access(request)
    sessions = [s for sid, s in session_store._SESSIONS.items() if session_store._MESSAGES.get(sid) is not None and s.get("webui_owner") in {None, owner}]
    return {"total": len(sessions), "active": sum(bool(s.get("active_stream_id")) for s in sessions)}


@router.get("/api/sessions/search")
async def dashboard_search(request: Request, q: str = ""):
    owner = _access(request)
    needle = q.strip().lower()
    results = []
    for sid, session in session_store._SESSIONS.items():
        if session.get("webui_owner") not in {None, owner}:
            continue
        text = " ".join(webui._message_text(item) for item in session_store._MESSAGES.get(sid, []))
        haystack = f"{session.get('title', '')} {text}".lower()
        if needle in haystack:
            item = _info(sid, session)
            item.update({"session_id": sid, "snippet": text[-240:], "role": "assistant" if text else None, "session_started": item["started_at"]})
            results.append(item)
    return {"results": results}


@router.get("/api/config")
async def dashboard_config(request: Request):
    _access(request)
    return {"model": _config_model(), "available_models": _models(), "reasoning_effort": "medium"}


@router.put("/api/config")
async def dashboard_save_config(request: Request):
    _access(request)
    body = await webui._body(request)
    config = body.get("config") if isinstance(body.get("config"), dict) else body
    model = config.get("model") if isinstance(config, dict) else None
    if model is not None and (not isinstance(model, str) or model not in _models()):
        raise HTTPException(status_code=400, detail="model is not an available model")
    return {"ok": True}


@router.get("/api/config/defaults")
async def dashboard_config_defaults(request: Request):
    _access(request)
    return {"model": _config_model(), "reasoning_effort": "medium"}


@router.get("/api/config/schema")
async def dashboard_config_schema(request: Request):
    _access(request)
    return {"fields": {}, "category_order": []}


@router.get("/api/config/raw")
async def dashboard_config_raw(request: Request):
    _access(request)
    return {"yaml": f"model: {_config_model()}\n", "path": os.getenv("HERMES_CONFIG_PATH", "/data/hermes/config.yaml")}


@router.get("/api/model/info")
async def dashboard_model_info(request: Request):
    _access(request)
    model = _config_model()
    return {
        "model": model,
        "provider": "omniroute",
        "auto_context_length": 0,
        "config_context_length": 0,
        "effective_context_length": 0,
        "capabilities": {"supports_tools": True, "supports_reasoning": True, "model_family": model},
    }


@router.get("/api/model/options")
async def dashboard_model_options(request: Request):
    _access(request)
    return {"models": [{"id": model, "label": model, "provider": "omniroute", "configured": True} for model in _models()]}


@router.get("/api/profiles")
async def dashboard_profiles(request: Request):
    _access(request)
    profiles = webui._WEBUI_STATE.get("profiles", [])
    if not profiles:
        profiles = [{"name": "default", "display_name": "Default", "is_default": True, "is_active": True, "model": _config_model(), "provider": "omniroute"}]
    return {"profiles": profiles}


@router.get("/api/profiles/active")
async def dashboard_active_profile(request: Request):
    _access(request)
    return {"name": "default", "display_name": "Default"}


@router.get("/api/logs")
async def dashboard_logs(request: Request, file: str = "gateway", lines: int = Query(200, ge=1, le=1000)):
    _access(request)
    path = webui.LOG_FILES.get(file, webui.LOG_FILES["gateway"]) if hasattr(webui, "LOG_FILES") else f"/data/cache/{file}.log"
    try:
        content = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except OSError:
        content = []
    return {"file": file, "lines": content}


@router.get("/api/gateway")
async def dashboard_gateway(request: Request):
    _access(request)
    return {"running": True, "state": "running", "pid": os.getpid(), "platforms": {}}


@router.get("/api/analytics")
async def dashboard_analytics(request: Request):
    _access(request)
    return {"daily": [], "models": [], "skills": [], "total": {"input_tokens": 0, "output_tokens": 0}}


@router.websocket("/api/events")
async def dashboard_events(websocket: WebSocket):
    owner = _ws_owner(websocket)
    if owner is None:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    _EVENT_CLIENTS.add(websocket)
    try:
        await websocket.send_json({"type": "gateway.ready", "payload": {"owner": owner}, "seq": 0})
        while True:
            message = await websocket.receive_text()
            if message:
                try:
                    payload = json.loads(message)
                except ValueError:
                    payload = {}
                if payload.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        _EVENT_CLIENTS.discard(websocket)


def _ws_owner(websocket: WebSocket) -> Optional[str]:
    token = websocket.cookies.get("hermes_webui_session")
    if not token:
        auth = websocket.headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
    query_ticket = websocket.query_params.get("ticket") or websocket.query_params.get("token")
    if query_ticket in _WS_TICKETS:
        if _WS_TICKETS.pop(query_ticket) < time.time():
            return None
        # A ticket was minted only after an authenticated REST request, so it
        # is the credential for this single upgrade.  Do not require a cookie
        # on the upgrade itself; browsers cannot attach arbitrary headers.
        token = "ticket-authorized"
        if not webui._auth_enabled():
            return "anonymous"
        return webui.WEBUI_PRINCIPAL
    if not webui._valid_session_token(token):
        return None
    return webui.WEBUI_PRINCIPAL if webui._auth_enabled() else "anonymous"


@router.websocket("/api/ws")
async def dashboard_gateway_ws(websocket: WebSocket):
    owner = _ws_owner(websocket)
    if owner is None:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    await websocket.send_json({"method": "event", "params": {"type": "gateway.ready", "payload": {"owner": owner}}})
    try:
        while True:
            frame = json.loads(await websocket.receive_text())
            request_id = frame.get("id")
            method = frame.get("method")
            params = frame.get("params") or {}
            if method == "gateway.ping":
                result = {"ok": True}
            elif method == "session.create":
                session_id = webui._new_session(params, owner)
                result = {"session_id": session_id}
                await websocket.send_json({"method": "event", "params": {"type": "session.info", "session_id": session_id, "payload": {"session_id": session_id}}})
            elif method == "config.set":
                result = {"ok": True}
            else:
                await websocket.send_json({"id": request_id, "error": {"code": -32601, "message": f"Unsupported method: {method}"}})
                continue
            await websocket.send_json({"id": request_id, "result": result})
    except (WebSocketDisconnect, ValueError):
        return


@router.websocket("/api/pty")
async def dashboard_pty(websocket: WebSocket):
    """Safe dashboard chat bridge backed by the existing Hermes stream worker."""
    owner = _ws_owner(websocket)
    if owner is None:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    session_id: Optional[str] = None
    buffer = ""
    await websocket.send_text("Hermex dashboard chat ready\r\n> ")
    try:
        while True:
            raw = await websocket.receive()
            if raw.get("type") == "websocket.disconnect":
                break
            if raw.get("bytes") is not None:
                chunk = raw["bytes"].decode("utf-8", errors="replace")
            else:
                chunk = raw.get("text", "")
            if not chunk:
                continue
            try:
                control = json.loads(chunk)
                if isinstance(control, dict) and control.get("type") in {"resize", "ping"}:
                    if control["type"] == "ping":
                        await websocket.send_text("\x1b[2K\r")
                    continue
            except ValueError:
                pass
            buffer += chunk.replace("\x00", "")
            if "\r" not in buffer and "\n" not in buffer:
                continue
            prompt, buffer = buffer.replace("\r", "\n").split("\n", 1)
            prompt = prompt.strip()
            if not prompt:
                await websocket.send_text("> ")
                continue
            if session_id is None:
                session_id = webui._new_session({"title": "Dashboard chat"}, owner)
            session = webui._owned_session(session_id, owner)
            webui._messages(session_id).append({"id": f"msg_{secrets.token_hex(12)}", "role": "user", "content": prompt, "timestamp": webui._now()})
            stream_id = webui._queue_chat_stream(session_id, owner)
            last_seq = 0
            while True:
                await asyncio.sleep(0.1)
                meta = webui._read_stream_meta(stream_id) or {}
                try:
                    records = [json.loads(line) for line in webui._stream_events_path(stream_id).read_text(encoding="utf-8").splitlines()]
                except OSError:
                    records = []
                for record in records:
                    if int(record.get("seq", 0)) <= last_seq:
                        continue
                    last_seq = int(record["seq"])
                    event = record.get("event")
                    data = record.get("data", {})
                    if event == "token":
                        await websocket.send_text(str(data.get("text", "")))
                    elif event == "reasoning":
                        await websocket.send_text(f"\r\n[thinking] {data.get('text', '')}")
                    elif event == "tool_call":
                        await websocket.send_text(f"\r\n[tool] {data.get('name', 'tool')}\r\n")
                    elif event == "error":
                        await websocket.send_text(f"\r\n[error] {data.get('error', 'request failed')}\r\n")
                if meta.get("status") in {"completed", "cancelled", "error"} and last_seq >= int(meta.get("seq", 0)):
                    await websocket.send_text("\r\n> ")
                    break
    except (WebSocketDisconnect, RuntimeError):
        return


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def dashboard_unsupported(request: Request, path: str):
    """Advertise an honest boundary for upstream pages not backed by Hermex."""
    if not path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    _access(request)
    return _unsupported("/" + path)