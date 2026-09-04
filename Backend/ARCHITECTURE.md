# Hermes Enterprise Space - Architecture & Implementation Plan

## System Architecture

\\mermaid
graph TB
    subgraph External_Clients [External Clients]
        APK[Claude Android APK<br/>Patched v1.260721.20]
        WEB[Web Browser]
        TG[Telegram Bot]
    end

    subgraph HF_Space [HuggingFace Space: jishnupg-hermes.hf.space]
        NGINX[Nginx :7860<br/>Edge Gzip+Brotli<br/>WebSocket Passthrough]

        subgraph FastAPI_Gateway [FastAPI Gateway :8000]
            BRIDGE[Anthropic Bridge<br/>Anthropic SSE to OpenAI]
            CLAUDE_REST[Claude REST API<br/>/api/bootstrap/*]
            OMNIROUTE_RT[OmniRoute Router<br/>Referer-Aware]
            IGNIS_RT[Ignis Router]
            HERMES_RT[Hermes Proxy]
            LOGS[Log Inspector<br/>/logs]
        end

        subgraph Core_Services [Core Services]
            HERMES[Hermes Agent :8642<br/>Autonomous Reasoning]
            OMNIR[OmniRoute :20128<br/>290+ LLM Providers]
            IGNIS[Ignis Obsidian :8080<br/>Knowledge Vault]
            REDIS[Redis 7 :6379<br/>Session Cache]
        end

        subgraph Persistence_Tier [Persistence Tier]
            ACTIVE_DB[Local SSD<br/>/root/.omniroute/storage.sqlite]
            DATA_DB[Persistent Volume<br/>/data/omniroute/storage.sqlite]
            HERMES_DATA[Hermes State<br/>/data/hermes/]
            VAULT_DATA[Vault Data<br/>/data/vaults/]
            KEY_HASH[.key_hash<br/>Rotation Guard]
        end
    end

    subgraph Cloud_Providers [Cloud LLM Providers]
        OAI[OpenAI]
        ANT[Anthropic]
        GEM[Google Gemini]
        DS[DeepSeek]
        GROQ[Groq]
        OTHER[290+ Providers]
    end

    APK -->|POST /hermes/v1/messages<br/>Anthropic Format| NGINX
    WEB -->|https://jishnupg-hermes.hf.space| NGINX
    TG -->|Bot Commands| HERMES

    NGINX -->|proxy_pass| BRIDGE
    NGINX -->|proxy_pass| CLAUDE_REST
    NGINX -->|/dashboard/* /v1/*| OMNIROUTE_RT
    NGINX -->|/obsidian/* /ws| IGNIS_RT
    NGINX -->|/v1/chat/completions| HERMES_RT
    NGINX -->|/logs| LOGS

    BRIDGE -->|OpenAI Format| HERMES
    HERMES_RT -->|OpenAI Compat| HERMES
    OMNIROUTE_RT -->|Turbopack| OMNIR
    IGNIS_RT -->|HTTP+WS| IGNIS

    HERMES -->|LLM API| OMNIR
    OMNIR -->|Route+Failover| OAI
    OMNIR -->|Route+Failover| ANT
    OMNIR -->|Route+Failover| GEM
    OMNIR -->|Route+Failover| DS
    OMNIR -->|Route+Failover| GROQ
    OMNIR -->|Route+Failover| OTHER

    HERMES -.->|vault_memory| IGNIS
    IGNIS -.->|markdown vault| VAULT_DATA

    ACTIVE_DB <-->|30s WAL sync| DATA_DB
    KEY_HASH -->|detect rotation| ACTIVE_DB
\
## Component Specifications

### 2.1 Hermes Agent Core (:8642)
- **Core Function**: Autonomous reasoning agent - plan decomposition, tool execution, memory recall, user interaction
- **Dynamic Tool Activation**: Context-aware tool filter analyzes user intent and injects only relevant tool schemas
- **Self-correction Loop**: Catches execution errors, analyzes logs, adjusts parameters, retries automatically
- **Built-in Skills**: web_search, browser_act, code_exec, vault_memory, telegram_notify
- **Telegram Integration**: Receives voice notes, code commands, plain queries; streams progress updates

### 2.2 OmniRoute AI Gateway (:20128)
- **Core Function**: High-performance universal LLM gateway and routing proxy
- **Upstream AI Connectors**: 290+ cloud providers (Groq, Gemini, Antigravity, DeepSeek, NVIDIA NIM, OpenAI, Anthropic, Cerebras, OpenRouter, Mistral, xAI, etc.)
- **Universal API Support**: OpenAI, Anthropic, Gemini, Ollama, CLI Compatibility endpoints
- **Dashboard**: Next.js 16 Turbopack Web Dashboard (/dashboard, /login, /settings, /providers)
- **Intelligent Load Balancing**: API key rotation with automatic rate-limit cooldown and failover
- **Background Monitoring**: Token health check (60s tick), daily model catalog sync (24h)
- **WebSockets**: :20131 (Embedded Services), :20132 (Live Telemetry)

### 2.3 Patched Claude Android APK Integration
- **Mechanism**: Patched APK routes all network requests to https://jishnupg-hermes.hf.space/hermes/v1/messages
- **Protocol Translation**: Gateway translates Anthropic protocol to Hermes agent actions / OmniRoute LLM streams
- **SSE Streaming**: Returns standard Anthropic SSE chunks (message_start, content_block_start, content_block_delta, message_delta, message_stop) with token-by-token streaming
- **7-second Keep-alive**: Heartbeat prevents OkHttp timeout

### 2.4 Ignis / Obsidian Knowledge Graph (:8080)
- **Core Function**: Long-term memory vault and structured knowledge graph
- **Storage**: Markdown-based notes vault on /data/obsidian/vault/
- **Hermes Access**: Bi-directional querying - reads previous context, writes new execution summaries

## Storage, Persistence & Zero-Data-Loss Architecture

### 3.1 Dual-Tier SQLite Engine
- **Local SSD Tier**: /root/.omniroute/ and /root/.hermes/ - high-speed read/write with SQLite WAL mode
- **Persistent Tier**: /data/ - permanent HuggingFace volume across container restarts
- **Background Checkpointer** (30s): PRAGMA wal_checkpoint(PASSIVE) + .backup to persistent tier
- **Boot Validation**: PRAGMA quick_check on all SQLite files
- **Rolling Backups**: Timestamped snapshots in /data/omniroute/backups/

### 3.2 Cryptographic Key Management
- **Secrets**: ENCRYPTION_KEY (AES-256), JWT_SECRET (HMAC-SHA256), API_KEY_SECRET (bearer auth)
- **Key-Hash Guard**: SHA-256 hash stored in .key_hash; rotation detected, DB archived, fresh tables
- **Persistent Storage**: Keys saved to /data/omniroute/ to survive container restarts

## Edge Ingress & Network Design

### 4.1 Nginx Edge Ingress (:7860)
- **Gzip + Brotli**: HTML, JS, CSS, JSON, SVG compression on the fly
- **Content-Encoding Fix**: Normalizes response headers to prevent Turbopack chunk decompression errors
- **WebSocket Passthrough**: Upgrades Upgrade and Connection headers for live telemetry
- **Buffer Tuning**: 100MB body limit for multi-modal uploads
- **SSE Passthrough**: No buffering, no compression for event streams

## Deployment Roadmap

### Phase 1: Base Space Foundation & Edge Ingress
- Dockerfile with multi-stage build (OmniRoute + Python + Redis + Nginx + Node.js)
- nginx.conf edge proxy with WebSocket, Gzip, Brotli support
- PWA manifest routes, favicon, static assets

### Phase 2: Gateway & Service Orchestration
- entrypoint.sh supervisor with process monitoring and graceful shutdown traps
- clean_db.py key-hash validator + health_doctor.py SQLite checkpointer
- FastAPI Ingress Gateway (:8000) with Anthropic to OpenAI stream translator
- Claude REST API mock (/api/bootstrap/*, /api/account)

### Phase 3: Hermes Agent Core & Tool Pipeline
- Hermes Agent runtime on port 8642
- Dynamic tool discovery and context-aware tool activation
- Hermes connected to OmniRoute upstream router and Obsidian storage

### Phase 4: Mobile & External Client Verification
- Verify Claude Android APK connection and streaming responses
- Connect Telegram Bot and test two-way command execution
- End-to-end integration test across all endpoints
