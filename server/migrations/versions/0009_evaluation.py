"""backtest runs and snapshots, outcomes, evaluations and model proposals (chapter 8)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "backtest_run",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("model_version_id", sa.Integer, sa.ForeignKey("model_version.id"), nullable=False),
        sa.Column("params", JSONB, nullable=False),               # start, end, classes
        sa.Column("status", sa.String(20), nullable=False),        # running | ok | failed
        sa.Column("started_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", TS),
        sa.Column("summary", JSONB),
        sa.Column("error", sa.Text),
    )
    # Recomputed history. Never shown as a result that was achieved (chapter 8).
    op.create_table(
        "backtest_snapshot",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("backtest_run.id"), nullable=False),
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
        sa.Column("knowledge_time", TS, nullable=False),
        sa.Column("inputs", JSONB, nullable=False),
        sa.Column("result", JSONB, nullable=False),
        sa.UniqueConstraint("run_id", "asset_id", "as_of"),
    )
    op.create_index("ix_backtest_snapshot_run_as_of", "backtest_snapshot", ["run_id", "as_of"])
    # Outcome after 1, 3, 6 and 12 months of a month-end grade, live or from a backtest run.
    op.create_table(
        "outcome",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("source", sa.String(10), nullable=False),        # live | backtest
        sa.Column("run_id", sa.Integer, sa.ForeignKey("backtest_run.id")),
        sa.Column("model_version_id", sa.Integer, sa.ForeignKey("model_version.id"), nullable=False),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("asset.id"), nullable=False),
        sa.Column("as_of", sa.Date, nullable=False),
        sa.Column("horizon_months", sa.Integer, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("total_return", sa.Float, nullable=False),
        sa.Column("benchmark", sa.String(60)),
        sa.Column("benchmark_return", sa.Float),
        sa.Column("excess_return", sa.Float, nullable=False),
        sa.Column("max_drawdown", sa.Float, nullable=False),
        sa.Column("computed_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.execute("CREATE UNIQUE INDEX ux_outcome ON outcome (source, COALESCE(run_id, 0), model_version_id, asset_id, "
               "as_of, horizon_months)")
    op.create_table(
        "evaluation",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("backtest_run.id")),
        sa.Column("model_version_id", sa.Integer, sa.ForeignKey("model_version.id"), nullable=False),
        sa.Column("computed_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("report", JSONB, nullable=False),
    )
    op.create_table(
        "model_proposal",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.String(30), nullable=False),           # letter_scale | weights (phase 9)
        sa.Column("model_version_id", sa.Integer, sa.ForeignKey("model_version.id"), nullable=False),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("backtest_run.id")),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("summary_nl", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("evidence", JSONB, nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="open"),  # open | approved | rejected
        sa.Column("decided_at", TS),
        sa.Column("applied_version", sa.String(20)),
    )
    for table in ("outcome", "evaluation"):
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION forbid_change();")


def downgrade() -> None:
    for table in ("model_proposal", "evaluation", "outcome", "backtest_snapshot", "backtest_run"):
        op.drop_table(table)
