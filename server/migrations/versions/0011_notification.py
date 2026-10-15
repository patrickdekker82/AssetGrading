"""notification log (phase 10)

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("kind", sa.String(20), nullable=False),        # job | watchdog | test
        sa.Column("channel", sa.String(20), nullable=False),     # webhook | e-mail | geen
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("ok", sa.Boolean, nullable=False),
        sa.Column("error", sa.Text),
    )
    op.create_index("ix_notification_created", "notification", ["created_at"])
    op.execute("CREATE TRIGGER notification_append_only BEFORE UPDATE OR DELETE ON notification "
               "FOR EACH ROW EXECUTE FUNCTION forbid_change();")


def downgrade() -> None:
    op.drop_table("notification")
