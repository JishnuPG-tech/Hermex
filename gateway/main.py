import os
import glob
import time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, Response

from gateway.anthropic_bridge import router as anthropic_router
from gateway.v1_sessions import router as v1_sessions_router
from gateway.hermes_proxy import router as hermes_proxy_router
from gateway.omniroute import router as omniroute_router
from gateway.ignis import router as ignis_router
from gateway.claude_rest_api import router as claude_rest_router
from gateway.telemetry import router as telemetry_router
from gateway.webui_api import router as webui_router

app = FastAPI(
    title="Hermes Agent Space Gateway",
    description="OmniRoute + Ignis + Hermes unified gateway.",
    docs_url=None,
    redoc_url=None,
)

@app.middleware("http")
async def normalize_hermes_paths(request: Request, call_next):
    # 1. Normalize duplicate slashes (e.g. /hermes//api -> /hermes/api)
    path = request.scope.get("path", "")
    import re
    cleaned_path = re.sub(r"/+", "/", path)

    # 2. If request starts with /hermes/api, /hermes/bootstrap, /hermes/account, /hermes/organizations
    # strip the leading /hermes prefix so it routes to the Claude REST API router
    # (Do NOT strip /hermes/v1/messages or /hermes/v1/models which belong to anthropic_bridge)
    if cleaned_path.startswith("/hermes/api/") or cleaned_path == "/hermes/api":
        cleaned_path = cleaned_path[len("/hermes"):]
    elif cleaned_path.startswith("/hermes/bootstrap"):
        cleaned_path = cleaned_path[len("/hermes"):]
    elif cleaned_path.startswith("/hermes/account"):
        cleaned_path = cleaned_path[len("/hermes"):]
    elif cleaned_path.startswith("/hermes/organizations"):
        cleaned_path = cleaned_path[len("/hermes"):]
    elif cleaned_path.startswith("/hermes/mobile"):
        cleaned_path = cleaned_path[len("/hermes"):]
    elif cleaned_path.startswith("/hermes/v1/code") or cleaned_path.startswith("/hermes/v1/sessions") or cleaned_path.startswith("/hermes/v1/b"):
        cleaned_path = cleaned_path[len("/hermes"):]
    elif cleaned_path.startswith("/hermes/code"):
        cleaned_path = cleaned_path[len("/hermes"):]
    elif cleaned_path.startswith("/hermes/telemetry") or cleaned_path.startswith("/hermes/live-logs") or cleaned_path.startswith("/hermes/ws"):
        cleaned_path = cleaned_path[len("/hermes"):]
    elif cleaned_path.startswith("/hermes/artifacts"):
        cleaned_path = cleaned_path[len("/hermes"):]

    request.scope["path"] = cleaned_path
    return await call_next(request)

# Order matters: exact routes BEFORE catch-all proxy
app.include_router(telemetry_router)
app.include_router(anthropic_router)
app.include_router(v1_sessions_router)  # v1 Sessions & Code API - MUST be before hermes_proxy catch-all
# Additive Hermex/WebUI surface. Keep this before legacy /api/models aliases.
app.include_router(webui_router)
app.include_router(claude_rest_router)
app.include_router(omniroute_router)
app.include_router(ignis_router)
app.include_router(hermes_proxy_router)  # Catch-all proxy for /v1/* and /health/*

@app.on_event("startup")
async def on_startup():
    try:
        from gateway.background_agent import start_all_saved_jobs
        start_all_saved_jobs()
    except Exception as e:
        print(f"Error starting background agent tasks: {e}")


# ── Root & Health ───────────────────────────────────────────────
@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return JSONResponse({
        "status": "ok",
        "service": "Hermes Agent Space",
        "components": {
            "hermes_agent": "http://127.0.0.1:8642",
            "omniroute": "http://127.0.0.1:20128",
            "ignis_obsidian": "http://127.0.0.1:8080",
        },
        "endpoints": {
            "anthropic_messages": "/hermes/v1/messages",
            "anthropic_models": "/hermes/v1/models",
            "openai_chat": "/v1/chat/completions",
            "openai_models": "/v1/models",
            "dashboard": "/dashboard",
            "obsidian": "/obsidian",
            "logs": "/logs",
            "health": "/health/live",
        },
    })


@app.api_route("/health/live", methods=["GET", "HEAD"])
async def health_live():
    return JSONResponse({"status": "alive"})


@app.api_route("/health", methods=["GET", "HEAD"])
async def health_check():
    services = {}
    import httpx
    client = httpx.AsyncClient(timeout=3.0)
    checks = {
        "hermes": "http://127.0.0.1:8642/health",
        "omniroute": "http://127.0.0.1:20128/api/monitoring/health",
        "ignis": "http://127.0.0.1:8080/obsidian/health",
    }
    for name, url in checks.items():
        try:
            r = await client.get(url)
            services[name] = {"status": "ok", "code": r.status_code}
        except Exception as e:
            services[name] = {"status": "starting", "message": str(e)}
    await client.aclose()
    return JSONResponse({"gateway": "healthy", "upstreams": services})


# ── PWA Manifest & Static Assets ───────────────────────────────
@app.api_route("/manifest.json", methods=["GET", "HEAD"])
@app.api_route("/manifest.webmanifest", methods=["GET", "HEAD"])
@app.api_route("/site.webmanifest", methods=["GET", "HEAD"])
async def webmanifest():
    return JSONResponse({
        "name": "Hermes Agent Space",
        "short_name": "Hermes",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0f172a",
        "theme_color": "#0f172a",
        "icons": [{"src": "/static/favicon.png", "sizes": "192x192", "type": "image/png"}],
    })


@app.api_route("/favicon.ico", methods=["GET", "HEAD"])
@app.api_route("/favicon.png", methods=["GET", "HEAD"])
@app.api_route("/static/favicon.png", methods=["GET", "HEAD"])
@app.api_route("/static/favicon.ico", methods=["GET", "HEAD"])
async def favicon():
    return Response(content=b"", status_code=204)


# ── Live Runtime Log Inspector ──────────────────────────────────
LOG_FILES = {
    "gateway": "/data/cache/gateway.log",
    "hermes": "/data/cache/hermes.log",
    "omniroute": "/data/cache/omniroute.log",
    "ignis": "/data/cache/ignis.log",
}


@app.api_route("/logs", methods=["GET", "HEAD"])
async def logs_viewer():
    html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Live Logs</title>
<meta http-equiv="refresh" content="5">
<style>
body{font-family:monospace;background:#0d1117;color:#c9d1d9;margin:0;padding:16px}
h1{color:#58a6ff;font-size:1.2rem;margin:0 0 12px}
.log{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px;margin:8px 0;max-height:400px;overflow-y:auto;white-space:pre-wrap;font-size:0.8rem;line-height:1.4}
.label{color:#8b949e;font-size:0.75rem;margin-bottom:4px}
.ok{color:#3fb950}.warn{color:#d29922}.err{color:#f85149}
</style></head><body>
<h1>Live Container Logs (auto-refresh 5s)</h1>
"""
    for name, path in LOG_FILES.items():
        content = ""
        status = "ok"
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                    import html as html_lib; content = html_lib.escape("".join(lines[-80:]))
            else:
                content = "(log file not yet created)"
                status = "warn"
        except Exception as e:
            content = f"(error reading: {e})"
            status = "err"
        html += f'<div class="label">{name.upper()} — {path} <span class="{status}">[{status}]</span></div>'
        html += f'<div class="log">{content}</div>\n'
    html += "</body></html>"
    return HTMLResponse(content=html)


@app.api_route("/logs/{service}", methods=["GET", "HEAD"])
async def logs_service(service: str):
    path = LOG_FILES.get(service)
    if not path:
        return JSONResponse({"error": f"Unknown service: {service}. Valid: {list(LOG_FILES.keys())}"}, status_code=404)
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                content = "".join(lines[-200:])
        else:
            content = "(log file not yet created)"
    except Exception as e:
        content = f"(error: {e})"
    return HTMLResponse(f"<pre style='font-family:monospace;background:#0d1117;color:#c9d1d9;padding:16px'>{content}</pre>")

@app.on_event("startup")
async def on_startup():
    try:
        from gateway import channels_manager
        await channels_manager.start_all_channels()
    except Exception as e:
        print(f"Error starting channels manager: {e}")

@app.on_event("shutdown")
async def on_shutdown():
    try:
        from gateway import channels_manager
        await channels_manager.stop_all_channels()
    except Exception as e:
        pass

# ── Catch-all proxy -> Hermes agent ─────────────────────────────
app.include_router(hermes_proxy_router)

