# Hermex Phase 3

Phase 3 adds durable projects, memory, goals, and dependency-aware tasks to
the existing Hermex WebUI without changing the frozen APK boundary or the
legacy `/v1/*` APIs.

## Architecture

The root FastAPI gateway remains the WebUI source of truth. Phase 3 extends
`gateway/webui_api.py`, which already owns authenticated WebUI metadata in
`HERMES_WEBUI_DATA_DIR` ( `/data/hermes/webui/state.json` in production).
Conversation messages remain in the existing `sessions_api` store at
`/data/sessions`.

The existing Hermes semantic-memory index is reused when a WebUI memory record
is created: the record remains user-scoped in WebUI state and is also indexed
through `hermes_core.tools.memory_tools.index_document_vector` for agent
recall. Indexing failure does not make the durable WebUI write fail.

## Data model

The state migration adds `memory`, `goals`, `tasks`, and `files` collections to
the existing JSON state document. Existing state files are upgraded
non-destructively with empty collections.

- **Projects** include name, description, instructions, color, archive state,
  timestamps, and computed session/file/goal/task counts.
- **Memory** includes content, type/category, source, timestamps, project and
  session references, confidence, metadata, and owner.
- **Goals** include title, description, status, priority, deadline, project
  reference, and timestamps. Progress is computed as completed tasks divided by
  tasks; no-task goals report zero.
- **Tasks** include status, goal/project references, dependency IDs,
  timestamps, error/result/summary fields, and an optional session reference.

Task dependencies must remain in the same project, cannot reference the task
itself, and cannot form a cycle. A task cannot become `READY` or `RUNNING`
until every predecessor is `COMPLETED`. Readiness is recalculated after task
changes, so failed/cancelled predecessors produce a durable `BLOCKED` state.

## API

All Phase 3 routes require the existing WebUI cookie or bearer key:

- `GET|POST /api/projects`
- `GET|PATCH|DELETE /api/projects/:id`
- `GET /api/projects/:id/{sessions,files,memory,goals,tasks}`
- `GET|POST /api/memory`, `PATCH|DELETE /api/memory/:id`
- `GET|POST /api/projects/:id/memory`
- `GET|POST /api/goals`, `GET|PATCH|DELETE /api/goals/:id`
- `GET|POST /api/projects/:id/goals`
- `GET|POST /api/goals/:id/tasks`
- `GET|POST /api/tasks`, `GET|PATCH|DELETE /api/tasks/:id`
- `POST /api/tasks/:id/start`
- `GET|POST /api/projects/:id/tasks`

The older action routes `/api/projects/{create,rename,delete}` remain
available for compatibility.

## UI

The existing dark Hermex chat remains the default view. A compact workspace
navigation adds Projects, Memory, and Goals. Project detail shows real
session/file/goal/task counts and project-scoped memory. Memory supports
search, creation, and forget. Goals show derived progress and a task graph
hierarchy with dependency-aware completion. All states include loading, empty,
and error handling, and the layout collapses for mobile widths.

## Authorization

Projects, memory, goals, tasks, and project files carry the same WebUI owner
principal used by existing sessions. Every read, write, update, delete, and
cross-resource reference is checked in the backend. Resource mismatches return
not-found semantics rather than exposing another principal's data.

## Validation

The Phase 3 suite covers authentication, project CRUD/detail, memory CRUD,
goal/task persistence, derived progress, dependency blocking/readiness, cycle
protection, and wrong-owner access. Existing WebUI, stream, attachment,
security, compatibility, and capability tests remain in the same suite.

Deployment and live verification are intentionally recorded only after a
successful push and live check.