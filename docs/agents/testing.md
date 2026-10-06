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

