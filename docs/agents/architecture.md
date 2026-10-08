# Architecture

`app/main.py` exposes REST and mounts Streamable HTTP MCP at `/mcp/`.
`app/mcp_server.py` publishes the official MCP SDK tools. Both call
`app/service.py`; tools cannot bypass project permissions or report ownership.

`app/auth.py` authenticates bearer tokens before REST/MCP dispatch and propagates
the developer identity through a ContextVar. Tokens have reader/writer/admin roles
and project slug scopes. Only administrators with `*` have global access.
The MVP uses static tokens; it does not implement OAuth discovery or SSO.
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
