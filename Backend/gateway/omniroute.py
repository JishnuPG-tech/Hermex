"""
OmniRoute Router — proxies dashboard, API, and WebSocket to OmniRoute.
Referer-aware: requests from /dashboard, /login, /omniroute → :20128 (dashboard)
Everything else → :20128 (unified, Turbopack standalone build).
Routes: /dashboard/*, /omniroute/*, /v1/*, /v1beta/*, /live-ws, /_next/*
"""
import os
import re
from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import JSONResponse
from gateway.utils import proxy_http_request, proxy_websocket_stream

router = APIRouter(tags=["OmniRoute"])

# OmniRoute Turbopack standalone: dashboard + API unified on :20128
OMNIROUTE_PORT = int(os.getenv("OMNIROUTE_PORT", "20128"))
OMNIROUTE_WS_PORT = int(os.getenv("OMNIROUTE_WS_PORT", "20132"))
OMNIROUTE_EMBED_PORT = int(os.getenv("OMNIROUTE_EMBED_PORT", "20131"))

MASTER_KEY = (
    os.getenv("OMNIROUTE_API_KEY")
    or os.getenv("API_SERVER_KEY")
    or os.getenv("INITIAL_PASSWORD")
    or os.getenv("API_KEY_SECRET")
    or "sk-2e556e0437ee2958-7baf2d-b4133935"
)

# Referer paths that indicate a dashboard-originating request
DASHBOARD_REFERER_PREFIXES = (
    "/dashboard", "/login", "/omniroute", "/setup",
    "/providers", "/connections", "/settings", "/keys", "/stats", "/logs",
)


def _is_dashboard_referer(request: Request) -> bool:
    """Check if the HTTP Referer originates from OmniRoute dashboard UI."""
    referer = request.headers.get("referer", "")
    if not referer:
        return False
    for prefix in DASHBOARD_REFERER_PREFIXES:
        if f"/{prefix.lstrip('/')}" in referer or referer.endswith(prefix):
            return True
    return False


def fixup_omniroute_html(html: str) -> str:
    """Rewrite Next.js root-relative URLs for /omniroute/ prefix."""
    html = html.replace('href="/', 'href="/omniroute/')
    html = html.replace("href='/", "href='/omniroute/")
    html = html.replace('src="/', 'src="/omniroute/')
    html = html.replace("src='/", "src='/omniroute/")
    html = html.replace('action="/', 'action="/omniroute/')
    html = html.replace('/omniroute/omniroute', '/omniroute')
    if "<head>" in html:
        js_patch = """<script>
(function() {
  var origFetch = window.fetch;
  window.fetch = function(resource, init) {
    if (typeof resource === 'string' && resource.startsWith('/') && !resource.startsWith('/omniroute') && !resource.startsWith('/_next')) {
      resource = '/omniroute' + resource;
    }
    return origFetch.call(this, resource, init);
  };
  var origOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url) {
    if (typeof url === 'string' && url.startsWith('/') && !url.startsWith('/omniroute') && !url.startsWith('/_next')) {
      url = '/omniroute' + url;
    }
    return origOpen.apply(this, arguments);
  };
})();
</script>"""
        html = html.replace("<head>", f"<head>{js_patch}", 1)
    return html


OMNIROUTE_BASE_URL = os.getenv("OMNIROUTE_BASE_URL", "https://jishnupg-opencode-cli.hf.space/v1").rstrip("/")

async def handle_omniroute_proxy(request: Request, path: str, html_fixup=None):
    """Dispatch to OmniRoute with Referer-aware routing."""
    req_path = request.url.path

    # Check if this is an API call (e.g. /v1/chat/completions, /v1/models, /v1beta/...)
    is_api_call = (
        req_path.startswith("/v1/")
        or req_path.startswith("/api/v1/")
        or req_path.startswith("/v1beta/")
        or req_path in ("/v1", "/api/v1", "/v1beta")
    )

    if is_api_call:
        subpath = req_path
        if subpath.startswith("/api/v1"):
            subpath = subpath[len("/api"):]
        if not subpath.startswith("/v1") and not subpath.startswith("/v1beta"):
            subpath = "/v1" + subpath
        
        base_clean = OMNIROUTE_BASE_URL[:-3] if OMNIROUTE_BASE_URL.endswith("/v1") else OMNIROUTE_BASE_URL
        target = f"{base_clean}{subpath}"
    else:
        target = f"http://127.0.0.1:{OMNIROUTE_PORT}{req_path}"

    extra_auth = {"Authorization": f"Bearer {MASTER_KEY}"}
    return await proxy_http_request(target, request, extra_headers=extra_auth, html_fixup=html_fixup)


# ── Dashboard routes ────────────────────────────────────────────
@router.api_route("/dashboard", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/dashboard/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/home", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/home/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/login", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/login/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/setup", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/setup/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/providers", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/providers/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/connections", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/connections/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/settings", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/settings/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/keys", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/keys/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/stats", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/stats/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
# @router.api_route("/logs")
# @router.api_route("/logs/{path:path}")
@router.api_route("/_next/{path:path}", methods=["GET", "POST", "HEAD", "OPTIONS"])
async def omniroute_dashboard(request: Request, path: str = ""):
    return await handle_omniroute_proxy(request, path, html_fixup=fixup_omniroute_html)


# ── API routes ──────────────────────────────────────────────────
@router.api_route("/v1", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/api/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def omniroute_v1(request: Request, path: str = ""):
    return await handle_omniroute_proxy(request, path)


# ── Gemini API ──────────────────────────────────────────────────
@router.api_route("/v1beta", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/v1beta/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def omniroute_v1beta(request: Request, path: str = ""):
    return await handle_omniroute_proxy(request, path)


# ── Provider management (Referer-aware) ────────────────────────
@router.api_route("/api/providers/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/api/providers", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def omniroute_providers(request: Request, path: str = ""):
    return await handle_omniroute_proxy(request, path)


@router.api_route("/api/monitoring/{path:path}", methods=["GET", "POST", "HEAD", "OPTIONS"])
async def omniroute_monitoring(request: Request, path: str = ""):
    return await handle_omniroute_proxy(request, path)


@router.api_route("/api/sessions/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS"])
async def omniroute_sessions(request: Request, path: str = ""):
    return await handle_omniroute_proxy(request, path)


@router.api_route("/api/usage/{path:path}", methods=["GET", "POST", "HEAD", "OPTIONS"])
async def omniroute_usage(request: Request, path: str = ""):
    return await handle_omniroute_proxy(request, path)


# ── WebSocket telemetry ─────────────────────────────────────────
@router.websocket("/live-ws")
async def omniroute_ws(websocket: WebSocket):
    target_ws = f"ws://127.0.0.1:{OMNIROUTE_WS_PORT}/live-ws"
    await proxy_websocket_stream(websocket, target_ws)


@router.websocket("/embed-ws")
async def omniroute_embed_ws(websocket: WebSocket):
    target_ws = f"ws://127.0.0.1:{OMNIROUTE_EMBED_PORT}/embed-ws"
    await proxy_websocket_stream(websocket, target_ws)

