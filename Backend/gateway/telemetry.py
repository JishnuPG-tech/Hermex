import time
import json
import asyncio
import gzip
from collections import deque
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter()

# Ring buffer for recent logs (stores last 3000 log events)
LOG_BUFFER = deque(maxlen=3000)
CONNECTED_CLIENTS: List[WebSocket] = []

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        history = list(LOG_BUFFER)
        if history:
            await websocket.send_json({
                "type": "history",
                "logs": history
            })

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, log_event: Dict[str, Any]):
        dead_connections = []
        msg = {
            "type": "log",
            "log": log_event
        }
        for connection in self.active_connections:
            try:
                await connection.send_json(msg)
            except Exception:
                dead_connections.append(connection)
        for dc in dead_connections:
            self.disconnect(dc)

manager = ConnectionManager()

def push_event(tag: str, level: str, message: str, details: str = "", device: str = "Android"):
    event = {
        "id": f"log_{int(time.time()*1000)}_{len(LOG_BUFFER)}",
        "tag": tag,
        "level": level.upper(),
        "message": message,
        "details": details,
        "device": device,
        "timestamp": int(time.time() * 1000),
        "created_at": time.strftime("%H:%M:%S", time.localtime())
    }
    LOG_BUFFER.append(event)
    asyncio.create_task(manager.broadcast(event))

# ── 1. Native Claude APK Telemetry & Crash Ingestion (/v1/b) ──
@router.post("/v1/b")
@router.post("/hermes/v1/b")
@router.post("/api/event_logging")
@router.post("/hermes/api/event_logging")
@router.post("/api/eval_metrics")
@router.post("/hermes/api/eval_metrics")
async def ingest_claude_native_telemetry(request: Request):
    try:
        raw_body = await request.body()
        content_encoding = request.headers.get("content-encoding", "").lower()
        if "gzip" in content_encoding:
            try:
                raw_body = gzip.decompress(raw_body)
            except Exception:
                pass
        
        body_str = raw_body.decode("utf-8", errors="ignore")
        data = None
        try:
            data = json.loads(body_str)
        except Exception:
            pass

        if isinstance(data, list):
            for item in data:
                parse_and_push_single(item)
        elif isinstance(data, dict):
            # Might contain 'events' or 'logs' array
            if "events" in data and isinstance(data["events"], list):
                for item in data["events"]:
                    parse_and_push_single(item)
            elif "logs" in data and isinstance(data["logs"], list):
                for item in data["logs"]:
                    parse_and_push_single(item)
            elif "batch" in data and isinstance(data["batch"], list):
                for item in data["batch"]:
                    parse_and_push_single(item)
            else:
                parse_and_push_single(data)
        else:
            if body_str.strip():
                push_event("NATIVE_RAW", "INFO", body_str[:500], body_str)
    except Exception as e:
        push_event("TELEMETRY_ERROR", "ERROR", f"Error parsing payload: {e}")
    
    return JSONResponse({"status": "ok", "success": True})

def parse_and_push_single(item: Any):
    if not isinstance(item, dict):
        push_event("APP_LOG", "INFO", str(item))
        return

    # Extract tag, event name, message, error
    event_name = item.get("event") or item.get("event_name") or item.get("name") or item.get("type") or "APP_EVENT"
    level = "INFO"
    msg = item.get("message") or item.get("msg") or event_name
    
    # Detect errors
    if "error" in str(item).lower() or item.get("level") in ("error", "ERROR", "err"):
        level = "ERROR"
    elif "warn" in str(item).lower() or item.get("level") in ("warn", "WARN"):
        level = "WARN"

    details = json.dumps(item, indent=2, ensure_ascii=False) if len(item) > 2 else ""
    push_event(event_name.upper(), level, msg, details)

# ── 2. Direct Telemetry Endpoint ──
@router.post("/api/telemetry/log")
@router.post("/hermes/api/telemetry/log")
@router.post("/telemetry/log")
async def ingest_log(request: Request):
    try:
        data = await request.json()
    except Exception:
        body = await request.body()
        data = {"message": body.decode("utf-8", errors="ignore"), "tag": "RAW", "level": "INFO"}
    
    push_event(
        tag=data.get("tag", "HERMES"),
        level=data.get("level", "INFO"),
        message=data.get("message", ""),
        details=data.get("details", "")
    )
    return JSONResponse({"status": "ok"})

@router.post("/api/telemetry/batch")
@router.post("/hermes/api/telemetry/batch")
async def ingest_batch_logs(request: Request):
    try:
        items = await request.json()
        if not isinstance(items, list):
            items = [items]
    except Exception:
        items = []

    for item in items:
        parse_and_push_single(item)
        
    return JSONResponse({"status": "ok", "count": len(items)})

@router.get("/api/telemetry/history")
@router.get("/hermes/api/telemetry/history")
async def get_log_history():
    return JSONResponse({
        "status": "ok",
        "total": len(LOG_BUFFER),
        "logs": list(LOG_BUFFER)
    })

@router.delete("/api/telemetry/clear")
@router.delete("/hermes/api/telemetry/clear")
async def clear_logs():
    LOG_BUFFER.clear()
    asyncio.create_task(manager.broadcast({"type": "clear"}))
    return JSONResponse({"status": "cleared"})

@router.websocket("/ws/logs")
@router.websocket("/hermes/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

@router.get("/live-logs", response_class=HTMLResponse)
@router.get("/hermes/live-logs", response_class=HTMLResponse)
@router.get("/logs/live", response_class=HTMLResponse)
async def live_logs_page():
    return HTMLResponse(HTML_PAGE)

HTML_PAGE = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hermes APK Real-Time Diagnostic Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        brand: '#d97706',
                        darkBg: '#0b0f19',
                        panelBg: '#111827',
                        cardBg: '#1f2937'
                    },
                    fontFamily: {
                        mono: ['JetBrains Mono', 'Fira Code', 'monospace']
                    }
                }
            }
        }
    </script>
    <style>
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #0b0f19; }
        ::-webkit-scrollbar-thumb { background: #374151; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #4b5563; }
        .log-row:hover { background-color: rgba(55, 65, 81, 0.4); }
    </style>
</head>
<body class="bg-darkBg text-gray-200 font-sans h-screen flex flex-col overflow-hidden">

    <header class="bg-panelBg/90 backdrop-blur border-b border-gray-800 px-6 py-3.5 flex items-center justify-between z-20 shrink-0">
        <div class="flex items-center space-x-3">
            <div class="w-9 h-9 rounded-lg bg-gradient-to-tr from-amber-600 to-orange-500 flex items-center justify-center text-white shadow-lg shadow-orange-500/20">
                <i class="fa-solid fa-bolt text-lg"></i>
            </div>
            <div>
                <h1 class="text-base font-bold text-white flex items-center space-x-2">
                    <span>Hermes Live Log Streamer</span>
                    <span class="text-xs px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 font-mono">No-ADB Cloud Ingestion</span>
                </h1>
                <p class="text-xs text-gray-400">Capturing native telemetry (/v1/b), WebView iframe, and runtime events</p>
            </div>
        </div>

        <div class="flex items-center space-x-3">
            <div id="connectionStatus" class="flex items-center space-x-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-mono">
                <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                <span id="connText">CONNECTING...</span>
            </div>

            <div class="hidden sm:flex items-center space-x-4 bg-darkBg/60 px-4 py-1 rounded-lg border border-gray-800 text-xs font-mono">
                <div>Total: <span id="totalCount" class="text-amber-400 font-bold">0</span></div>
                <div class="text-gray-600">|</div>
                <div>EPS: <span id="epsCount" class="text-blue-400 font-bold">0</span>/s</div>
                <div class="text-gray-600">|</div>
                <div>Errors: <span id="errCount" class="text-red-400 font-bold">0</span></div>
            </div>

            <button onclick="togglePause()" id="pauseBtn" class="px-3 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-xs font-semibold border border-gray-700 transition flex items-center space-x-1.5">
                <i class="fa-solid fa-pause"></i>
                <span>Pause</span>
            </button>

            <button onclick="clearLogs()" class="px-3 py-1.5 rounded-lg bg-gray-800 hover:bg-red-950/40 text-gray-300 hover:text-red-400 text-xs font-semibold border border-gray-700 hover:border-red-500/30 transition flex items-center space-x-1.5">
                <i class="fa-solid fa-trash-can"></i>
                <span>Clear</span>
            </button>

            <button onclick="exportLogs()" class="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold shadow transition flex items-center space-x-1.5">
                <i class="fa-solid fa-download"></i>
                <span>Export</span>
            </button>
        </div>
    </header>

    <div class="bg-panelBg/60 border-b border-gray-800 px-6 py-2.5 flex flex-wrap items-center justify-between gap-3 shrink-0">
        <div class="flex items-center space-x-1.5 text-xs">
            <button onclick="setFilter('ALL')" class="filter-pill active px-3 py-1 rounded-md bg-amber-500 text-darkBg font-bold transition" data-tag="ALL">ALL</button>
            <button onclick="setFilter('ERROR')" class="filter-pill px-3 py-1 rounded-md bg-gray-800 hover:bg-gray-700 text-red-400 font-mono transition" data-tag="ERROR">ERROR</button>
            <button onclick="setFilter('WARN')" class="filter-pill px-3 py-1 rounded-md bg-gray-800 hover:bg-gray-700 text-amber-400 font-mono transition" data-tag="WARN">WARN</button>
            <button onclick="setFilter('WEBVIEW')" class="filter-pill px-3 py-1 rounded-md bg-gray-800 hover:bg-gray-700 text-cyan-400 font-mono transition" data-tag="WEBVIEW">WEBVIEW</button>
            <button onclick="setFilter('NETWORK')" class="filter-pill px-3 py-1 rounded-md bg-gray-800 hover:bg-gray-700 text-purple-400 font-mono transition" data-tag="NETWORK">NETWORK</button>
            <button onclick="setFilter('COMPOSE')" class="filter-pill px-3 py-1 rounded-md bg-gray-800 hover:bg-gray-700 text-emerald-400 font-mono transition" data-tag="COMPOSE">COMPOSE</button>
            <button onclick="setFilter('STATE')" class="filter-pill px-3 py-1 rounded-md bg-gray-800 hover:bg-gray-700 text-blue-400 font-mono transition" data-tag="STATE">STATE</button>
        </div>

        <div class="flex items-center space-x-3">
            <div class="relative">
                <i class="fa-solid fa-magnifying-glass absolute left-3 top-2.5 text-gray-500 text-xs"></i>
                <input type="text" id="searchInput" oninput="applyFilters()" placeholder="Filter logs, URLs, stack traces..." class="w-64 sm:w-80 bg-darkBg border border-gray-700 rounded-lg pl-8 pr-3 py-1.5 text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-amber-500 transition font-mono">
            </div>

            <label class="flex items-center space-x-2 text-xs text-gray-400 cursor-pointer select-none">
                <input type="checkbox" id="autoScrollCheck" checked class="rounded bg-gray-800 border-gray-700 text-amber-500 focus:ring-0">
                <span>Auto-Scroll</span>
            </label>
        </div>
    </div>

    <main id="logContainer" class="flex-1 overflow-y-auto font-mono text-xs p-4 space-y-1 bg-darkBg">
        <div id="emptyPlaceholder" class="h-full flex flex-col items-center justify-center text-gray-600">
            <i class="fa-solid fa-terminal text-4xl mb-3 text-gray-700"></i>
            <p class="text-sm font-semibold text-gray-500">Awaiting Log Stream from Hermes APK...</p>
            <p class="text-xs text-gray-600 mt-1">Logs sent from your mobile app via /v1/b, telemetry, or WebSocket will appear here lively in real-time.</p>
        </div>
        <div id="logList"></div>
    </main>

    <footer class="bg-panelBg/90 border-t border-gray-800 px-6 py-2 flex items-center justify-between text-xs text-gray-500 shrink-0 font-mono">
        <div class="flex items-center space-x-3">
            <span class="flex items-center space-x-1.5"><i class="fa-solid fa-circle text-[8px] text-emerald-400"></i><span>Endpoints: <code class="text-gray-400 font-bold">POST /v1/b</code> &bull; <code class="text-gray-400 font-bold">POST /api/telemetry/log</code></span></span>
        </div>
        <div>Hermes Diagnostic Console v2.0 • Ultra-Low Latency Engine</div>
    </footer>

    <script>
        let allLogs = [];
        let filteredLogs = [];
        let activeTag = 'ALL';
        let isPaused = false;
        let autoScroll = true;
        let eventCountLastSec = 0;
        let ws = null;

        const logList = document.getElementById('logList');
        const logContainer = document.getElementById('logContainer');
        const emptyPlaceholder = document.getElementById('emptyPlaceholder');
        const totalCountEl = document.getElementById('totalCount');
        const epsCountEl = document.getElementById('epsCount');
        const errCountEl = document.getElementById('errCount');
        const connTextEl = document.getElementById('connText');
        const connectionStatusEl = document.getElementById('connectionStatus');
        const searchInput = document.getElementById('searchInput');
        const autoScrollCheck = document.getElementById('autoScrollCheck');
        const pauseBtn = document.getElementById('pauseBtn');

        autoScrollCheck.addEventListener('change', (e) => {
            autoScroll = e.target.checked;
        });

        setInterval(() => {
            epsCountEl.innerText = eventCountLastSec;
            eventCountLastSec = 0;
        }, 1000);

        function initWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws/logs`;
            
            connTextEl.innerText = "CONNECTING...";
            connectionStatusEl.className = "flex items-center space-x-2 px-3 py-1 rounded-full bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs font-mono";

            ws = new WebSocket(wsUrl);

            ws.onopen = () => {
                connTextEl.innerText = "LIVE STREAMING";
                connectionStatusEl.className = "flex items-center space-x-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-mono";
            };

            ws.onmessage = (event) => {
                if (isPaused) return;
                try {
                    const data = JSON.parse(event.data);
                    if (data.type === 'history') {
                        allLogs = data.logs || [];
                        renderAll();
                    } else if (data.type === 'log') {
                        appendLog(data.log);
                    } else if (data.type === 'clear') {
                        allLogs = [];
                        renderAll();
                    }
                } catch (e) {
                    console.error("WS Parse Error", e);
                }
            };

            ws.onclose = () => {
                connTextEl.innerText = "RECONNECTING...";
                connectionStatusEl.className = "flex items-center space-x-2 px-3 py-1 rounded-full bg-red-500/10 border border-red-500/30 text-red-400 text-xs font-mono";
                setTimeout(initWebSocket, 2000);
            };

            ws.onerror = (e) => {
                ws.close();
            };
        }

        function appendLog(log) {
            allLogs.push(log);
            eventCountLastSec++;
            updateStats();

            if (matchesFilter(log)) {
                emptyPlaceholder.classList.add('hidden');
                const row = createLogRow(log);
                logList.appendChild(row);

                if (autoScroll) {
                    logContainer.scrollTop = logContainer.scrollHeight;
                }
            }
        }

        function createLogRow(log) {
            const div = document.createElement('div');
            div.className = "log-row flex items-start space-x-2.5 py-1 px-2.5 rounded border border-transparent hover:border-gray-800 transition";

            let levelColor = "bg-gray-800 text-gray-300 border-gray-700";
            let tagColor = "text-amber-400";
            let textColor = "text-gray-200";

            if (log.level === 'ERROR') {
                levelColor = "bg-red-500/15 text-red-400 border-red-500/30";
                textColor = "text-red-300 font-semibold";
            } else if (log.level === 'WARN') {
                levelColor = "bg-amber-500/15 text-amber-400 border-amber-500/30";
                textColor = "text-amber-200";
            } else if (log.level === 'DEBUG') {
                levelColor = "bg-blue-500/15 text-blue-400 border-blue-500/30";
            }

            if (log.tag.includes('WEBVIEW')) tagColor = "text-cyan-400";
            else if (log.tag.includes('NET')) tagColor = "text-purple-400";
            else if (log.tag.includes('COMPOSE')) tagColor = "text-emerald-400";
            else if (log.tag.includes('STATE')) tagColor = "text-blue-400";

            const timeStr = log.created_at || new Date(log.timestamp).toLocaleTimeString();

            div.innerHTML = `
                <span class="text-gray-500 shrink-0 select-none">${timeStr}</span>
                <span class="px-1.5 py-0.5 rounded text-[10px] uppercase font-bold border shrink-0 ${levelColor}">${log.level}</span>
                <span class="font-bold shrink-0 ${tagColor}">[${log.tag}]</span>
                <span class="flex-1 break-all ${textColor}">${escapeHtml(log.message)}</span>
                ${log.details ? `<div class="text-[11px] text-gray-400 w-full mt-1 bg-black/30 p-1.5 rounded border border-gray-800"><pre class="overflow-x-auto">${escapeHtml(log.details)}</pre></div>` : ''}
            `;
            return div;
        }

        function renderAll() {
            logList.innerHTML = '';
            const filtered = allLogs.filter(matchesFilter);
            if (filtered.length === 0) {
                emptyPlaceholder.classList.remove('hidden');
            } else {
                emptyPlaceholder.classList.add('hidden');
                const fragment = document.createDocumentFragment();
                filtered.forEach(log => {
                    fragment.appendChild(createLogRow(log));
                });
                logList.appendChild(fragment);
                if (autoScroll) {
                    logContainer.scrollTop = logContainer.scrollHeight;
                }
            }
            updateStats();
        }

        function matchesFilter(log) {
            if (activeTag !== 'ALL') {
                if (activeTag === 'ERROR' && log.level !== 'ERROR') return false;
                if (activeTag === 'WARN' && log.level !== 'WARN' && log.level !== 'ERROR') return false;
                if (activeTag === 'WEBVIEW' && !log.tag.includes('WEBVIEW')) return false;
                if (activeTag === 'NETWORK' && !log.tag.includes('NET')) return false;
                if (activeTag === 'COMPOSE' && !log.tag.includes('COMPOSE')) return false;
                if (activeTag === 'STATE' && !log.tag.includes('STATE')) return false;
            }

            const query = searchInput.value.trim().toLowerCase();
            if (!query) return true;

            const fullText = `${log.tag} ${log.level} ${log.message} ${log.details || ''}`.toLowerCase();
            return fullText.includes(query);
        }

        function setFilter(tag) {
            activeTag = tag;
            document.querySelectorAll('.filter-pill').forEach(btn => {
                if (btn.dataset.tag === tag) {
                    btn.className = "filter-pill active px-3 py-1 rounded-md bg-amber-500 text-darkBg font-bold transition";
                } else {
                    btn.className = "filter-pill px-3 py-1 rounded-md bg-gray-800 hover:bg-gray-700 text-gray-400 font-mono transition";
                }
            });
            renderAll();
        }

        function applyFilters() {
            renderAll();
        }

        function updateStats() {
            totalCountEl.innerText = allLogs.length;
            const errs = allLogs.filter(l => l.level === 'ERROR').length;
            errCountEl.innerText = errs;
        }

        function togglePause() {
            isPaused = !isPaused;
            if (isPaused) {
                pauseBtn.innerHTML = '<i class="fa-solid fa-play"></i><span>Resume</span>';
                pauseBtn.className = "px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold transition flex items-center space-x-1.5";
            } else {
                pauseBtn.innerHTML = '<i class="fa-solid fa-pause"></i><span>Pause</span>';
                pauseBtn.className = "px-3 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-xs font-semibold border border-gray-700 transition flex items-center space-x-1.5";
            }
        }

        function clearLogs() {
            fetch('/api/telemetry/clear', { method: 'DELETE' });
            allLogs = [];
            renderAll();
        }

        function exportLogs() {
            const blob = new Blob([JSON.stringify(allLogs, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `hermes_apk_logs_${Date.now()}.json`;
            a.click();
            URL.revokeObjectURL(url);
        }

        function escapeHtml(str) {
            if (!str) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        }

        window.onload = initWebSocket;
    </script>
</body>
</html>
"""
