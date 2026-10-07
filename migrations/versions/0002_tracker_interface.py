"""Generalize project/task mapping; preserve existing Plane data and IDs."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column("tracker_provider", sa.String(40), nullable=False, server_default="plane")
        )
        batch.alter_column(
            "plane_workspace", new_column_name="tracker_workspace", existing_type=sa.String(100)
        )
        batch.alter_column(
            "plane_project_id",
            new_column_name="tracker_project_id",
            existing_type=sa.String(36),
            type_=sa.String(200),
        )
    with op.batch_alter_table("tasks") as batch:
        batch.alter_column(
            "plane_item_id",
            new_column_name="external_id",
            existing_type=sa.String(36),
            type_=sa.String(200),
        )


def downgrade():
    connection = op.get_bind()
    if not op.get_context().as_sql:
        incompatible = connection.scalar(
            sa.text(
                "SELECT count(*) FROM projects WHERE tracker_provider != 'plane' "
                "OR length(tracker_project_id) > 36"
            )
        ) or connection.scalar(sa.text("SELECT count(*) FROM tasks WHERE length(external_id) > 36"))
        if incompatible:
            raise RuntimeError("Cannot downgrade non-Plane or oversized tracker mappings")
    with op.batch_alter_table("tasks") as batch:
        batch.alter_column(
            "external_id",
            new_column_name="plane_item_id",
            existing_type=sa.String(200),
            type_=sa.String(36),
        )
    with op.batch_alter_table("projects") as batch:
        batch.alter_column(
            "tracker_workspace", new_column_name="plane_workspace", existing_type=sa.String(100)
        )
        batch.alter_column(
            "tracker_project_id",
            new_column_name="plane_project_id",
            existing_type=sa.String(200),
            type_=sa.String(36),
        )
        batch.drop_column("tracker_provider")
