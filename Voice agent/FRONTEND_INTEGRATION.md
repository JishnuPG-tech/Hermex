# Replit / Web Voice UI Integration

The existing Replit voice UI should remain unchanged until the backend is deployed and health-checked.

## 1. Create a session

POST to:

`https://<VOICE_API_HOST>/voice/session`

Body:

```json
{
  "voice": "rounded",
  "language": "en-GB",
  "pace": "normal"
}
```

Response:

```json
{
  "session_id": "uuid",
  "room_name": "hermex-voice-uuid",
  "participant_identity": "user-uuid",
  "livekit_url": "wss://...",
  "token": "short-lived-jwt",
  "token_expires_in": 600,
  "agent_name": "hermex-voice",
  "settings": {
    "voice": "rounded",
    "language": "en-GB",
    "pace": "normal"
  }
}
```

## 2. Connect to LiveKit

Use the official LiveKit Web SDK. Connect using the returned `livekit_url` and token.

The browser must never contain:

- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- Hermes API keys
- OmniRoute keys

## 3. Publish microphone

After connecting:

1. Enable the microphone.
2. Publish the local audio track.
3. Subscribe to the Hermex agent's audio track.
4. Render the actual local/remote audio levels into the existing UI atmosphere.

## 4. Voice state

The UI should derive state from LiveKit/agent events:

- CONNECTING
- LISTENING
- THINKING
- SPEAKING
- RECONNECTING
- ERROR
- DISCONNECTED

Do not add a chat transcript.

## 5. Interruption

Do not implement a separate frontend cancellation protocol for speech. The LiveKit AgentSession handles normal realtime interruption/barge-in behavior. The UI only needs to keep publishing microphone audio and reflect the current state.

## 6. Settings

When the user changes voice/language/pace, the next `/voice/session` request should use the selected values.

For an active room, changing these settings should either:

- apply them through a future realtime data/control protocol, or
- take effect on the next session.

Do not silently pretend a setting changed if the active agent did not receive it.

## 7. Health check

Before connecting the UI:

`GET /health`

Expected:

```json
{
  "status": "ok",
  "service": "hermex-voice-api"
}
```

## 8. Production security

The `/voice/session` endpoint should be protected by the existing Hermex authentication layer when the integration moves beyond the isolated demo. The current shared-secret hook is intentionally minimal and is not a replacement for the main Hermex identity system.
