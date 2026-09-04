"""
Ignis (Obsidian) Router — proxies vault management to Ignis server.
Routes: /obsidian/*, /vault/*, /ws (LiveSync WebSocket)
"""
import os
from fastapi import APIRouter, Request, WebSocket
from gateway.utils import proxy_http_request, proxy_websocket_stream

router = APIRouter(tags=["Ignis"])

IGNIS_PORT = int(os.getenv("IGNIS_PORT", "8080"))


@router.api_route("/obsidian", methods=["GET", "HEAD"])
async def obsidian_root():
    from fastapi.responses import JSONResponse
    return JSONResponse({"status": "ok", "service": "Ignis Obsidian", "port": IGNIS_PORT})


@router.api_route("/obsidian/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def obsidian_proxy(request: Request, path: str = ""):
    target = f"http://127.0.0.1:{IGNIS_PORT}/obsidian/{path}" if path else f"http://127.0.0.1:{IGNIS_PORT}/obsidian"
    return await proxy_http_request(target, request)


@router.api_route("/vault/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def vault_proxy(request: Request, path: str = ""):
    target = f"http://127.0.0.1:{IGNIS_PORT}/vault/{path}" if path else f"http://127.0.0.1:{IGNIS_PORT}/vault"
    return await proxy_http_request(target, request)


@router.api_route("/api/vaults", methods=["GET", "POST", "HEAD", "OPTIONS"])
@router.api_route("/api/vaults/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def vaults_api(request: Request, path: str = ""):
    target = f"http://127.0.0.1:{IGNIS_PORT}/api/vaults/{path}" if path else f"http://127.0.0.1:{IGNIS_PORT}/api/vaults"
    return await proxy_http_request(target, request)


@router.api_route("/api/files/{vault}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def files_api(request: Request, vault: str, path: str = ""):
    target = f"http://127.0.0.1:{IGNIS_PORT}/api/files/{vault}/{path}"
    return await proxy_http_request(target, request)


@router.websocket("/ws")
@router.websocket("/obsidian/ws")
async def obsidian_ws(websocket: WebSocket):
    ws_path = websocket.scope.get("path", "/ws")
    target_ws = f"ws://127.0.0.1:{IGNIS_PORT}{ws_path}"
    await proxy_websocket_stream(websocket, target_ws)
