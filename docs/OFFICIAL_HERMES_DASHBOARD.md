# Official Hermes dashboard integration

Hermex serves the upstream Hermes dashboard from `official/web` at
`/dashboard/`. The source is derived from NousResearch/hermes-agent commit
`245e48008fa814b3251f50755eb656bd9fb86cb1` (2026-09-05) and retains the
upstream MIT license and attribution. `official/apps/shared` contains the
small shared TypeScript package required by the dashboard's WebSocket client.

## Runtime architecture

```text
Browser
  -> official Hermes Web Dashboard (/dashboard/)
  -> Hermex WebUI compatibility/API layer (/api/*)
  -> existing Hermex gateway and session store
  -> Hermes Agent (:8642)
```

The dashboard is built with Vite into `build/hermes-dashboard` and copied into
the production image as `/app/web`. FastAPI serves its assets and SPA
deep-links under `/dashboard/*`. API routes remain at `/api/*`; this is why
the generated dashboard is configured with `base: "/dashboard/"` while the
runtime base-path variable is empty.

## Compatibility contract

The compatibility layer provides real adapters for:

- `/api/status`, `/api/auth/me`, `/api/auth/ws-ticket`
- paginated session list/detail/messages/search/stats and deletion
- `/api/config`, `/api/config/defaults`, `/api/config/schema`, `/api/config/raw`
- `/api/model/info`, `/api/model/options`, `/api/profiles`, `/api/profiles/active`
- `/api/logs`, `/api/gateway`, `/api/analytics`
- `/api/events`, `/api/ws`, and `/api/pty`

Dashboard chat uses the existing Hermes stream worker. The PTY bridge accepts
terminal input only, handles resize/ping control messages, and emits real
streamed Hermes tokens, reasoning, tool notifications, and errors. It does not
expose a host shell or arbitrary filesystem operations. WebSocket upgrades
require the same cookie/bearer authentication as REST, or a single-use ticket
minted by `/api/auth/ws-ticket`.

Hermex-specific APIs for projects, memory, goals, tasks, uploads, artifacts,
and settings remain available in `gateway/webui_api.py`. The former React/Vite
application in `artifacts/hermes-web` is retained only as historical source
and tests; it is no longer copied, built, or served by the production image.

The upstream dashboard exposes additional Hermes features that require the
full Hermes CLI runtime (cron, MCP management, plugin installation, provider
OAuth, and messaging setup). Those endpoints return an explicit `501
feature_not_supported` response in Hermex until a safe backend equivalent is
available; they never return fake success responses.