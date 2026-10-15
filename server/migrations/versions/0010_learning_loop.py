"""learning loop (chapter 8 and 9): model activations, challengers, qualitative assessments

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    # Which model version is active, and since when. The latest row wins. Append-only: a rollback is a new row.
    op.create_table(
        "model_activation",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("model_version_id", sa.Integer, sa.ForeignKey("model_version.id"), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),        # baseline | promote | rollback
        sa.Column("proposal_id", sa.Integer, sa.ForeignKey("model_proposal.id")),
        sa.Column("note", sa.Text),
        sa.Column("activated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.execute("CREATE TRIGGER model_activation_append_only BEFORE UPDATE OR DELETE ON model_activation "
               "FOR EACH ROW EXECUTE FUNCTION forbid_change();")
    op.create_table(
        "challenger",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("model_version_id", sa.Integer, sa.ForeignKey("model_version.id"), nullable=False, unique=True),
        sa.Column("champion_version_id", sa.Integer, sa.ForeignKey("model_version.id"), nullable=False),
        sa.Column("proposal_id", sa.Integer, sa.ForeignKey("model_proposal.id")),
        sa.Column("status", sa.String(12), nullable=False),       # shadow | promoted | retired
        sa.Column("started_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("ended_at", TS),
        sa.Column("checks", JSONB),                                # last promotion check
        sa.Column("checked_at", TS),
    )
    op.add_column("model_proposal", sa.Column("source", sa.String(12), nullable=False, server_default="model"))
    op.add_column("model_proposal", sa.Column("refusal", JSONB))   # guardrail violations when refused
    op.create_table(
        "qualitative_assessment",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("asset.id"), nullable=False, index=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("source_name", sa.Text, nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("rubrics", JSONB, nullable=False),
        sa.Column("red_flags", JSONB, nullable=False),
        sa.Column("rejected_quotes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("llm_call_id", sa.BigInteger, sa.ForeignKey("llm_call.id")),
    )
    op.execute("CREATE TRIGGER qualitative_assessment_append_only BEFORE UPDATE OR DELETE ON qualitative_assessment "
               "FOR EACH ROW EXECUTE FUNCTION forbid_change();")


def downgrade() -> None:
    op.drop_table("qualitative_assessment")
    op.drop_column("model_proposal", "refusal")
    op.drop_column("model_proposal", "source")
    op.drop_table("challenger")
    op.drop_table("model_activation")
