# Testing

Install dependencies with `uv sync --locked` and run:

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

The default tests use temporary SQLite databases with real Alembic upgrade and
downgrade, a mock HTTP Plane API and real MCP client/server protocol calls through
ASGI. SQLite is a testing fallback, not a deployment database. Its search is a
substring fallback; it cannot validate PostgreSQL FTS, locks or report triggers.

Initialization tests verify that REST/MCP return the same file scaffold without
storing draft documents, and that the local command writes to the selected Git
checkout even when launched elsewhere. Existing files are preserved; wrong
repository URLs, unresolved revisions and unexpected file paths are rejected.
Project drafts still require agent inspection and review. Common report/style
standards are tested for identical content across different project names.

For PostgreSQL checks, point TEST_DATABASE_URL to a dedicated empty test database:

```sh
TEST_DATABASE_URL=postgresql+asyncpg://context:context@localhost:5432/context_test uv run pytest -q
```

Do not point tests at a production database. Tests upgrade/downgrade the schema
and discard all tables after each test. Run sequentially, not with pytest-xdist.
The GitHub Actions workflow runs the suite against PostgreSQL 17.

Tests cover project scoping, session ownership, idempotent and concurrent reports,
outbox atomicity/retries, exact-ref documents, live-to-cached context fallback,
history pagination, controlled transitions, MCP identity propagation and, with
PostgreSQL, append-only triggers and full-text search.

Real Plane connectivity requires a separate test workspace and API credentials.
Automated tests do not modify a real Plane workspace.

The memory adapter verifies that REST, task context, string state transitions and
the worker operate without any Plane requests or payloads. Plane adapter tests
verify the normalized contract separately. Migration tests seed a legacy SQLite
database and verify mappings, snapshots, reports and pending jobs survive upgrade
and downgrade. This migration preservation test does not replace PostgreSQL CI.

Frontend checks: `cd frontend`, `npm ci`, `npm test`, `npm run build`.
The Node tests verify report aggregation and escaping of external text. The backend
suite verifies the read-only project overview and reader/project authorization.

Task creation tests cover Plane v1/v2 POST payloads and escaped descriptions,
invalid upstream responses, REST/MCP creation and database snapshots, write/project
scope, input validation, upstream failure without local insertion, and database
failure recovery through the reported external ID. Remote creation is mocked;
these tests do not demonstrate atomicity between Plane and PostgreSQL.
