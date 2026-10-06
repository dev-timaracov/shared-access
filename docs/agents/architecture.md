# Architecture

`app/main.py` exposes REST and mounts Streamable HTTP MCP at `/mcp/`.
`app/mcp_server.py` publishes the official MCP SDK tools. Both call
`app/service.py`; tools cannot bypass project permissions or report ownership.

`app/auth.py` authenticates bearer tokens before REST/MCP dispatch and propagates
the developer identity through a ContextVar. Tokens have reader/writer/admin roles
and project slug scopes. Only administrators with `*` have global access.
The MVP uses static tokens; it does not implement OAuth discovery or SSO.

PostgreSQL stores projects, Plane task mappings/snapshots, developer sessions,
append-only reports, task-to-Git links, revision-bound documentation, observed
task events and a durable report-comment outbox. Alembic owns the schema.

Plane supplies current task requirements and state. `get_task_context` refreshes
on demand and explicitly labels unavailable/cached snapshots. v1/v2 request
differences are isolated in `app/plane.py`. A project's repository allowlist
restricts document/session inputs. A report can link multiple commits; the same
commit/PR may be linked to several tasks. Git associations are agent claims,
not facts independently verified against a Git provider.

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

