"""insider filings (SEC Form 4) and news items (Marketaux)

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One row per Form 4 filing and reporting owner: the open-market purchases and sales in it. Point in time:
    # `filed_at` is when the filing became public (acceptance time, or the end of the filing day for the
    # quarterly SEC data sets).
    op.create_table(
        "insider_filing",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("asset.id"), nullable=False),
        sa.Column("accession", sa.String(25), nullable=False),
        sa.Column("owner_cik", sa.String(12), nullable=False),
        sa.Column("owner_name", sa.Text),
        sa.Column("is_director", sa.Boolean, nullable=False),
        sa.Column("is_officer", sa.Boolean, nullable=False),
        sa.Column("is_ten_pct", sa.Boolean, nullable=False),
        sa.Column("plan_10b5_1", sa.Boolean),                    # null: not stated (forms before April 2023)
        sa.Column("first_trade", sa.Date),
        sa.Column("last_trade", sa.Date),
        sa.Column("purchase_shares", sa.Numeric, nullable=False),
        sa.Column("purchase_value", sa.Numeric, nullable=False),  # US dollars
        sa.Column("sale_shares", sa.Numeric, nullable=False),
        sa.Column("sale_value", sa.Numeric, nullable=False),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(12), nullable=False),      # sec_bulk | sec_form4
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("call_id", sa.BigInteger),
        sa.UniqueConstraint("accession", "owner_cik", name="uq_insider_filing"),
    )
    op.create_index("ix_insider_filing_asset", "insider_filing", ["asset_id", "filed_at"])
    op.execute("CREATE TRIGGER insider_filing_append_only BEFORE UPDATE OR DELETE ON insider_filing "
               "FOR EACH ROW EXECUTE FUNCTION forbid_change();")

    # Which quarterly SEC data sets were read (history before the Form 4 filings fetched one by one).
    op.create_table(
        "insider_dataset",
        sa.Column("quarter", sa.String(6), primary_key=True),     # e.g. 2024q1
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("filings", sa.Integer, nullable=False),
    )

    op.create_table(
        "news_item",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("asset.id"), nullable=False),
        sa.Column("uuid", sa.String(64), nullable=False),        # the provider's id of the article
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("url", sa.Text),
        sa.Column("source_name", sa.Text),
        sa.Column("sentiment", sa.Float),                         # the provider's entity sentiment, -1..1
        sa.Column("source", sa.String(20), nullable=False),      # marketaux
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("call_id", sa.BigInteger),
        sa.UniqueConstraint("asset_id", "uuid", name="uq_news_item"),
    )
    op.create_index("ix_news_item_asset", "news_item", ["asset_id", "published_at"])
    op.execute("CREATE TRIGGER news_item_append_only BEFORE UPDATE OR DELETE ON news_item "
               "FOR EACH ROW EXECUTE FUNCTION forbid_change();")


def downgrade() -> None:
    op.drop_table("news_item")
    op.drop_table("insider_dataset")
    op.drop_table("insider_filing")
