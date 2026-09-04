---
title: Hermes
emoji: ⚡
colorFrom: purple
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# Hermes Agent + Knowledge Space

Autonomous AI Agent Core with dynamic situation-aware tool activation, connected to the OmniRoute LLM Gateway (`jishnupg-opencode-cli.hf.space`) and Ignis Obsidian Knowledge Vault.

### Ingress Endpoints:
- **Claude Android APK:** `POST https://jishnupg-hermes.hf.space/v1/messages`
- **OpenAI v1 Ingress:** `POST https://jishnupg-hermes.hf.space/v1/chat/completions`
- **Obsidian Vault UI:** `https://jishnupg-hermes.hf.space/vault`


## Hermex / WebUI API

The existing OpenAI-compatible `/v1/*` API remains available unchanged. Hermex should use the Space root URL, not append `/v1`:

`https://jishnupg-hermes.hf.space`

The additive WebUI adapter exposes authentication, sessions, projects, chat/SSE, uploads, workspace files, models, providers, settings, reasoning, and profiles under `/api/*`. Set `HERMES_WEBUI_PASSWORD` in the Hugging Face Space Variables and secrets to enable the independent WebUI password login. Alternatively, set `HERMES_WEBUI_API_KEY` to accept a pre-shared bearer key without issuing a cookie. The adapter uses an HTTP-only session cookie and never returns Gateway credentials to clients. Do not rely on the development fallback (no configured WebUI credential) for a public deployment.

### Hermes Agent server operations

The `Hermes Agent` tool loop owns server-side work; the upstream inference service only supplies model tokens. Its `bash_exec` tool runs Bash directly inside the running Space container with the normal `/app` and `/data` filesystem, network, environment, and installed binaries. It can inspect and edit files, run tests and services, install packages, clone/pull/commit/push Git repositories, and inspect logs or processes. Commands accept a working directory, a 1–600 second timeout, and bounded output. The production image includes Git and Python; package installation remains available to the container runtime.

Multi-step tool calls feed each command result back into the next agent round. `HERMES_MAX_TOOL_ROUNDS` controls the per-request tool loop (default 6, maximum 12), and `HERMES_SERVER_WORKDIR` controls the default shell directory (default `/app`). The agent must verify command output before reporting an operation as complete.

WebUI chat defaults to the existing Hermes runtime at `http://127.0.0.1:8642/v1/chat`, preserving its tools and model fallback behavior. Set `HERMES_WEBUI_CHAT_BACKEND=gateway`, `HERMES_WEBUI_GATEWAY_BASE_URL`, and `HERMES_WEBUI_GATEWAY_API_KEY` only when the deployment topology requires the OpenAI-compatible gateway instead. Conversation data continues in `/data/sessions`; WebUI metadata and file-backed SSE replay state use `/data/hermes/webui`. `/data` must be backed by persistent Space storage for state to survive restarts. `HERMES_AVAILABLE_MODELS` can provide a comma-separated list of models confirmed by the configured provider.

Health: `GET /health`

### WebUI endpoint reference

All WebUI routes except authentication status and login require either the
`hermes_webui_session` HTTP-only cookie or the configured
`HERMES_WEBUI_API_KEY` bearer token. JSON errors use an `error` or FastAPI
`detail` field and standard HTTP status codes.

- Authentication: `GET /api/auth/status`, `POST /api/auth/login`,
  `POST /api/auth/logout`
- Sessions: `GET /api/sessions`, `GET /api/sessions/search`,
  `GET /api/session`, `GET /api/session/status`,
  `GET /api/session/usage`, `POST /api/session/new`,
  `POST /api/session/{rename,delete,clear,pin,archive,move,branch,truncate,update,compress,undo,retry,yolo}`
- Projects: `GET /api/projects`, `POST /api/projects/{create,rename,delete}`
- Chat: `POST /api/chat/start`, `GET /api/chat/stream`,
  `GET|POST /api/chat/cancel`, `GET /api/chat/stream/status`,
  `POST /api/chat/steer`
- Workspaces/files: `GET /api/workspaces`,
  `GET /api/workspaces/suggest`, `GET /api/list`, `GET /api/file`,
  `GET /api/file/raw`, `GET /api/media`
- Uploads: `POST /api/upload`, `POST /api/upload/extract`
- Configuration: `GET /api/models`, `GET /api/models/live`,
  `GET /api/providers`, `GET|POST /api/settings`,
  `POST /api/default-model`, `GET|POST /api/reasoning`,
  `GET /api/profiles`, `POST /api/profile/{switch,create}`

`/api/chat/stream` is a real SSE stream. Events include `token`,
`reasoning`, `tool_call`, `tool_result`, `error`, `cancel`, and
`stream_end`. Pass `Last-Event-ID: <stream_id>:<sequence>` or
`after_seq` to replay events after a reconnect. Cancellation cancels the
underlying asyncio task and closes its upstream HTTP stream.

### Configuration and deployment

Required in production:

- `UPSTREAM_OMNIROUTE_URL` and `UPSTREAM_API_KEY` for the Hermes runtime
- `HERMES_WEBUI_PASSWORD` or `HERMES_WEBUI_API_KEY` for WebUI authentication

Optional WebUI variables are `HERMES_WEBUI_COOKIE_SECURE` (defaults to
`true`), `HERMES_WEBUI_ALLOWED_ORIGINS`, `HERMES_WEBUI_DATA_DIR`,
`HERMES_WEBUI_WORKSPACES`, `HERMES_WEBUI_WORKSPACE_BASE`,
`HERMES_WEBUI_MAX_UPLOAD_BYTES`, `HERMES_AVAILABLE_MODELS`,
`HERMES_WEBUI_GATEWAY_BASE_URL`, and `HERMES_WEBUI_GATEWAY_API_KEY`.
Credentials belong in Hugging Face Variables and secrets, never in git.

Hugging Face exposes only Nginx on port 7860:

`HTTPS → Nginx :7860 → FastAPI :8000 → /api WebUI adapter → Hermes :8642`

The adapter shares the existing session store at `/data/sessions`; its
metadata and durable SSE replay files are stored at
`/data/hermes/webui`. The root `entrypoint.sh` runs one FastAPI worker so
these process-local caches remain consistent while `/data` provides restart
persistence. The existing OpenAI-compatible API remains at
`https://jishnupg-hermes.hf.space/v1`.

The repository root (`Dockerfile`, `entrypoint.sh`, `nginx.conf`, and
`gateway/`) is the Hugging Face deployment source of truth. `Backend/` is
retained as the older standalone gateway source; the root image copies only
its complete Claude REST bridge because the root adapter imports that
implementation. Changes to the deployed WebUI adapter belong in the root
tree.

### Verification

Run the dependency-light regression suite and syntax checks from the
repository root:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q gateway hermes_core
git diff --check
```
