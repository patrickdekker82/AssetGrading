"""price_daily_eur: one daily euro close per asset, from the most preferred source that has it

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-11
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The order in asset.price_sources is the preference; a day missing at the first source is taken
    # from the next. `source` tells which one was used for each day.
    op.execute(
        """
        CREATE VIEW price_daily_eur AS
        SELECT DISTINCT ON (e.asset_id, e.ts)
               e.asset_id, e.ts, e.source, e.quote_currency, e.close_native,
               e.close_eur, e.open_eur, e.high_eur, e.low_eur, e.volume
        FROM price_bar_eur e
        JOIN asset a ON a.id = e.asset_id
        WHERE e.interval = '1d' AND e.close_eur IS NOT NULL
        ORDER BY e.asset_id, e.ts,
                 COALESCE(array_position(ARRAY(SELECT jsonb_array_elements_text(a.price_sources)), e.source), 99);
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW price_daily_eur;")
