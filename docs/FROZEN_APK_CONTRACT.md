# Frozen Hermex APK Contract

The existing Hermex Android APK is a compatibility client. It cannot be
rebuilt or updated to receive new features, so the backend must preserve the
routes and response shapes that it already uses.

## Supported compatibility surface

The frozen APK may continue to use:

- `/health`
- authentication and bootstrap routes already present in the gateway
- model discovery
- session loading
- Anthropic-compatible `/v1/messages` streaming

These routes are compatibility surfaces. New product features must not require
an APK update.

## New feature policy

The following capabilities belong to the updateable Hermex Web App instead of
the frozen APK:

- goals and task graphs
- autonomous-run dashboards
- memory management
- rich artifacts
- approval workflows
- scheduling
- proactive-contact controls
- browser voice
- Web Push
- WebRTC/SIP controls
- audit and activity views

Backend changes must run the frozen-client regression tests before deployment.
The APK remains useful for basic chat and compatibility verification, but it is
not the primary product surface for new development.