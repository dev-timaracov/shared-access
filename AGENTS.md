# Project Context Service

Read `docs/agents/architecture.md`, `docs/agents/testing.md` and
`docs/agents/workflow.md` before changing behavior.

- Python 3.12+, FastAPI, SQLAlchemy async, PostgreSQL and Alembic.
- REST and MCP must call the same service layer; authorization belongs in that layer.
- Every task/document/search operation must check project scope.
- Derive developer identity from authentication, never from agent parameters.
- Work reports are append-only. Retry keys must reject changed payloads.
- The task tracker is the source of current task state. Cached snapshots disclose freshness.
- Service and worker depend on TaskTracker; provider HTTP/payloads belong in adapters.
- Keep status transitions separate from work reports.
- Bind documentation to exact repository revisions. Do not silently fall back to main.
- Agent-reported checks and Git links are unverified until checked against CI/Git.
- Never put credentials in tool schemas, logs or source control.
- Model changes require a new Alembic revision, not edits to historical migrations.
- Run Ruff and the test suite. Report skipped PostgreSQL/integration checks explicitly.
