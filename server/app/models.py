from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ModelVersion(Base):
    """Every model configuration that was ever loaded. Rows are never updated."""

    __tablename__ = "model_version"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(32), unique=True)
    config_hash: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- Phase 1: data layer -------------------------------------------------------------------------
# Every row with market data carries `source` and `fetched_at`; most also point to the provider call
# whose raw response produced it (`call_id`).



class JobRun(Base):
    __tablename__ = "job_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(40))
    trigger: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))  # running | ok | partial | failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)


class ProviderCallLog(Base):
    """One row per HTTP call to a provider. Append-only; the basis for budgets and the usage page."""

    __tablename__ = "provider_call_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    endpoint: Mapped[str] = mapped_column(String(200))
    params: Mapped[dict | None] = mapped_column(JSONB)
    status_code: Mapped[int | None] = mapped_column(Integer)
    ok: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text)
    cost: Mapped[int] = mapped_column(Integer, default=1)
    response_bytes: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    job_run_id: Mapped[int | None] = mapped_column(ForeignKey("job_run.id"))


class ProviderResponse(Base):
    """Raw response body (gzip) next to the normalised rows; pruned after the provider's retention."""

    __tablename__ = "provider_response"

    call_id: Mapped[int] = mapped_column(ForeignKey("provider_call_log.id"), primary_key=True)
    content_type: Mapped[str | None] = mapped_column(String(100))
    body_gzip: Mapped[bytes] = mapped_column(LargeBinary)


class Asset(Base):
    __tablename__ = "asset"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(20), index=True)  # crypto | stock | etf | ...
    symbol: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    coingecko_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    slug: Mapped[str | None] = mapped_column(String(200), unique=True)   # key in URLs and the API
    country: Mapped[str | None] = mapped_column(String(2))
    sector: Mapped[str | None] = mapped_column(String(60))
    categories: Mapped[list | None] = mapped_column(JSONB)
    template_override: Mapped[str | None] = mapped_column(String(40))
    price_sources: Mapped[list | None] = mapped_column(JSONB)  # preference order, e.g. ["binance", ...]
    tracked: Mapped[bool] = mapped_column(Boolean, default=False)  # prices kept up to date
    tracked_since: Mapped[date | None] = mapped_column(Date)
    meta_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mapping_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssetAlias(Base):
    """Identifiers of an asset at other sources: venue symbols, contract addresses, ISINs."""

    __tablename__ = "asset_alias"
    __table_args__ = (UniqueConstraint("kind", "value"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    value: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UniverseMembership(Base):
    """Daily snapshot of a list, including excluded coins and coins that later disappear."""

    __tablename__ = "universe_membership"

    universe: Mapped[str] = mapped_column(String(40), primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), primary_key=True)
    rank: Mapped[int | None] = mapped_column(Integer)
    market_cap_eur: Mapped[float | None] = mapped_column(Numeric)
    included: Mapped[bool] = mapped_column(Boolean)
    exclusion: Mapped[str | None] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(40))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    call_id: Mapped[int | None] = mapped_column(ForeignKey("provider_call_log.id"))


class PriceBar(Base):
    """Completed bars in the venue's own quote currency. Euro values come from view price_bar_eur."""

    __tablename__ = "price_bar"

    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), primary_key=True)
    interval: Mapped[str] = mapped_column(String(4), primary_key=True)
    ts: Mapped[date] = mapped_column(Date, primary_key=True)  # the day the bar closes (UTC)
    source: Mapped[str] = mapped_column(String(40), primary_key=True)
    open: Mapped[float | None] = mapped_column(Numeric)
    high: Mapped[float | None] = mapped_column(Numeric)
    low: Mapped[float | None] = mapped_column(Numeric)
    close: Mapped[float] = mapped_column(Numeric)
    volume: Mapped[float | None] = mapped_column(Numeric)
    quote_currency: Mapped[str] = mapped_column(String(10))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    call_id: Mapped[int | None] = mapped_column(ForeignKey("provider_call_log.id"))


class FundamentalFact(Base):
    """Point-in-time facts. Append-only: a revised value is a new row with a later available_at."""

    __tablename__ = "fundamental_fact"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"))
    field: Mapped[str] = mapped_column(String(60))
    as_of: Mapped[date] = mapped_column(Date)
    value: Mapped[float] = mapped_column(Numeric)
    unit: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(40))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    call_id: Mapped[int | None] = mapped_column(ForeignKey("provider_call_log.id"))


class FxRate(Base):
    """ECB reference rates: 1 unit of `base` = `rate` units of `quote`."""

    __tablename__ = "fx_rate"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    base: Mapped[str] = mapped_column(String(3), primary_key=True)
    quote: Mapped[str] = mapped_column(String(3), primary_key=True)
    source: Mapped[str] = mapped_column(String(40), primary_key=True)
    rate: Mapped[float] = mapped_column(Numeric)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    call_id: Mapped[int | None] = mapped_column(ForeignKey("provider_call_log.id"))


class MacroObservation(Base):
    """Macro series (FRED). Append-only like fundamental_fact."""

    __tablename__ = "macro_observation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    series_id: Mapped[str] = mapped_column(String(60))
    date: Mapped[date] = mapped_column(Date)
    value: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(40))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    call_id: Mapped[int | None] = mapped_column(ForeignKey("provider_call_log.id"))


class GradeSnapshot(Base):
    """One grade per asset, day and model version. Append-only: the record of what the model said."""

    __tablename__ = "grade_snapshot"
    __table_args__ = (UniqueConstraint("asset_id", "as_of", "model_version_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"))
    as_of: Mapped[date] = mapped_column(Date)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_version.id"))
    template_id: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    score: Mapped[float | None] = mapped_column(Float)
    quality: Mapped[float | None] = mapped_column(Float)
    timing: Mapped[float | None] = mapped_column(Float)
    coverage: Mapped[float] = mapped_column(Float)
    letter: Mapped[str | None] = mapped_column(String(3))
    peg_safety: Mapped[int | None] = mapped_column(Integer)
    price_eur: Mapped[float | None] = mapped_column(Float)
    knowledge_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    inputs: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WatchlistItem(Base):
    __tablename__ = "watchlist_item"

    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MarketRegime(Base):
    """Daily market regime (chapter 5) with the three inputs it was decided on. Append-only."""

    __tablename__ = "market_regime"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_version.id"), primary_key=True)
    state: Mapped[str | None] = mapped_column(String(12))
    score: Mapped[int | None] = mapped_column(Integer)
    week_end: Mapped[date] = mapped_column(Date)
    inputs: Mapped[dict] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BacktestSnapshot(Base):
    """A grade recomputed for a past month-end with only the data known then (chapter 8). Never live."""

    __tablename__ = "backtest_snapshot"
    __table_args__ = (UniqueConstraint("run_id", "asset_id", "as_of"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_run.id"))
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id"))
    as_of: Mapped[date] = mapped_column(Date)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_version.id"))
    template_id: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    score: Mapped[float | None] = mapped_column(Float)
    quality: Mapped[float | None] = mapped_column(Float)
    timing: Mapped[float | None] = mapped_column(Float)
    coverage: Mapped[float] = mapped_column(Float)
    letter: Mapped[str | None] = mapped_column(String(3))
    peg_safety: Mapped[int | None] = mapped_column(Integer)
    price_eur: Mapped[float | None] = mapped_column(Float)
    knowledge_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    inputs: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict] = mapped_column(JSONB)
