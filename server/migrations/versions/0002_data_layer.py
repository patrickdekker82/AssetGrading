"""data layer: assets, aliases, universe, prices, facts, fx, macro, provider calls, job runs

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APPEND_ONLY = ["provider_call_log", "universe_membership", "fundamental_fact", "macro_observation"]

TS = sa.DateTime(timezone=True)


def call_fk() -> sa.Column:
    return sa.Column("call_id", sa.BigInteger, sa.ForeignKey("provider_call_log.id"))


def upgrade() -> None:
    op.create_table(
        "job_run",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job", sa.String(40), nullable=False),
        sa.Column("trigger", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", TS, nullable=False),
        sa.Column("finished_at", TS),
        sa.Column("summary", JSONB),
        sa.Column("error", sa.Text),
    )
    op.create_index("ix_job_run_job_started", "job_run", ["job", "started_at"])

    op.create_table(
        "provider_call_log",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("endpoint", sa.String(200), nullable=False),
        sa.Column("params", JSONB),
        sa.Column("status_code", sa.Integer),
        sa.Column("ok", sa.Boolean, nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("cost", sa.Integer, nullable=False, server_default="1"),
        sa.Column("response_bytes", sa.Integer),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("started_at", TS, nullable=False),
        sa.Column("job_run_id", sa.Integer, sa.ForeignKey("job_run.id")),
    )
    op.create_index("ix_provider_call_log_provider_started", "provider_call_log", ["provider", "started_at"])

    op.create_table(
        "provider_response",
        sa.Column("call_id", sa.BigInteger, sa.ForeignKey("provider_call_log.id"), primary_key=True),
        sa.Column("content_type", sa.String(100)),
        sa.Column("body_gzip", sa.LargeBinary, nullable=False),
    )

    op.create_table(
        "asset",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_class", sa.String(20), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("coingecko_id", sa.String(200), unique=True),
        sa.Column("categories", JSONB),
        sa.Column("template_override", sa.String(40)),
        sa.Column("price_sources", JSONB),
        sa.Column("tracked", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("tracked_since", sa.Date),
        sa.Column("meta_updated_at", TS),
        sa.Column("mapping_checked_at", TS),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_asset_asset_class", "asset", ["asset_class"])

    op.create_table(
        "asset_alias",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("asset.id"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("value", sa.String(200), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("kind", "value"),
    )
    op.create_index("ix_asset_alias_asset_id", "asset_alias", ["asset_id"])

    op.create_table(
        "universe_membership",
        sa.Column("universe", sa.String(40), primary_key=True),
        sa.Column("as_of", sa.Date, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("asset.id"), primary_key=True),
        sa.Column("rank", sa.Integer),
        sa.Column("market_cap_eur", sa.Numeric),
        sa.Column("included", sa.Boolean, nullable=False),
        sa.Column("exclusion", sa.String(40)),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("fetched_at", TS, nullable=False),
        call_fk(),
    )

    op.create_table(
        "price_bar",
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("asset.id"), primary_key=True),
        sa.Column("interval", sa.String(4), primary_key=True),
        sa.Column("ts", sa.Date, primary_key=True),
        sa.Column("source", sa.String(40), primary_key=True),
        sa.Column("open", sa.Numeric),
        sa.Column("high", sa.Numeric),
        sa.Column("low", sa.Numeric),
        sa.Column("close", sa.Numeric, nullable=False),
        sa.Column("volume", sa.Numeric),
        sa.Column("quote_currency", sa.String(10), nullable=False),
        sa.Column("fetched_at", TS, nullable=False),
        call_fk(),
    )
    op.create_index("ix_price_bar_source_last", "price_bar", ["asset_id", "source", "interval", "ts"])

    op.create_table(
        "fundamental_fact",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("asset.id"), nullable=False),
        sa.Column("field", sa.String(60), nullable=False),
        sa.Column("as_of", sa.Date, nullable=False),
        sa.Column("value", sa.Numeric, nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("available_at", TS, nullable=False),
        sa.Column("fetched_at", TS, nullable=False),
        call_fk(),
    )
    op.create_index(
        "ix_fundamental_fact_lookup", "fundamental_fact", ["asset_id", "field", "source", "as_of", "available_at"]
    )

    op.create_table(
        "fx_rate",
        sa.Column("date", sa.Date, primary_key=True),
        sa.Column("base", sa.String(3), primary_key=True),
        sa.Column("quote", sa.String(3), primary_key=True),
        sa.Column("source", sa.String(40), primary_key=True),
        sa.Column("rate", sa.Numeric, nullable=False),
        sa.Column("fetched_at", TS, nullable=False),
        call_fk(),
    )
    op.create_index("ix_fx_rate_asof", "fx_rate", ["base", "quote", "date"])

    op.create_table(
        "macro_observation",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("series_id", sa.String(60), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("available_at", TS, nullable=False),
        sa.Column("fetched_at", TS, nullable=False),
        call_fk(),
    )
    op.create_index("ix_macro_observation_lookup", "macro_observation", ["series_id", "source", "date", "available_at"])

    for table in APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_change();"
        )

    # Daily bars converted to euro with ECB reference rates (the last rate on or before the bar date).
    # USDT is first converted to USD with Coinbase's USDT-USD close of the same day; when that is
    # missing the euro value stays empty rather than assuming 1 USDT = 1 USD.
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
            WHERE r.base = 'EUR' AND r.quote = 'USD' AND r.date <= b.ts
            ORDER BY r.date DESC LIMIT 1
        ) usd ON true
        LEFT JOIN LATERAL (
            SELECT p.close FROM price_bar p
            JOIN asset a ON a.id = p.asset_id AND a.coingecko_id = 'tether'
            WHERE p.source = 'coinbase' AND p.interval = b.interval AND p.ts = b.ts AND p.quote_currency = 'USD'
        ) usdt ON true
        CROSS JOIN LATERAL (
            SELECT CASE b.quote_currency
                WHEN 'EUR' THEN 1::numeric
                WHEN 'USD' THEN 1 / usd.rate
                WHEN 'USDT' THEN usdt.close / usd.rate
            END AS factor
        ) f;
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW price_bar_eur;")
    for table in APPEND_ONLY:
        op.execute(f"DROP TRIGGER {table}_append_only ON {table};")
    for table in [
        "macro_observation", "fx_rate", "fundamental_fact", "price_bar", "universe_membership",
        "asset_alias", "asset", "provider_response", "provider_call_log", "job_run",
    ]:
        op.drop_table(table)
