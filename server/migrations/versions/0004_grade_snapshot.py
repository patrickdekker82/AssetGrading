"""grade_snapshot: one grade per asset, day and model version (append-only)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "grade_snapshot",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("asset.id"), nullable=False),
        sa.Column("as_of", sa.Date, nullable=False),
        sa.Column("model_version_id", sa.Integer, sa.ForeignKey("model_version.id"), nullable=False),
        sa.Column("template_id", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("score", sa.Float),
        sa.Column("quality", sa.Float),
        sa.Column("timing", sa.Float),
        sa.Column("coverage", sa.Float, nullable=False),
        sa.Column("letter", sa.String(3)),
        sa.Column("peg_safety", sa.Integer),
        sa.Column("price_eur", sa.Float),
        sa.Column("knowledge_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("inputs", JSONB, nullable=False),
        sa.Column("result", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("asset_id", "as_of", "model_version_id"),
    )
    op.create_index("ix_grade_snapshot_asof", "grade_snapshot", ["as_of", "model_version_id"])
    op.execute(
        "CREATE TRIGGER grade_snapshot_append_only BEFORE UPDATE OR DELETE ON grade_snapshot "
        "FOR EACH ROW EXECUTE FUNCTION forbid_change();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER grade_snapshot_append_only ON grade_snapshot;")
    op.drop_table("grade_snapshot")
