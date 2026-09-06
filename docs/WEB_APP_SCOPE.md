# Hermex Web App Scope

The Hermex Web App is the primary updateable client for Hermes. It is a
responsive React/TypeScript application that can also be installed as a PWA.
The frozen Android APK remains a separate compatibility client.

## Initial vertical slice

The first web release implements:

1. password/session bootstrap
2. session list
3. create and select conversations
4. streaming chat over the existing WebUI SSE API
5. reconnect and replay
6. cancellation
7. responsive mobile and desktop layout

## Backend boundary

The Web App uses the existing same-origin FastAPI WebUI APIs:

- `GET /api/auth/status`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/sessions`
- `GET /api/session`
- `POST /api/session/new`
- `POST /api/chat/start`
- `GET /api/chat/stream`
- `GET /api/chat/stream/status`
- `POST /api/chat/cancel`

The Web App must not contain provider credentials or implement a second agent
runtime. Hermes Agent remains the source of tool execution and model routing.

## Browser constraints

The server-side autonomous runtime continues while the browser is closed.
Service workers provide notifications and asset caching; they must not be
treated as an unrestricted background execution environment. Browser voice
requires explicit microphone permission and a user-visible active session.