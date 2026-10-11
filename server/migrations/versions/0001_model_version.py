"""model_version: every model configuration ever loaded (append-only)

Revision ID: 0001
Revises:
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_version",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("version", sa.String(32), nullable=False, unique=True),
        sa.Column("config_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.Text),
        sa.Column("config", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # Model versions are history: refuse UPDATE and DELETE at database level.
    op.execute(
        """
        CREATE FUNCTION forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME;
        END;
        $$;
        """
    )
    op.execute(
        "CREATE TRIGGER model_version_append_only BEFORE UPDATE OR DELETE ON model_version "
        "FOR EACH ROW EXECUTE FUNCTION forbid_change();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER model_version_append_only ON model_version;")
    op.execute("DROP FUNCTION forbid_change();")
    op.drop_table("model_version")
