import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from gateway.utils import proxy_http_request

router = APIRouter(tags=["HermesProxy"])

# Hermes agent API server runs inside the container on this port. The public
# gateway (7860) reverse-proxies /v1/* and /health to it so the Space exposes
# exactly one public port.
HERMES_INTERNAL_PORT = int(os.getenv("HERMES_INTERNAL_PORT", "8642"))
API_SERVER_KEY = os.getenv("API_SERVER_KEY", os.getenv("OMNIROUTE_API_KEY", ""))

HERMES_BASE = f"http://127.0.0.1:{HERMES_INTERNAL_PORT}"


def _auth_headers(request: Request):
    auth = request.headers.get("authorization")
    if auth:
        return {"Authorization": auth}
    return {"Authorization": f"Bearer {API_SERVER_KEY}"}


async def _proxy(target_url: str, request: Request):
    try:
        return await proxy_http_request(target_url, request, extra_headers=_auth_headers(request))
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return JSONResponse(
            {"error": {"message": "Hermes agent is not reachable (starting up?)",
                       "type": "upstream_connection_error"}},
            status_code=502,
        )


@router.api_route(
    "/v1/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def v1_proxy(request: Request, path: str):
    target = f"{HERMES_BASE}/v1/{path}"
    return await _proxy(target, request)


@router.api_route(
    "/v1",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def v1_root(request: Request):
    return await _proxy(f"{HERMES_BASE}/v1", request)


@router.api_route(
    "/health/{path:path}",
    methods=["GET", "POST", "HEAD"],
)
async def health_proxy(request: Request, path: str):
    target = f"{HERMES_BASE}/health/{path}"
    return await _proxy(target, request)


@router.api_route(
    "/hermes/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def hermes_proxy(request: Request, path: str):
    """Catch-all for any other /hermes/* endpoints (e.g. /hermes/v1/chat/completions)."""
    target = f"{HERMES_BASE}/{path}"
    return await _proxy(target, request)