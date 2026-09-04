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

The additive WebUI adapter exposes authentication, sessions, projects, chat/SSE, uploads, workspace files, models, providers, settings, reasoning, and profiles under `/api/*`. Set `HERMES_WEBUI_PASSWORD` in the Hugging Face Space Variables and secrets to enable the independent WebUI password login. The adapter uses an HTTP-only session cookie and never returns Gateway credentials to clients.

WebUI chat defaults to the existing gateway at `http://127.0.0.1:8000`; set `HERMES_WEBUI_GATEWAY_BASE_URL` and `HERMES_WEBUI_GATEWAY_API_KEY` only when the deployment topology requires a different internal gateway. Conversation data continues in `/data/sessions`; WebUI metadata and file-backed SSE replay state use `/data/hermes/webui`. `/data` must be backed by persistent Space storage for state to survive restarts.

Health: `GET /health`
