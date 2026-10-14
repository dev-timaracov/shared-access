"""Snapshot the authenticated developer's display name in each report."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("reports", sa.Column("developer_name", sa.String(200), nullable=True))


def downgrade():
    with op.batch_alter_table("reports") as batch:
        batch.drop_column("developer_name")
