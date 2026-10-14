"""market_regime (append-only) and euro conversion for every ECB currency

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)

PRICE_DAILY_EUR = """
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


def upgrade() -> None:
    op.create_table(
        "market_regime",
        sa.Column("date", sa.Date, primary_key=True),
        sa.Column("model_version_id", sa.Integer, sa.ForeignKey("model_version.id"), primary_key=True),
        sa.Column("state", sa.String(12)),           # risk_on | neutral | risk_off; NULL = too few inputs
        sa.Column("score", sa.Integer),              # sum of the input votes
        sa.Column("week_end", sa.Date, nullable=False),  # the completed week the inputs were read from
        sa.Column("inputs", JSONB, nullable=False),
        sa.Column("computed_at", TS, nullable=False),
    )
    op.execute(
        "CREATE TRIGGER market_regime_append_only BEFORE UPDATE OR DELETE ON market_regime "
        "FOR EACH ROW EXECUTE FUNCTION forbid_change();"
    )
    # Every quote currency the ECB publishes (indices in JPY, GBP, ...) gets a euro value, not only USD.
    op.execute("DROP VIEW price_daily_eur;")
    op.execute("DROP VIEW price_bar_eur;")
    op.execute(
        """
        CREATE VIEW price_bar_eur AS
        SELECT b.asset_id, b.interval, b.ts, b.source, b.quote_currency,
               b.close AS close_native,
               b.close * f.factor AS close_eur,
               b.open * f.factor AS open_eur,
               b.high * f.factor AS high_eur,
               b.low * f.factor AS low_eur,
               b.volume
        FROM price_bar b
        LEFT JOIN LATERAL (
            SELECT r.rate FROM fx_rate r
            WHERE r.base = 'EUR' AND r.quote = CASE WHEN b.quote_currency = 'USDT' THEN 'USD'
                                                    ELSE b.quote_currency END
              AND r.date <= b.ts
            ORDER BY r.date DESC LIMIT 1
        ) fx ON b.quote_currency <> 'EUR'
        LEFT JOIN LATERAL (
            SELECT p.close FROM price_bar p
            JOIN asset a ON a.id = p.asset_id AND a.coingecko_id = 'tether'
            WHERE p.source = 'coinbase' AND p.interval = b.interval AND p.ts = b.ts AND p.quote_currency = 'USD'
        ) usdt ON b.quote_currency = 'USDT'
        CROSS JOIN LATERAL (
            SELECT CASE
                WHEN b.quote_currency = 'EUR' THEN 1::numeric
                WHEN b.quote_currency = 'USDT' THEN usdt.close / fx.rate
                ELSE 1 / fx.rate
            END AS factor
        ) f;
        """
    )
    op.execute(PRICE_DAILY_EUR)


def downgrade() -> None:
    op.execute("DROP VIEW price_daily_eur;")
    op.execute("DROP VIEW price_bar_eur;")
    op.execute(
        """
        CREATE VIEW price_bar_eur AS
        SELECT b.asset_id, b.interval, b.ts, b.source, b.quote_currency,
               b.close AS close_native, b.close * f.factor AS close_eur, b.open * f.factor AS open_eur,
               b.high * f.factor AS high_eur, b.low * f.factor AS low_eur, b.volume
        FROM price_bar b
        LEFT JOIN LATERAL (
            SELECT r.rate FROM fx_rate r WHERE r.base = 'EUR' AND r.quote = 'USD' AND r.date <= b.ts
            ORDER BY r.date DESC LIMIT 1
        ) usd ON true
        LEFT JOIN LATERAL (
            SELECT p.close FROM price_bar p
            JOIN asset a ON a.id = p.asset_id AND a.coingecko_id = 'tether'
            WHERE p.source = 'coinbase' AND p.interval = b.interval AND p.ts = b.ts AND p.quote_currency = 'USD'
        ) usdt ON true
        CROSS JOIN LATERAL (
            SELECT CASE b.quote_currency WHEN 'EUR' THEN 1::numeric WHEN 'USD' THEN 1 / usd.rate
                WHEN 'USDT' THEN usdt.close / usd.rate END AS factor
        ) f;
        """
    )
    op.execute(PRICE_DAILY_EUR)
    op.execute("DROP TABLE market_regime;")
