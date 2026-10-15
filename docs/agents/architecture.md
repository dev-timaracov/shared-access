# Architecture

MCP `init` and `sync` share service methods with REST. Initialization is admin-only,
returns draft file contents for an allowed repository and exact SHA without storing
them as revision-bound documents. The client writes missing files in the target
checkout. Project drafts vary by project; common report and Python/DDD standards
are loaded from packaged `app/specification_guides/*.md` and copied unchanged.
The scaffold also includes `docs/agents/frontend-style-guide.md` for JS/TS/UI;
skills select the Python or frontend standard by the code being changed.
The response marks these paths as `common_files`. Existing files are preserved.
The same scaffold includes four repository-scoped skills under `.agents/skills/`:
`python-unit-tests`, `work-report`, `implement-specification`, and `execute-tracker-task`.
Their canonical `SKILL.md` resources live in packaged `app/skill_templates/` and
are included in `common_files`, copied unchanged across projects. Skills read
the target checkout's documentation rather than embedding this service's architecture.
`python -m app.init_project --project-dir ...` explicitly selects and
checks that checkout and its Git remote. Sync requires write access, follows tracker pagination
and atomically stores the returned task snapshots without deleting work history.

All Compose services use `restart: always`. After successful migration, the migrate
container stays alive and exposes readiness through a marker healthcheck. API and
worker depend on that readiness. On restart the marker is removed before migrating.

`app/main.py` exposes REST and mounts Streamable HTTP MCP at `/mcp/`.
`app/mcp_server.py` publishes the official MCP SDK tools. Both call
`app/service.py`; tools cannot bypass project permissions or report ownership.

`app/auth.py` authenticates bearer tokens before REST/MCP dispatch and propagates
the developer identity through a ContextVar. Tokens have reader/writer/admin roles
and project slug scopes. Only administrators with `*` have global access.
The MVP uses static tokens; it does not implement OAuth discovery or SSO.
Token identities accept an optional `display_name`; no-auth uses
`LOCAL_ADMIN_DISPLAY_NAME`. Migration 0003 adds nullable `reports.developer_name`.
The service snapshots the authenticated name at report creation, independently of
the retry payload hash. History/context and worker publication use that snapshot;
renaming an identity does not alter immutable reports or identical retries.
Reports predating the migration keep a null name and display their developer ID.
The explicit `python -m app --no-auth` option (or `AUTH_DISABLED=true`) assigns
all REST/MCP requests a server-owned `local-admin` identity with global admin
access. Service authorization and ownership checks still run against that identity.
This mode is intended for trusted environments; the CLI binds to loopback by default.

PostgreSQL stores projects, external task mappings/snapshots, developer sessions,
append-only reports, task-to-Git links, revision-bound documentation, observed
task events and a durable report-comment outbox. Alembic owns the schema.

`TaskTracker` in `app/trackers/base.py` is the integration interface for current
requirements, state transitions and report publication. Service and worker receive
it through dependency injection and do not import or understand provider HTTP shapes.
DTOs (`TrackerProject`, `TaskSnapshot`, `TaskContext`, `TrackerReport`) are independent
of ORM models. All snapshots use a normalized state_id and task schema.

`PlaneTaskTracker` in `app/trackers/plane.py` implements this interface, including
v1/v2 normalization, description fallback, UUID validation and comment deduplication.
`app/trackers/factory.py` is the composition root used by API and worker. Register a
new factory there or inject an adapter into `create_app(..., tracker=adapter)`.
`TASK_TRACKER_PROVIDER` selects the process's adapter; each project stores its provider
and must match that adapter. Simultaneous mixed providers are not supported yet.
Credentials stay in adapter-specific settings, not project mappings or tool inputs.

`get_task_context` refreshes on demand and explicitly labels unavailable/cached
snapshots. A project's repository allowlist
restricts document/session inputs. A report can link multiple commits; the same
commit/PR may be linked to several tasks. Git associations are agent claims,
not facts independently verified against a Git provider.

Canonical mapping fields are tracker_provider, tracker_workspace, tracker_project_id
and external_id. External task/state IDs are strings; Plane enforces UUIDs inside
its adapter. Migration 0002 renames the old columns, expands ID lengths and defaults
existing projects to Plane, preserving snapshots, session/report IDs and outbox jobs.
Legacy snapshots with state instead of state_id are accepted on read. Downgrade
rejects non-Plane/oversized mappings to avoid losing data.

Transport-only compatibility aliases live in `app/compat.py` and input schemas:
Plane projects still accept plane_workspace/plane_project_id/plane_item_id and return
deprecated plane/plane_sync aliases. New clients use tracker/tracker_sync/external_id.
PLANE_SYNC_REPORTS remains an alias for TRACKER_SYNC_REPORTS.

Documents are uploaded by an administrator or trusted CI using
`scripts/sync_docs.py`, which reads tracked blobs at a resolved Git commit SHA.
The context query does not fall back between revisions. Agents also read local
repository documentation, particularly for uncommitted changes.

Reports are immutable through the API and PostgreSQL rejects UPDATE/DELETE with
a trigger. Uniqueness on session + retry key handles concurrent identical retries;
a payload hash rejects reusing a key for different content. The report and outbox
job are saved in the same transaction.

The separate worker uses row locks and SKIP LOCKED, retries with backoff, and a
five-minute lease for crash recovery. It looks for a matching Plane external ID
before publishing. This is at-least-once delivery with best-effort remote
deduplication, not exactly-once: Plane does not enforce unique external IDs.
A job becomes `dead` after ten failures; an operator can inspect/reset it in the DB.

Status transitions are admin-only, explicitly allowlisted per project, and compare
an expected state with a live Plane read. This is not an atomic compare-and-swap
at Plane: another writer can change state between GET and PATCH. A crash after
Plane accepts PATCH but before the local commit can leave an audit gap; a later
refresh recovers the current snapshot. Do not use this MVP for guaranteed global
transition auditing without adding upstream activity/webhook reconciliation.

Full-text search uses PostgreSQL `simple` configuration and GIN indexes over
document content and report text. Query inputs are SQL parameters. Project and
optional repository/revision restrictions apply before results are returned.
No embedding model is required. pgvector/semantic ranking is a future extension.

Known boundaries: no automatic Git/CI adapter, no incoming webhook ingestion,
no complete Plane change history/backfill, no OAuth/SSO, no billing/rate-limit layer,
no automatic approval of architectural decisions. Returned document/report text
is external data; consuming agents must not treat it as privileged instructions.

Task creation uses `ContextService.create_task` from REST
`POST /api/projects/{project_id}/tasks/create` and MCP `create_task`. Writer/admin
and project scope are checked before the adapter is called. `NewTask` accepts a
title, plain-text description and priority; the tracker chooses the default state.
Plane escapes descriptions into HTML and supports v1/v2 creation. v2's omitted
description is stored from the input with `description_source=creation_input`.
The returned mapping and snapshot use the existing tasks table. This operation
has no cross-system transaction or automatic retry: if the local save fails, the
error includes the upstream task ID for registration/sync recovery. After an
uncertain upstream failure, inspect live tasks before creating again. Existing
adapters may omit this capability and return 501.

The standalone `frontend/` Vite client reads REST with a bearer token held only in
memory. Development proxies `/api` to the backend; production requires a same-origin
reverse proxy. `ContextService.project_overview` authorizes project scope before
returning project configuration, exact-revision document metadata and local task
snapshots explicitly labeled cached/unavailable. It performs no tracker calls or
writes. Live task browsing continues through the existing paginated tracker method.
Report charts count loaded history by UTC day and outcome; observed events are
limited to the recent events exposed by history, not a full upstream audit.

## Style guide adoption

`docs/agents/style-guide.md` is the local copy of the common Python/DDD standard.
The current checkout uses Ruff format with a 100-character line length in
`pyproject.toml` and CI; Black migration is not part of the initialization change.
Keep the existing formatter for this checkout until that migration is made explicitly.
The current shared ContextService and some tests predate the 500 SLOC / 50-line
limits and the finer application-service decomposition. Treat those differences
as technical debt; this documentation update does not certify full conformance
or require an unrelated rewrite. Apply the standard to new code and avoid expanding
existing violations; record any necessary local exceptions in review.
The frontend currently uses plain JavaScript and Vite with Node's test runner;
TypeScript, Prettier and ESLint are not configured. The frontend guide documents
the target conventions, not a completed tooling migration. Preserve this stack
for existing code until migration is explicitly included in a task.
