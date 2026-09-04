"""
v1 Sessions & Code API Router
Implements the v1 endpoints that the APK expects at /v1/*
Proxies to internal Hermes Agent (:8642) or returns graceful defaults if unhandled
"""
import os
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Request, Query, Body, Path, HTTPException, Header
from fastapi.responses import JSONResponse, StreamingResponse

from gateway.utils import proxy_http_request

router = APIRouter(tags=["v1 Sessions & Code"])

# Internal Hermes Agent base URL
HERMES_INTERNAL_PORT = int(os.getenv("HERMES_INTERNAL_PORT", "8642"))
HERMES_BASE = f"http://127.0.0.1:{HERMES_INTERNAL_PORT}"
API_SERVER_KEY = os.getenv("API_SERVER_KEY", os.getenv("OMNIROUTE_API_KEY", ""))


def _auth_headers(request: Request) -> dict:
    auth = request.headers.get("authorization")
    if auth:
        return {"Authorization": auth}
    return {"Authorization": f"Bearer {API_SERVER_KEY}"}


async def _proxy_to_hermes(path: str, request: Request, default_fallback: Any = None):
    """Proxy request to internal Hermes Agent at /v1/{path}, returning fallback if 404"""
    target = f"{HERMES_BASE}/v1/{path}"
    try:
        resp = await proxy_http_request(target, request, extra_headers=_auth_headers(request))
        if resp.status_code == 404 and default_fallback is not None:
            return JSONResponse(default_fallback)
        return resp
    except Exception:
        if default_fallback is not None:
            return JSONResponse(default_fallback)
        raise


# ============================================================
# v1 CODE SESSIONS
# ============================================================

@router.get("/v1/code/sessions")
async def list_code_sessions(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List code sessions"""
    return await _proxy_to_hermes("code/sessions", request, default_fallback={"data": [], "has_more": False})


@router.post("/v1/code/sessions")
async def create_code_session(
    request: Request,
    body: dict = Body(...),
):
    """Create a new code session"""
    session_id = f"cs_{os.urandom(8).hex()}"
    return await _proxy_to_hermes("code/sessions", request, default_fallback={"id": session_id, "status": "active", "created_at": "2026-08-26T00:00:00Z"})


@router.get("/v1/code/sessions/{session_id}")
async def get_code_session(
    request: Request,
    session_id: str = Path(...),
):
    """Get code session details"""
    return await _proxy_to_hermes(f"code/sessions/{session_id}", request, default_fallback={"id": session_id, "status": "active", "events": []})


@router.delete("/v1/code/sessions/{session_id}")
async def delete_code_session(
    request: Request,
    session_id: str = Path(...),
):
    """Delete a code session"""
    return await _proxy_to_hermes(f"code/sessions/{session_id}", request, default_fallback={"status": "deleted", "id": session_id})


@router.post("/v1/code/sessions/{session_id}/archive")
async def archive_code_session(
    request: Request,
    session_id: str = Path(...),
):
    """Archive a code session"""
    return await _proxy_to_hermes(f"code/sessions/{session_id}/archive", request, default_fallback={"status": "archived", "id": session_id})


@router.post("/v1/code/sessions/{session_id}/unarchive")
async def unarchive_code_session(
    request: Request,
    session_id: str = Path(...),
):
    """Unarchive a code session"""
    return await _proxy_to_hermes(f"code/sessions/{session_id}/unarchive", request, default_fallback={"status": "active", "id": session_id})


@router.get("/v1/code/sessions/{session_id}/events")
async def get_code_session_events(
    request: Request,
    session_id: str = Path(...),
    after: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    """Get code session events (polling)"""
    return await _proxy_to_hermes(f"code/sessions/{session_id}/events", request, default_fallback={"events": [], "has_more": False})


@router.get("/v1/code/sessions/{session_id}/events/stream")
async def stream_code_session_events(
    request: Request,
    session_id: str = Path(...),
    after: Optional[str] = Query(None),
):
    """Stream code session events (SSE)"""
    return await _proxy_to_hermes(f"code/sessions/{session_id}/events/stream", request, default_fallback={"events": [], "has_more": False})


@router.post("/v1/code/sessions/{session_id}/mark_read")
async def mark_code_session_read(
    request: Request,
    session_id: str = Path(...),
    body: dict = Body(...),
):
    """Mark code session as read"""
    return await _proxy_to_hermes(f"code/sessions/{session_id}/mark_read", request, default_fallback={"status": "ok"})


@router.post("/v1/code/sessions/{session_id}/ping")
async def ping_code_session(
    request: Request,
    session_id: str = Path(...),
):
    """Ping a code session"""
    return await _proxy_to_hermes(f"code/sessions/{session_id}/ping", request, default_fallback={"status": "pong"})


@router.get("/v1/code/sessions/{session_id}/mcp-servers")
async def list_session_mcp_servers(
    request: Request,
    session_id: str = Path(...),
):
    """List MCP servers for a code session"""
    return await _proxy_to_hermes(f"code/sessions/{session_id}/mcp-servers", request, default_fallback={"servers": []})


@router.get("/v1/code/sessions/{session_id}/client/presence")
async def get_session_client_presence(
    request: Request,
    session_id: str = Path(...),
):
    """Get client presence for a code session"""
    return await _proxy_to_hermes(f"code/sessions/{session_id}/client/presence", request, default_fallback={"active": True})


@router.get("/v1/code/sessions/agent_owned")
async def list_agent_owned_sessions(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
):
    """List agent-owned code sessions"""
    return await _proxy_to_hermes("code/sessions/agent_owned", request, default_fallback={"data": [], "has_more": False})


@router.get("/v1/code/session_groupings")
async def get_code_session_groupings(request: Request):
    """Get code session groupings"""
    return await _proxy_to_hermes("code/session_groupings", request, default_fallback={"groupings": []})


# ============================================================
# v1 CODE GITHUB INTEGRATION
# ============================================================

@router.post("/v1/code/github/set-pr-auto-merge")
async def set_pr_auto_merge(
    request: Request,
    body: dict = Body(...),
):
    """Set PR auto-merge"""
    return await _proxy_to_hermes("code/github/set-pr-auto-merge", request, default_fallback={"status": "ok"})


@router.post("/v1/code/github/compare-refs")
async def compare_github_refs(
    request: Request,
    body: dict = Body(...),
):
    """Compare Git refs"""
    return await _proxy_to_hermes("code/github/compare-refs", request, default_fallback={"files": [], "ahead": 0, "behind": 0})


@router.post("/v1/code/github/batch-branch-status")
async def batch_branch_status(
    request: Request,
    body: dict = Body(...),
):
    """Get batch branch status"""
    return await _proxy_to_hermes("code/github/batch-branch-status", request, default_fallback={"branches": []})


@router.post("/v1/code/github/subscribe-pr")
async def subscribe_pr(
    request: Request,
    body: dict = Body(...),
):
    """Subscribe to PR"""
    return await _proxy_to_hermes("code/github/subscribe-pr", request, default_fallback={"status": "subscribed"})


@router.post("/v1/code/github/unsubscribe-pr")
async def unsubscribe_pr(
    request: Request,
    body: dict = Body(...),
):
    """Unsubscribe from PR"""
    return await _proxy_to_hermes("code/github/unsubscribe-pr", request, default_fallback={"status": "unsubscribed"})


@router.get("/v1/code/github/get-file-content")
async def get_github_file_content(
    request: Request,
    owner: str = Query(...),
    repo: str = Query(...),
    path: str = Query(...),
    ref: str = Query(...),
):
    """Get GitHub file content"""
    return await _proxy_to_hermes("code/github/get-file-content", request, default_fallback={"content": "", "encoding": "utf-8"})


@router.get("/v1/code/runners/self-hosted/pools")
async def list_self_hosted_pools(request: Request):
    """List self-hosted runner pools"""
    return await _proxy_to_hermes("code/runners/self-hosted/pools", request, default_fallback={"pools": []})


# ============================================================
# v1 SESSIONS (General)
# ============================================================

@router.get("/v1/sessions")
async def list_sessions(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List all sessions"""
    return await _proxy_to_hermes("sessions", request, default_fallback={"data": [], "has_more": False})


@router.post("/v1/sessions")
async def create_session(
    request: Request,
    body: dict = Body(...),
):
    """Create a new session"""
    session_id = f"s_{os.urandom(8).hex()}"
    return await _proxy_to_hermes("sessions", request, default_fallback={"id": session_id, "status": "active", "created_at": "2026-08-26T00:00:00Z"})


@router.get("/v1/sessions/{session_id}")
async def get_session(
    request: Request,
    session_id: str = Path(...),
):
    """Get session details"""
    return await _proxy_to_hermes(f"sessions/{session_id}", request, default_fallback={"id": session_id, "status": "active", "events": []})


@router.get("/v1/sessions/{session_id}/events")
async def get_session_events(
    request: Request,
    session_id: str = Path(...),
    after: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    """Get session events (polling)"""
    return await _proxy_to_hermes(f"sessions/{session_id}/events", request, default_fallback={"events": [], "has_more": False})


@router.get("/v1/sessions/{session_id}/share-status")
async def get_session_share_status(
    request: Request,
    session_id: str = Path(...),
):
    """Get session share status"""
    return await _proxy_to_hermes(f"sessions/{session_id}/share-status", request, default_fallback={"is_shared": False})


@router.get("/v1/sessions/watch")
async def watch_sessions(request: Request):
    """Watch sessions (SSE)"""
    return await _proxy_to_hermes("sessions/watch", request, default_fallback={"status": "active"})


@router.get("/v1/sessions-share")
async def list_session_shares(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
):
    """List session shares"""
    return await _proxy_to_hermes("sessions-share", request, default_fallback={"shares": []})


@router.post("/v1/sessions-share")
async def create_session_share(
    request: Request,
    body: dict = Body(...),
):
    """Create a session share"""
    return await _proxy_to_hermes("sessions-share", request, default_fallback={"id": f"sh_{os.urandom(8).hex()}", "url": ""})


@router.get("/v1/sessions-share/{share_id}")
async def get_session_share(
    request: Request,
    share_id: str = Path(...),
):
    """Get session share details"""
    return await _proxy_to_hermes(f"sessions-share/{share_id}", request, default_fallback={"id": share_id, "active": True})


# ============================================================
# v1 ENVIRONMENT PROVIDERS
# ============================================================

@router.get("/v1/environment_providers/private/organizations/{org_id}/environments")
async def list_environments(
    request: Request,
    org_id: str = Path(...),
):
    """List environments for organization"""
    return await _proxy_to_hermes(f"environment_providers/private/organizations/{org_id}/environments", request, default_fallback={"environments": []})


@router.get("/v1/environment_providers/private/organizations/{org_id}/environments/{env_id}")
async def get_environment(
    request: Request,
    org_id: str = Path(...),
    env_id: str = Path(...),
):
    """Get environment details"""
    return await _proxy_to_hermes(f"environment_providers/private/organizations/{org_id}/environments/{env_id}", request, default_fallback={"id": env_id, "name": "Default Environment", "status": "running"})


@router.post("/v1/environment_providers/private/organizations/{org_id}/environments/{env_id}/archive")
async def archive_environment(
    request: Request,
    org_id: str = Path(...),
    env_id: str = Path(...),
):
    """Archive an environment"""
    return await _proxy_to_hermes(f"environment_providers/private/organizations/{org_id}/environments/{env_id}/archive", request, default_fallback={"status": "archived"})


@router.post("/v1/environment_providers/private/organizations/{org_id}/cloud/create")
async def create_cloud_environment(
    request: Request,
    org_id: str = Path(...),
    body: dict = Body(...),
):
    """Create a cloud environment"""
    return await _proxy_to_hermes(f"environment_providers/private/organizations/{org_id}/cloud/create", request, default_fallback={"id": f"env_{os.urandom(8).hex()}", "status": "created"})


# ============================================================
# v1 SESSION INGRESS (Git Proxy)
# ============================================================

@router.get("/v1/session_ingress/session/{session_id}/git_proxy/file")
async def git_proxy_file(
    request: Request,
    session_id: str = Path(...),
    path: str = Query(...),
    ref: str = Query(...),
):
    """Get file via git proxy"""
    return await _proxy_to_hermes(f"session_ingress/session/{session_id}/git_proxy/file", request, default_fallback={"content": ""})


@router.get("/v1/session_ingress/session/{session_id}/git_proxy/compare")
async def git_proxy_compare(
    request: Request,
    session_id: str = Path(...),
    base: str = Query(...),
    head: str = Query(...),
):
    """Compare refs via git proxy"""
    return await _proxy_to_hermes(f"session_ingress/session/{session_id}/git_proxy/compare", request, default_fallback={"files": []})


# ============================================================
# v1 TRIGGERS
# ============================================================

@router.get("/v1/triggers")
async def list_triggers(request: Request):
    """List triggers"""
    return await _proxy_to_hermes("triggers", request, default_fallback={"triggers": []})


@router.get("/v1/triggers/{trigger_id}")
async def get_trigger(
    request: Request,
    trigger_id: str = Path(...),
):
    """Get trigger details"""
    return await _proxy_to_hermes(f"triggers/{trigger_id}", request, default_fallback={"id": trigger_id, "active": True})


# ============================================================
# v1 FILESTORE (File Upload)
# ============================================================

@router.post("/v1/filestore/fs/createFile")
async def create_filestore_file(
    request: Request,
    body: dict = Body(...),
):
    """Create file in filestore"""
    return await _proxy_to_hermes("filestore/fs/createFile", request, default_fallback={"file_id": f"file_{os.urandom(8).hex()}", "status": "created"})


@router.post("/v1/organizations/{org_id}/conversations/{conv_id}/files/prepare-upload")
async def prepare_file_upload(
    request: Request,
    org_id: str = Path(...),
    conv_id: str = Path(...),
    body: dict = Body(...),
):
    """Prepare file upload"""
    return await _proxy_to_hermes(f"organizations/{org_id}/conversations/{conv_id}/files/prepare-upload", request, default_fallback={"upload_url": "/v1/filestore/upload", "file_id": f"file_{os.urandom(8).hex()}"})


# ============================================================
# CHAT FEEDBACK
# ============================================================

@router.post("/v1/organizations/{org}/chat_conversations/{chat}/chat_messages/{message}/chat_feedback")
async def submit_chat_feedback(
    request: Request,
    org: str = Path(...),
    chat: str = Path(...),
    message: str = Path(...),
    body: dict = Body(...),
):
    """Submit chat feedback"""
    return await _proxy_to_hermes(f"organizations/{org}/chat_conversations/{chat}/chat_messages/{message}/chat_feedback", request, default_fallback={"status": "ok"})


# ============================================================
# HEALTH CHECK FOR V1
# ============================================================

@router.get("/v1/health")
async def v1_health(request: Request):
    """v1 API health check"""
    return await _proxy_to_hermes("health", request, default_fallback={"status": "healthy"})
