"""asset.slug: one readable key per asset for every class (crypto: CoinGecko id; stocks: ticker-based)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("asset", sa.Column("slug", sa.String(200)))
    op.add_column("asset", sa.Column("country", sa.String(2)))
    op.add_column("asset", sa.Column("sector", sa.String(60)))
    op.execute("UPDATE asset SET slug = coingecko_id WHERE slug IS NULL AND coingecko_id IS NOT NULL")
    op.create_unique_constraint("uq_asset_slug", "asset", ["slug"])


def downgrade() -> None:
    op.drop_constraint("uq_asset_slug", "asset")
    op.drop_column("asset", "sector")
    op.drop_column("asset", "country")
    op.drop_column("asset", "slug")
