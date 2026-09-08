# Hermex Voice Agent

This directory is intentionally isolated from the existing Hermex runtime.

It provides the production realtime voice layer for the Hermex Voice Agent UI:

```text
Web / Android
    |
    | HTTPS token/session API
    v
Voice API
    |
    | LiveKit JWT
    v
LiveKit Cloud
    |
    | WebRTC audio
    v
Hermex Voice Agent
    |
    | OpenAI-compatible HTTPS
    v
Hermes Cognitive Core (:8642 /v1/chat/completions)
    |
    v
OmniRoute -> configured AI models
```

## Isolation

Nothing in this folder is imported by the existing gateway. The existing Hermex application is therefore unchanged until an explicit integration step is performed.

## Services

- `api.py`: token/session/config API for the voice frontend.
- `agent.py`: LiveKit Agents 1.x realtime voice worker.
- `cognitive.py`: secure adapter from the voice worker to the existing Hermes OpenAI-compatible endpoint.
- `config.py`: environment configuration and validation.
- `protocol.py`: shared session/settings models.

## Required environment

Copy `.env.example` to `.env` and provide:

- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `HERMES_COGNITIVE_URL`
- `HERMES_COGNITIVE_API_KEY`

The voice agent uses LiveKit Inference for STT/TTS by default. This keeps the voice transport/provider implementation separate from Hermes reasoning. Provider-specific STT/TTS can be introduced later without changing the frontend contract.

## Run API

```bash
pip install -r requirements.txt
uvicorn api:app --host 0.0.0.0 --port 8788
```

## Run agent

```bash
python agent.py start
```

For local LiveKit development, use the LiveKit CLI/dev workflow as appropriate.

## Frontend contract

`POST /voice/session` returns a short-lived LiveKit token and room URL. The browser/mobile client must never receive `LIVEKIT_API_SECRET`.

Example request:

```json
{
  "voice": "rounded",
  "language": "en-GB",
  "pace": "normal"
}
```

The frontend then connects to the returned LiveKit room using the returned JWT.

## Production notes

- Use opaque UUIDs for LiveKit identities and room names. Never use a user's real name in these values.
- Keep all secrets in deployment environment variables.
- Put the API behind HTTPS.
- Use an authenticated frontend-to-token request in production.
- The Cognitive Core URL should point at the existing Hermes OpenAI-compatible `/v1/chat/completions` endpoint.
- Do not expose OmniRoute credentials or Hermes internal credentials to the client.
