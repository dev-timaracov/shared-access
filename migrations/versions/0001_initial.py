"""Initial schema, full-text indexes and append-only report protection."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    json = sa.JSON().with_variant(JSONB(), "postgresql")

    def ident():
        return sa.Column("id", sa.String(36), primary_key=True)

    def fk(name, table):
        return sa.Column(name, sa.String(36), sa.ForeignKey(f"{table}.id"), nullable=False)

    def col(name, type):
        return sa.Column(name, type, nullable=False)

    op.create_table(
        "projects",
        ident(),
        col("slug", sa.String(80)),
        col("name", sa.String(200)),
        sa.Column("plane_workspace", sa.String(100)),
        sa.Column("plane_project_id", sa.String(36)),
        col("repositories", json),
        col("allowed_transitions", json),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "tasks",
        ident(),
        fk("project_id", "projects"),
        col("plane_item_id", sa.String(36)),
        col("snapshot", json),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("project_id", "plane_item_id"),
    )
    op.create_index("ix_tasks_project_id", "tasks", ["project_id"])
    op.create_table(
        "work_sessions",
        ident(),
        fk("task_id", "tasks"),
        col("developer_id", sa.String(128)),
        col("agent_client", sa.String(80)),
        col("repo", sa.String(300)),
        col("branch", sa.String(200)),
        sa.Column("base_sha", sa.String(64)),
        col("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_work_sessions_task_id", "work_sessions", ["task_id"])
    op.create_table(
        "reports",
        ident(),
        fk("task_id", "tasks"),
        fk("session_id", "work_sessions"),
        col("developer_id", sa.String(128)),
        col("idempotency_key", sa.String(128)),
        col("payload_hash", sa.String(64)),
        col("payload", json),
        col("search_text", sa.Text()),
        col("created_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("session_id", "idempotency_key"),
    )
    op.create_index("ix_reports_task_time", "reports", ["task_id", "created_at", "id"])
    op.create_table(
        "git_links",
        ident(),
        fk("task_id", "tasks"),
        col("repo", sa.String(300)),
        col("kind", sa.String(20)),
        col("value", sa.String(500)),
        sa.UniqueConstraint("task_id", "repo", "kind", "value"),
    )
    op.create_index("ix_git_links_task_id", "git_links", ["task_id"])
    op.create_table(
        "documents",
        ident(),
        fk("project_id", "projects"),
        col("repo", sa.String(300)),
        col("ref", sa.String(200)),
        col("path", sa.String(500)),
        col("content", sa.Text()),
        sa.Column("source_url", sa.String(1000)),
        col("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("project_id", "repo", "ref", "path"),
    )
    op.create_index("ix_documents_project_id", "documents", ["project_id"])
    op.create_table(
        "task_events",
        ident(),
        fk("task_id", "tasks"),
        col("actor", sa.String(128)),
        col("payload", json),
        col("created_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_task_events_task_id", "task_events", ["task_id"])
    op.create_table(
        "outbox",
        ident(),
        fk("report_id", "reports"),
        col("status", sa.String(20)),
        col("attempts", sa.Integer()),
        col("available_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(200)),
        sa.UniqueConstraint("report_id"),
    )
    op.create_index("ix_outbox_status", "outbox", ["status"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_reports_fts ON reports USING gin "
            "(to_tsvector('simple'::regconfig, search_text))"
        )
        op.execute(
            "CREATE INDEX ix_documents_fts ON documents USING gin "
            "(to_tsvector('simple'::regconfig, content))"
        )
        op.execute("""
            CREATE FUNCTION reject_report_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'Work reports are append-only'; END;
            $$
        """)
        op.execute(
            "CREATE TRIGGER reports_append_only BEFORE UPDATE OR DELETE ON reports "
            "FOR EACH ROW EXECUTE FUNCTION reject_report_mutation()"
        )


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER reports_append_only ON reports")
        op.execute("DROP FUNCTION reject_report_mutation()")
    for table in (
        "outbox",
        "task_events",
        "documents",
        "git_links",
        "reports",
        "work_sessions",
        "tasks",
        "projects",
    ):
        op.drop_table(table)
