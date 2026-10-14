"""llm_call and explanation (append-only), llm_batch (chapter 9)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "llm_batch",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("batch_id", sa.String(100), nullable=False, unique=True),
        sa.Column("component", sa.String(40), nullable=False),
        sa.Column("model", sa.String(60), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("model_version_id", sa.Integer, sa.ForeignKey("model_version.id"), nullable=False),
        sa.Column("custom_ids", JSONB, nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),     # submitted | ended | expired | failed
        sa.Column("submitted_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("ended_at", TS),
    )
    op.create_table(
        "llm_call",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("component", sa.String(40), nullable=False),
        sa.Column("model", sa.String(60), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False, index=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("asset.id"), index=True),
        sa.Column("model_version_id", sa.Integer, sa.ForeignKey("model_version.id")),
        sa.Column("snapshot_as_of", sa.Date),
        sa.Column("mode", sa.String(10), nullable=False),        # batch | direct
        sa.Column("batch_id", sa.String(100)),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("stop_reason", sa.String(30)),
        sa.Column("output", sa.Text),                            # the raw answer, exactly as received
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("problems", JSONB),
        sa.Column("usage", JSONB),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("request_id", sa.String(100)),
        sa.Column("error", sa.Text),
    )
    op.create_table(
        "explanation",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("asset.id"), nullable=False),
        sa.Column("model_version_id", sa.Integer, sa.ForeignKey("model_version.id"), nullable=False),
        sa.Column("snapshot_as_of", sa.Date, nullable=False),
        sa.Column("source", sa.String(10), nullable=False),      # model | template (after a failed check)
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("used_metrics", JSONB),
        sa.Column("llm_call_id", sa.BigInteger, sa.ForeignKey("llm_call.id")),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        # The grade it was written for, to decide when it must be rewritten.
        sa.Column("status", sa.String(20)),
        sa.Column("letter", sa.String(3)),
        sa.Column("score", sa.Float),
        sa.Column("peg_safety", sa.Integer),
        sa.Column("pillars", JSONB, nullable=False),
    )
    op.create_index("ix_explanation_asset", "explanation", ["asset_id", "model_version_id", "created_at"])
    for table in ("llm_call", "explanation"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_change();"
        )


def downgrade() -> None:
    op.drop_table("explanation")
    op.drop_table("llm_call")
    op.drop_table("llm_batch")
