# Phase status

- Phase 0: COMPLETE
- Phase 1: COMPLETE
- Phase 2: COMPLETE
- Phase 3: COMPLETE locally; deployment pending for the current WebUI revision

The Phase 3 backend and API were already implemented and covered by the local
functional suite. The existing Hermes WebUI now exposes the complete workspace
navigation—Chat, Projects, Memory, Goals, Tasks, and Settings—against those
same authenticated APIs. Tasks can be started or completed from the durable
task graph, and the Settings view reads and persists the server-owned WebUI
visibility settings without exposing provider credentials.

The previous deployment was live-verified before this revision, but the current
revision has not been pushed or live-verified from this workspace. Run the
deployment checklist after publishing it; authenticated CRUD still requires
the production password, which is intentionally not stored in the repository
or this workspace.