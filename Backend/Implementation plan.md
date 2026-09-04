Complete Project Summary: Hermes Agent Space
What This Project Is
A single HuggingFace Space (jishnupg-hermes.hf.space) that runs three AI services behind one public port, connected to a patched Claude Android APK that thinks it is talking to Anthropic's real servers.
Claude Android App → https://jishnupg-hermes.hf.space/hermes/v1/messages
                              │
                         [Nginx :7860]
                              │
                         [FastAPI :8000]
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         Hermes :8642    OmniRoute :20128   Ignis :8080
         (Agent Core)    (LLM Router)      (Obsidian)
              │               │
              ▼               ▼
         OpenAI API     290+ Cloud LLMs
         (fallback)     (OpenAI/Anthropic/Gemini/DeepSeek/etc.)
What Was Done (In Order)
Phase 1: Claude APK Reverse Engineering
The official Claude Android APK (com.anthropic.claude v1.260721.20) was reverse-engineered using apktool to understand how it communicates with Anthropic's servers.
What was found:
- The app uses Anthropic Messages API format (not OpenAI format)
- It sends POST /v1/messages with { "model": "...", "messages": [...], "stream": true }
- It expects SSE responses: message_start → content_block_delta → message_stop
- It has dual-layer auth: Legacy GMS Google Sign-In + modern Credential Manager
- Network config in network_security_config.xml controls cert trust
- OkHttp3 + Cronet (HTTP/3 QUIC) is the transport stack
What was patched:
- network_security_config.xml — added <certificates src="user" /> to trust user CA certs (enables mitmproxy)
- Base URL redirected from api.anthropic.com to jishnupg-hermes.hf.space
- Bearer token auth injected (sk-2e556e0437ee2958-7baf2d-b4133935)
- APK rebuilt, zipaligned, debug-signed → Claude_hermes_v1_patched_final_aligned_signed.apk
Key smali files mapped:
File	Purpose
btg.smali	OkHttp interceptor — all Anthropic request headers
dl5.smali	Cronet engine — QUIC hints (cosmetic, not routing)
kr7.smali	API client config — validates ApiKey
akk.smali	Legacy Google Sign-In
eq0.smali	Modern Credential Manager
Phase 2: Protocol Bridge (Anthropic ↔ OpenAI)
Problem discovered: Claude app sends Anthropic format, but the backend returns OpenAI format. The app crashes or shows errors.
Solution: hermes_anthropic_bridge.py — a FastAPI bridge that:
1. Receives Anthropic-format POST /hermes/v1/messages
2. Translates messages to OpenAI format
3. Calls upstream LLM (Hermes agent or OmniRoute)
4. Translates OpenAI response back to proper Anthropic SSE stream
5. Sends keep-alive heartbeats every 7 seconds (prevents OkHttp timeout)
Verified end-to-end: POST /hermes/v1/messages → correct Anthropic SSE stream with real LLM reply in 5-9 seconds.
Phase 3: Hermes Space Architecture
The Hermes Space (jishnupg-hermes.hf.space) was built with:
Service	Port	Purpose
Nginx	:7860	Public HTTPS edge (single port)
FastAPI Gateway	:8000	Routing + Anthropic bridge
Hermes Agent	:8642	Autonomous AI agent (tool-calling, memory, skills)
Hermes Agent features:
- OpenAI-compatible API at /v1/chat/completions
- Persistent memory (MEMORY.md, USER.md)
- Custom skills (skills/)
- SQLite FTS5 conversation archives
- 15-second rsync persistence daemon to /data/hermes/
Phase 4: Adding OmniRoute + Ignis (Current Work)
Added two new services to the Hermes Space:
OmniRoute AI Gateway (:20128 dashboard, :20129 API):
- Multi-provider load balancer across 290+ LLM providers
- RTK + Caveman token compression (15-95% reduction)
- Quota-share auto-fallback cascade (429 failover)
- OAuth provider management
- Live telemetry WebSocket
Ignis (Obsidian) (:8080):
- Headless vault manager for markdown knowledge bases
- File CRUD (read/write/delete)
- Vault creation with auto-generated folder structure
- LiveSync WebSocket for real-time note propagation
- Vault zip export
Claude APK Mock REST API (in FastAPI):
- /api/bootstrap/{org_id}/app_start — app initialization
- /api/account — user profile
- /api/organizations — org listing
- /api/organizations/{org_id}/chat_conversations — conversation history
- /api/organizations/{org_id}/chat_conversations/{chat_id}/completion — internal SSE
- /api/organizations/{org_id}/chat_conversations/{chat_id}/title — title generation
- /api/organizations/{org_id}/chat_conversations/{chat_id}/stop_response — cancellation
Complete File Inventory
hermes_space/
├── Dockerfile                    # Multi-stage: OmniRoute + Python + Node.js + nginx
├── entrypoint.sh                 # Starts 4 services + supervisor loop
├── nginx.conf                    # :7860 → :8000
├── README.md                     # HF Space metadata
├── .env.example                  # Environment template
├── ignis/
│   ├── package.json              # express + ws + archiver
│   └── server.js                 # Obsidian vault server :8080
├── gateway/
│   ├── __init__.py               # Exports FastAPI app
│   ├── main.py                   # Mounts all 5 routers
│   ├── anthropic_bridge.py       # Anthropic SSE ↔ OpenAI translation
│   ├── hermes_proxy.py           # /v1/* → Hermes :8642
│   ├── omniroute.py              # /dashboard, /v1/*, /live-ws → OmniRoute
│   ├── ignis.py                  # /obsidian/*, /vault/*, /ws → Ignis
│   ├── cla
+ Thought: 2.9s
Here is the complete project summary, continuing from where you left off:
Complete Project Summary: Hermes Agent Space
What This Project Is
A single HuggingFace Space (jishnupg-hermes.hf.space) running three AI services behind one public port, connected to a patched Claude Android APK that thinks it is talking to Anthropic's real servers.
Claude Android App → https://jishnupg-hermes.hf.space/hermes/v1/messages
                              │
                         [Nginx :7860]
                              │
                         [FastAPI :8000]
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         Hermes :8642    OmniRoute :20128   Ignis :8080
         (Agent Core)    (LLM Router)      (Obsidian)
              │               │
              ▼               ▼
         OpenAI API     290+ Cloud LLMs
         (fallback)     (OpenAI/Anthropic/Gemini/DeepSeek/etc.)
What Was Done (In Order)
Phase 1: Claude APK Reverse Engineering
The official Claude Android APK (com.anthropic.claude v1.260721.20) was reverse-engineered using apktool to understand how it communicates with Anthropic's servers.
What was found:
- The app uses Anthropic Messages API format (not OpenAI format)
- It sends POST /v1/messages with { "model": "...", "messages": [...], "stream": true }
- It expects SSE responses: message_start → content_block_delta → message_stop
- It has dual-layer auth: Legacy GMS Google Sign-In + modern Credential Manager
- Network config in network_security_config.xml controls cert trust
- OkHttp3 + Cronet (HTTP/3 QUIC) is the transport stack
What was patched:
- network_security_config.xml — added <certificates src="user" /> to trust user CA certs (enables mitmproxy)
- Base URL redirected from api.anthropic.com to jishnupg-hermes.hf.space
- Bearer token auth injected (sk-2e556e0437ee2958-7baf2d-b4133935)
- APK rebuilt, zipaligned, debug-signed → Claude_hermes_v1_patched_final_aligned_signed.apk
Key smali files mapped:
File	Purpose
btg.smali	OkHttp interceptor — all Anthropic request headers
dl5.smali	Cronet engine — QUIC hints (cosmetic, not routing)
kr7.smali	API client config — validates ApiKey
akk.smali	Legacy Google Sign-In
eq0.smali	Modern Credential Manager
Phase 2: Protocol Bridge (Anthropic ↔ OpenAI)
Problem discovered: Claude app sends Anthropic format, but the backend returns OpenAI format. The app crashes or shows errors.
Solution: hermes_anthropic_bridge.py — a FastAPI bridge that:
1. Receives Anthropic-format POST /hermes/v1/messages
2. Translates messages to OpenAI format
3. Calls
+ Thought: 401ms
Complete Project Summary: Hermes Agent Space
What This Project Is
A single HuggingFace Space (jishnupg-hermes.hf.space) running three AI services behind one public port, connected to a patched Claude Android APK that thinks it is talking to Anthropic's real servers.
Claude Android App → https://jishnupg-hermes.hf.space/hermes/v1/messages
                              │
                         [Nginx :7860]
                              │
                         [FastAPI :8000]
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         Hermes :8642    OmniRoute :20128   Ignis :8080
         (Agent Core)    (LLM Router)      (Obsidian)
              │               │
              ▼               ▼
         OpenAI API     290+ Cloud LLMs
         (fallback)     (OpenAI/Anthropic/Gemini/DeepSeek/etc.)
What Was Done (In Order)
Phase 1: Claude APK Reverse Engineering
The official Claude Android APK (com.anthropic.claude v1.260721.20) was reverse-engineered using apktool to understand how it communicates with Anthropic's servers.
What was found:
- The app uses Anthropic Messages API format (not OpenAI format)
- It sends POST /v1/messages with { "model": "...", "messages": [...], "stream": true }
- It expects SSE responses: message_start → content_block_delta → message_stop
- It has dual-layer auth: Legacy GMS Google Sign-In + modern Credential Manager
- Network config in network_security_config.xml controls cert trust
- OkHttp3 + Cronet (HTTP/3 QUIC) is the transport stack
What was patched:
- network_security_config.xml — added <certificates src="user" /> to trust user CA certs (enables mitmproxy)
- Base URL redirected from api.anthropic.com to jishnupg-hermes.hf.space
- Bearer token auth injected (sk-2e556e0437ee2958-7baf2d-b4133935)
- APK rebuilt, zipaligned, debug-signed → Claude_hermes_v1_patched_final_aligned_signed.apk
Key smali files mapped:
File	Purpose
btg.smali	OkHttp interceptor — all Anthropic request headers
dl5.smali	Cronet engine — QUIC hints (cosmetic, not routing)
kr7.smali	API client config — validates ApiKey
akk.smali	Legacy Google Sign-In
eq0.smali	Modern Credential Manager
Phase 2: Protocol Bridge (Anthropic ↔ OpenAI)
Problem discovered: Claude app sends Anthropic format, but the backend returns OpenAI format. The app crashes or shows errors.
Solution: hermes_anthropic_bridge.py — a FastAPI bridge that:
1. Receives Anthropic-format POST /hermes/v1/messages
2. Translates messages to OpenAI format
3. Calls upstream LLM (Hermes agent or OmniRoute)
4. Translates OpenAI response back to proper Anthropic SSE stream
5. Sends keep-alive heartbeats every 7 seconds (prevents OkHttp timeout)
SSE event flow:
event: message_start
data: {"type":"message_start","message":{"id":"msg_xxx","role":"assistant","content":[],"model":"claude-sonnet-4-20250514","stop_reason":null,"usage":{"input_tokens":0,"output_tokens":0}}}

event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":" there!"}}

event: content_block_stop
data: {"type":"content_block_stop","index":0}

event: message_delta
data: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},"usage":{"output_tokens":15}}

event: message_stop
data: {"type":"message_stop"}
Verified end-to-end: POST /hermes/v1/messages → correct Anthropic SSE stream with real LLM reply in 5-9 seconds.
Phase 3: Hermes Space Architecture
The Hermes Space (jishnupg-hermes.hf.space) was built with:
Service	Port
Nginx	:7860
FastAPI Gateway	:8000
Hermes Agent	:8642
Hermes Agent features:
- OpenAI-compatible API at /v1/chat/completions
- Persistent memory (MEMORY.md, USER.md)
- Custom skills (skills/)
- SQLite FTS5 conversation archives
- 15-second rsync persistence daemon to /data/hermes/
Phase 4: Adding OmniRoute + Ignis
Added two new services to the Hermes Space:
OmniRoute AI Gateway (:20128 dashboard, :20129 API):
- Multi-provider load balancer across 290+ LLM providers
- RTK + Caveman token compression (15-95% reduction)
- Quota-share auto-fallback cascade (429 failover)
- OAuth provider management
- Live telemetry WebSocket
Ignis (Obsidian) (:8080):
- Headless vault manager for markdown knowledge bases
- File CRUD (read/write/delete)
- Vault creation with auto-generated folder structure
- LiveSync WebSocket for real-time note propagation
- Vault zip export
Claude APK Mock REST API (in FastAPI):
- /api/bootstrap/{org_id}/app_start — app initialization
- /api/account — user profile
- /api/organizations — org listing
- /api/organizations/{org_id}/chat_conversations — conversation history
- /api/organizations/{org_id}/chat_conversations/{chat_id}/completion — internal SSE
- /api/organizations/{org_id}/chat_conversations/{chat_id}/title — title generation
- /api/organizations/{org_id}/chat_conversations/{chat_id}/stop_response — cancellation
Complete File Inventory
hermes_space/
├── Dockerfile                    # Multi-stage: OmniRoute + Python + Node.js + nginx
├── entrypoint.sh                 # Starts 4 services + supervisor loop
├── nginx.conf                    # :7860 → :8000
├── README.md                     # HF Space metadata
├── .env.example                  # Environment template
├── ignis/
│   ├── package.json              # express + ws + archiver
│   └── server.js                 # Obsidian vault server :8080
├── gateway/
│   ├── __init__.py               # Exports FastAPI app
│   ├── main.py                   # Mounts all 5 routers
│   ├── anthropic_bridge.py       # Anthropic SSE ↔ OpenAI translation
│   ├── hermes_proxy.py           # /v1/* → Hermes :8642
│   ├── omniroute.py              # /dashboard, /v1/*, /live-ws → OmniRoute
│   ├── ignis.py                  # /obsidian/*, /vault/*, /ws → Ignis
│   ├── claude_rest_api.py        # /api/bootstrap/*, /api/account (mock)
│   └── utils.py                  # HTTP proxy + WebSocket proxy + html_fixup
Complete Endpoint Map
Claude APK Endpoints (Anthropic Format)
Method	Endpoint
POST	/hermes/v1/messages
GET	/hermes/v1/models
GET	/api/bootstrap/{org_id}/app_start
GET	/api/account
GET	/api/organizations
GET	/api/organizations/{org_id}/chat_conversations
GET	/api/organizations/{org_id}/chat_conversations/{chat_id}
POST	/api/organizations/{org_id}/chat_conversations/{chat_id}/completion
POST	/api/organizations/{org_id}/chat_conversations/{chat_id}/title
POST	/api/organizations/{org_id}/chat_conversations/{chat_id}/stop_response
OmniRoute Endpoints (OpenAI Format)
Method	Endpoint
POST	/v1/chat/completions
GET	/v1/models
POST	/v1beta/models/{model}:generateContent
POST	/v1beta/models/{model}:streamGenerateContent
GET	/dashboard/*
WS	/live-ws
GET	/api/providers/*
Ignis (Obsidian) Endpoints
Method	Endpoint
GET	/obsidian
GET	/api/vaults
POST	/api/vaults/create
GET	/api/files/:vault/*
POST	/api/files/:vault/*
DELETE	/api/files/:vault/*
GET	/api/vaults/:vault/zip
GET	/api/bootstrap/:vault
WS	/ws
WS	/obsidian/ws
Hermes Endpoints
Method	Endpoint
POST	/v1/chat/completions
GET	/v1/models
GET	/health
Request Flow (End-to-End)
1. User opens patched Claude APK
2. App sends GET /api/bootstrap/personal/app_start
   → Returns: user uuid, org capabilities ["pro"], model list
3. App sends GET /api/organizations/personal/chat_conversations
   → Returns: conversation history array
4. User types message
5. App sends POST /hermes/v1/messages
   Headers: Authorization: Bearer sk-2e556e0437ee2958-7baf2d-b4133935
            Anthropic-Version: 2023-06-01
            Anthropic-Beta: ccr-byoc-2025-07-29
   Body: {"model":"claude-sonnet-4-20250514","messages":[{"role":"user","content":"Hello"}],"stream":true}
6. Nginx :7860 → FastAPI :8000
7. anthropic_bridge.py receives request
8. translate_to_openai() converts to OpenAI format
9. Calls Hermes agent :8642 or OmniRoute :20129
10. LLM generates response
11. translate_to_anthropic_sse() converts back to Anthropic SSE
12. 7-second keep-alive heartbeats sent during generation
13. SSE stream: message_start → content_block_delta × N → message_stop
14. Claude APK renders streaming response
Network Configuration (from Smali)
File	Line	Value
dl5.smali	66	claude.ai
dl5.smali	74	www.claude.ai
dl5.smali	80	api.anthropic.com
btg.smali	47	Anthropic-Version: 2023-06-01
btg.smali	55	Anthropic-Beta: ccr-byoc-2025-07-29
btg.smali	41	X-Organization-Uuid
btg.smali	76	X-Trusted-Device-Token
k39.smali	198	authorization
kr7.smali	831	"ApiKey must be set."
Note: api.anthropic.com in dl5.smali are QUIC connection pre-warming hints only. They do NOT control routing. Base URL was patched at HTTP client builder level.
Persistence Architecture
/data/
├── hermes/
│   ├── memories/USER.md          # User preferences
│   ├── memories/MEMORY.md        # Agent knowledge
│   ├── skills/                   # Custom agent skills
│   └── sessions/                 # SQLite FTS5 archives
├── omniroute/
│   ├── storage.sqlite            # Provider DB (290+ providers)
│   ├── oauth/                    # OAuth tokens
│   └── backups/                  # Rotating SQLite snapshots
├── vaults/                       # Obsidian markdown vaults
│   ├── Daily Notes/              # Auto-journaled logs
│   ├── Memories/                 # Distilled session memories
│   └── Archives/                 # Compacted conversations
└── cache/
    ├── hermes.log                # Hermes runtime logs
    ├── omniroute.log             # OmniRoute logs
    ├── ignis.log                 # Ignis logs
    └── gateway.log               # FastAPI gateway logs
Sync daemon: Every 15 seconds, rsync copies Hermes state and OmniRoute DB to /data/ for persistence across Space rebuilds.
Supervisor Loop
The entrypoint.sh supervisor monitors all 4 services every 5 seconds:
while true; do
    # Check Nginx
    if ! kill -0 $NGINX_PID; then restart nginx; fi
    
    # Check FastAPI
    if ! kill -0 $FASTAPI_PID; then restart uvicorn; fi
    
    # Check Hermes
    if ! kill -0 $HERMES_PID; then restart hermes gateway; fi
    
    # Check OmniRoute
    if ! kill -0 $OMNIROUTE_PID; then restart node server.js; fi
    
    # Check Ignis
    if ! kill -0 $IGNIS_PID; then restart node server.js; fi
    
    sleep 5
done
Build & Deploy
# Local development
cd "C:\Users\JISHNU PG\Pictures\Hermes\hermes_space"
docker compose up --build

# Deploy to HuggingFace Space
git init
git add .
git commit -m "OmniRoute + Ignis + Hermes unified space"
git remote add hermes https://huggingface.co/spaces/Jishnupg/Hermes
git push hermes main
Verification Commands
# Gateway health
curl https://jishnupg-hermes.hf.space/health/live

# Hermes
curl https://jishnupg-hermes.hf.space/hermes/v1/models

# OmniRoute
curl https://jishnupg-hermes.hf.space/v1/models

# Ignis
curl https://jishnupg-hermes.hf.space/api/vaults

# Claude APK bridge (SSE test)
curl -X POST https://jishnupg-hermes.hf.space/hermes/v1/messages `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer sk-2e556e0437ee2958-7baf2d-b4133935" `
  -d '{"model":"claude-sonnet-4-20250514","messages":[{"role":"user","content":"Hi"}],"stream":true}'

# Install patched APK
adb install "Claude_hermes_v1_patched_final_aligned_signed.apk"

# Monitor traffic
adb logcat | Select-String "jishnupg|anthropic|hermes"
What This Project Achieves
1. Claude APK works with custom backend — the patched app connects to your servers instead of Anthropic
2. Full agent capabilities — Hermes provides autonomous tool-calling, memory, and skills
3. Multi-provider LLM routing — OmniRoute balances across 290+ providers with automatic failover
4. Knowledge management — Ignis provides Obsidian-style markdown vaults with real-time sync
5. Single port deployment — Everything runs behind one public HTTPS endpoint
6. Persistent state — All data survives Space rebuilds via /data/ volume sync
7. Self-healing — Supervisor loop restarts any crashed service within 5 seconds
This project was built through iterative reverse engineering, protocol analysis, and systems integration across multiple conversation sessions.
Last updated: 2026-08-22