import os
import asyncio

import httpx
import aiohttp
from fastapi import Request, Response, WebSocket
from fastapi.responses import StreamingResponse

PUBLIC_HOST = os.getenv("PUBLIC_HOST", "jishnupg-hermes.hf.space")

IGNIS_PORT = int(os.getenv("IGNIS_PORT", "8080"))

_http_client = None


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=300.0, write=300.0, pool=30.0),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=500, max_keepalive_connections=100, keepalive_expiry=30.0),
        )
    return _http_client


_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
    "content-length", "content-encoding",
}


from urllib.parse import urlparse

def build_upstream_headers(request: Request, extra_headers=None, target_url=None) -> dict:
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP and k.lower() not in ("host", "user-agent")
    }
    if target_url and target_url.startswith("http"):
        parsed = urlparse(target_url)
        headers["Host"] = parsed.netloc
    else:
        headers["Host"] = PUBLIC_HOST
    headers["X-Forwarded-Host"] = PUBLIC_HOST
    headers["X-Forwarded-Proto"] = "https"
    headers["X-Forwarded-Port"] = "443"
    headers["User-Agent"] = request.headers.get("user-agent") or "HermesSpace-Gateway/1.0"
    if extra_headers:
        for ek, ev in extra_headers.items():
            for existing in list(headers.keys()):
                if existing.lower() == ek.lower():
                    del headers[existing]
            headers[ek] = ev
    return headers


async def proxy_http_request(target_url, request, extra_headers=None, html_fixup=None):
    client = get_http_client()
    headers = build_upstream_headers(request, extra_headers, target_url=target_url)
    body = await request.body()
    req = client.build_request(
        method=request.method,
        url=target_url,
        headers=headers,
        params=dict(request.query_params),
        content=body,
    )
    resp = await client.send(req, stream=True)

    content_type = resp.headers.get("content-type", "")
    is_stream = (
        "text/event-stream" in content_type
        or "video/" in content_type
        or "audio/" in content_type
        or resp.headers.get("transfer-encoding") == "chunked"
    )

    # Filter hop-by-hop headers but keep as strings
    filtered_headers = {
        k: v for k, v in resp.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }

    if is_stream:
        async def stream_generator():
            try:
                async for chunk in resp.aiter_bytes():
                    yield chunk
            finally:
                await resp.aclose()

        streaming = StreamingResponse(
            stream_generator(),
            status_code=resp.status_code,
            media_type=content_type or None,
            headers=filtered_headers,
        )
        return streaming

    content = await resp.aread()
    await resp.aclose()

    if html_fixup and "text/html" in content_type:
        try:
            text = content.decode("utf-8", errors="replace")
            text = html_fixup(text)
            content = text.encode("utf-8")
        except Exception:
            pass

    return Response(
        content=content,
        status_code=resp.status_code,
        media_type=content_type or None,
        headers=filtered_headers,
    )


async def proxy_websocket_stream(websocket: WebSocket, target_ws_url: str):
    await websocket.accept()

    query_string = websocket.scope.get("query_string", b"").decode("utf-8")
    if query_string:
        sep = "&" if "?" in target_ws_url else "?"
        target_ws_url = f"{target_ws_url}{sep}{query_string}"

    skip_headers = {"host", "sec-websocket-key", "sec-websocket-version", "sec-websocket-extensions"}
    forward_headers = {k: v for k, v in websocket.headers.items() if k.lower() not in skip_headers}
    forward_headers["Host"] = PUBLIC_HOST
    forward_headers["X-Forwarded-Host"] = PUBLIC_HOST
    forward_headers["X-Forwarded-Proto"] = "https"
    forward_headers["X-Forwarded-Port"] = "443"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(target_ws_url, headers=forward_headers) as upstream_ws:
                async def downstream_to_upstream():
                    async for msg in upstream_ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await websocket.send_text(msg.data)
                        elif msg.type == aiohttp.WSMsgType.BINARY:
                            await websocket.send_bytes(msg.data)
                        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                            break

                async def upstream_to_downstream():
                    while True:
                        try:
                            msg = await websocket.receive()
                            if "text" in msg:
                                await upstream_ws.send_str(msg["text"])
                            elif "bytes" in msg:
                                await upstream_ws.send_bytes(msg["bytes"])
                            elif msg.get("type") == "websocket.disconnect":
                                break
                        except Exception:
                            break

                await asyncio.gather(downstream_to_upstream(), upstream_to_downstream(), return_exceptions=True)
    except Exception:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
