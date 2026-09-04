# Hermes AI Backend & Autonomous Microservices

This directory contains the production-grade backend services for the **Hermes Platform**, combining high-performance LLM routing, autonomous server tool execution, 24/7 background task scheduling, mobile telemetry ingestion, and interactive Obsidian notes management.

---

## 🏛️ System Architecture

```text
                               ┌────────────────────────────────┐
                               │       Client Ingestion         │
                               │  (Claude Mobile / Web / App)   │
                               └───────────────┬────────────────┘
                                               │
                                               ▼
                              ┌─────────────────────────────────┐
                              │       Nginx Reverse Proxy       │
                              │ (SSL / WebSocket / Buffering)   │
                              └───────────────┬─────────────────┘
                                               │
                                               ▼
                              ┌─────────────────────────────────┐
                              │      FastAPI Hermes Gateway     │
                              │         (Port 7860/8642)        │
                              └───────┬───────────────┬─────────┘
                                      │               │
            ┌─────────────────────────┴────┐   ┌──────┴────────────────────────┐
            ▼                              ▼   ▼                               ▼
  ┌──────────────────┐    ┌─────────────────┐ ┌──────────────────┐  ┌──────────────────┐
  │  Agent Executor  │    │ 24/7 Background │ │   Ignis Server   │  │ OmniRoute Engine │
  │ (Tools / Skills) │    │  Task Daemon    │ │ (Obsidian Notes) │  │  (Multi-Provider)│
  └─────────┬────────┘    └────────┬────────┘ └──────────────────┘  └──────────────────┘
            │                      │
            ▼                      ▼
  ┌─────────────────────────────────────────┐
  │         Persistent Server Disk          │
  │  (/data/hermes/conversations & tasks)   │
  └─────────────────────────────────────────┘
```

---

## 🚀 Core Backend Modules (`gateway/`)

### 1. `claude_rest_api.py` — Native Anthropic REST API Implementation
- Implements `/api/organizations/{org}/chat_conversations/{chat_id}/completion` with live chunk-by-chunk SSE streaming.
- **Immediate State Pre-registration**: Creates assistant message placeholder nodes instantly on user prompt submission, eliminating mobile UI pending stalls.
- **Asynchronous AI Title Generator**: Automatically generates concise 3–6 word conversation titles in the background upon chat creation.

### 2. `agent_executor.py` — Universal Multi-Turn Autonomous Tool Engine
- Executes server-level capabilities:
  - `bash`: Shell execution with timeout protection and stdout/stderr capture.
  - `read_file`, `write_file`, `list_dir`: Safe filesystem access.
  - `schedule_task`, `list_background_tasks`, `stop_background_task`: 24/7 background job control.
  - `activate_skill`, `list_skills`: Dynamic domain persona activation (`python-pro`, `fastapi-pro`, `docker-expert`, `database-architect`, `security-auditor`, `systematic-debugging`).
- **Dual-Mode Multi-Turn Loop**: Seamlessly executes tool requests, streams status indicators (`*Executing bash*`), and continues reasoning until producing complete, structured markdown reports.

### 3. `background_agent.py` — 24/7 Persistent Background Daemon
- Schedules recurring autonomous tasks (cron intervals from seconds to days).
- Persists task definitions and run logs in `/data/hermes/scheduled_tasks.json`.
- Runs continuously on the server even when the user closes the mobile app.

### 4. `telemetry.py` — Live Mobile Log Streaming & Dashboard
- Ingests events from the Android APK via `/api/telemetry/log`.
- Broadcasts logs in real-time over WebSockets (`/ws/logs`) to the live dashboard webapp.

### 5. `health_doctor.py` & `clean_db.py` — Self-Healing Infrastructure
- Key-Hash Guard detects encryption key changes to prevent database corruption.
- Automated migrations and SQLite3 table repairs during container initialization.

---

## 🛠️ Local Development & Deployment

### Run Locally with Docker
```bash
docker build -t hermes-backend .
docker run -p 7860:7860 -v hermes_data:/data hermes-backend
```

### Environment Variables (`.env`)
```bash
OMNIROUTE_URL=http://127.0.0.1:20128/v1
HERMES_MODEL=auto/smart
PUBLIC_PORT=7860
DATA_DIR=/data
```
