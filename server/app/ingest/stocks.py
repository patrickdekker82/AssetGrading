"""Stock run (weekdays 22:30 UTC, after the US close).

Steps: ECB rates -> SEC company list and filing metadata -> assets (US candidates, AEX members,
benchmark indices) -> daily prices (Tiingo or EODHD when a key is set, else Yahoo) -> SEC company facts
when a new filing appeared or monthly -> market values and the US top list.
Every step is idempotent; a failure for one stock is reported and the run continues.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.grading.assign import assign_stock
from app.ingest.fx_macro import update_fx
from app.ingest.report import Report
from app.ingest.store import insert_facts, insert_membership, upsert_bars
from app.modelconfig import ModelConfig
from app.models import Asset, AssetAlias, FundamentalFact, PriceBar
from app.providers import Fact, ProviderError
from app.providers.config import ProvidersConfig
from app.providers.registry import Providers
from app.providers.stockprices import PriceSeries
from app.stocks_config import StocksConfig
from app.universes import Universes

US_UNIVERSE, AEX_UNIVERSE = "stocks_us", "stocks_aex"
KEYED_SOURCES = {"tiingo", "eodhd"}
RECHECK_TOLERANCE = Decimal("0.0005")    # 0.05%: a larger change of an old adjusted close means a split or dividend


@dataclass
class StockContext:
    sf: sessionmaker[Session]
    providers: Providers
    cfg: ProvidersConfig
    stocks: StocksConfig
    universes: Universes
    model: ModelConfig
    today: date
    report: Report
    only: set[int] | None = None
    last_filed: dict[int, str] | None = None   # asset id -> date of the newest filing (from this run)

    @property
    def price_start(self) -> date:
        return date.fromisoformat(self.stocks.prices.history_start)


def us_list_size(universes: Universes) -> int:
    tab = next(t for t in universes.tabs if t.slug == "stocks")
    return tab.size or 50


def run_stocks(sf: sessionmaker[Session], providers: Providers, cfg: ProvidersConfig, stocks: StocksConfig,
               universes: Universes, model: ModelConfig, today: date | None = None) -> Report:
    ctx = StockContext(sf, providers, cfg, stocks, universes, model, today or datetime.now(UTC).date(), Report(),
                       last_filed={})
    update_fx(sf, providers, cfg, ctx.report, ctx.today)
    try:
        sec_list = providers.get("sec").company_tickers()
    except ProviderError as exc:
        ctx.report.error(f"SEC company list: {exc}")
        sec_list = []
    if sec_list:
        sync_us_candidates(ctx, sec_list)
    sync_aex(ctx, sec_list)
    sync_benchmarks(ctx)
    update_prices(ctx)
    update_fundamentals(ctx)
    record_us_universe(ctx)
    record_aex_universe(ctx)
    return ctx.report


# --- assets -------------------------------------------------------------------------------------

def _set_alias(session: Session, asset_id: int, kind: str, value: str, source: str) -> None:
    existing = session.scalar(select(AssetAlias).where(AssetAlias.kind == kind, AssetAlias.value == value))
    if existing is None:
        session.add(AssetAlias(asset_id=asset_id, kind=kind, value=value, source=source))
    elif existing.asset_id != asset_id:
        existing.asset_id = asset_id


def aliases(session: Session, asset_id: int) -> dict[str, str]:
    return {k: v for k, v in session.execute(
        select(AssetAlias.kind, AssetAlias.value).where(AssetAlias.asset_id == asset_id))}


def _upsert_asset(session: Session, slug: str, **fields) -> tuple[Asset, bool]:
    asset = session.scalar(select(Asset).where(Asset.slug == slug))
    created = asset is None
    if created:
        asset = Asset(slug=slug, **fields)
        session.add(asset)
        session.flush()
    else:
        for k, v in fields.items():
            if v is not None:
                setattr(asset, k, v)
    return asset, created


def _apply_meta(ctx: StockContext, asset: Asset, meta: dict) -> None:
    sic = meta.get("sic")
    asset.categories = [f"sic:{sic}", meta.get("sic_description") or ""] if sic else asset.categories
    _, _, sector = assign_stock(asset.slug, sic, ctx.model.assignment)
    asset.sector = sector
    asset.meta_updated_at = datetime.now(UTC)


def sic_of(asset: Asset) -> int | None:
    for c in asset.categories or []:
        if isinstance(c, str) and c.startswith("sic:"):
            return int(c[4:])
    return None


def sync_us_candidates(ctx: StockContext, sec_list: list[dict]) -> None:
    """The largest SEC registrants that file a 10-K: candidates for the US list (ranked later by market value)."""
    seen: set[int] = set()
    candidates = []
    for row in sec_list:
        if row["cik"] in seen:
            continue  # a second share class of the same company
        seen.add(row["cik"])
        candidates.append(row)
        if len(candidates) >= ctx.stocks.us.candidates:
            break
    for row in candidates:
        sync_us_company(ctx, row)


def sync_us_company(ctx: StockContext, row: dict) -> int | None:
    """Create or update one US company from SEC metadata; None when it files no 10-K (or SEC fails)."""
    try:
        meta = ctx.providers.get("sec").submissions(row["cik"])
    except ProviderError as exc:
        ctx.report.error(f"SEC submissions {row['ticker']}: {exc}")
        return None
    forms = {f["form"] for f in meta["filings"]}
    if not forms & set(ctx.stocks.us.forms):
        ctx.report.add("us_skipped_no_10k")
        return None
    with ctx.sf() as session:
        slug = row["ticker"].lower()
        asset, created = _upsert_asset(
            session, slug, asset_class="stock", symbol=row["ticker"], name=meta["name"] or row["title"],
            country=(meta["country_code"] or "US")[:2] if meta["foreign"] else "US",
        )
        if created:
            asset.price_sources = _sources(ctx, "us")
            ctx.report.add("assets_created")
        asset.tracked = True
        asset.tracked_since = asset.tracked_since or ctx.today
        _apply_meta(ctx, asset, meta)
        _set_alias(session, asset.id, "sec_cik", str(row["cik"]), "sec")
        _set_alias(session, asset.id, "us_ticker", row["ticker"], "sec")
        _set_alias(session, asset.id, "yahoo_symbol", row["ticker"], "config")
        ctx.last_filed[asset.id] = _last_filing(meta)
        session.commit()
        return asset.id


def ingest_single_stock(sf: sessionmaker[Session], providers: Providers, cfg: ProvidersConfig, stocks: StocksConfig,
                        universes: Universes, model: ModelConfig, ticker: str) -> tuple[int | None, Report]:
    """Fetch one US stock on request (a 10-K filer outside the list): metadata, prices and SEC facts."""
    ctx = StockContext(sf, providers, cfg, stocks, universes, model, datetime.now(UTC).date(), Report(),
                       last_filed={})
    row = next((r for r in providers.get("sec").company_tickers() if r["ticker"] == ticker.upper()), None)
    if row is None:
        return None, ctx.report
    asset_id = sync_us_company(ctx, row)
    if asset_id is None:
        return None, ctx.report
    update_fx(sf, providers, cfg, ctx.report, ctx.today)
    sync_benchmarks(ctx)
    with sf() as session:
        bench_ids = set(session.scalars(select(Asset.id).where(Asset.asset_class == "index")))
    ctx.only = {asset_id} | bench_ids
    update_prices(ctx)
    update_fundamentals(ctx)
    return asset_id, ctx.report


def _last_filing(meta: dict) -> str:
    return max((f["filed"] for f in meta["filings"]), default="")


def sync_aex(ctx: StockContext, sec_list: list[dict]) -> None:
    by_ticker = {r["ticker"]: r for r in sec_list}
    sec = ctx.providers.get("sec")
    for m in ctx.stocks.aex.members:
        slug = f"{m.ticker.lower()}-as"
        country = m.country or (m.isin[:2] if m.isin else None)
        meta = None
        if m.sec_ticker and m.sec_ticker in by_ticker:
            try:
                meta = sec.submissions(by_ticker[m.sec_ticker]["cik"])
            except ProviderError as exc:
                ctx.report.error(f"SEC submissions {m.sec_ticker}: {exc}")
        with ctx.sf() as session:
            asset, created = _upsert_asset(session, slug, asset_class="stock", symbol=m.ticker, name=m.name,
                                           country=country)
            if created:
                asset.price_sources = _sources(ctx, "eu")
                ctx.report.add("assets_created")
            asset.tracked = True
            asset.tracked_since = asset.tracked_since or ctx.today
            if meta:
                _apply_meta(ctx, asset, meta)
                _set_alias(session, asset.id, "sec_cik", str(meta["cik"]), "sec")
                ctx.last_filed[asset.id] = _last_filing(meta)
            else:
                asset.sector = assign_stock(slug, None, ctx.model.assignment)[2]
            if m.isin:
                _set_alias(session, asset.id, "isin", m.isin, "config")
            _set_alias(session, asset.id, "euronext_ticker", m.ticker, "config")
            _set_alias(session, asset.id, "yahoo_symbol", m.yahoo, "config")
            session.commit()


def sync_benchmarks(ctx: StockContext) -> None:
    for b in (ctx.stocks.us.benchmark, ctx.stocks.aex.benchmark):
        with ctx.sf() as session:
            asset, created = _upsert_asset(session, b.slug, asset_class="index", symbol=b.yahoo, name=b.name)
            if created:
                asset.price_sources = ["yahoo"]
            asset.tracked = True
            asset.tracked_since = asset.tracked_since or ctx.today
            _set_alias(session, asset.id, "yahoo_symbol", b.yahoo, "config")
            session.commit()


def _sources(ctx: StockContext, region: str) -> list[str]:
    configured = ctx.stocks.prices.us_sources if region == "us" else ctx.stocks.prices.eu_sources
    return list(configured)


def _available(ctx: StockContext, source: str) -> bool:
    return source not in KEYED_SOURCES or bool(ctx.providers.get(source).api_key)


def stock_targets(ctx: StockContext, session: Session, classes=("stock", "index")) -> list[Asset]:
    assets = list(session.scalars(
        select(Asset).where(Asset.asset_class.in_(classes), Asset.tracked.is_(True)).order_by(Asset.id)))
    return [a for a in assets if a.id in ctx.only] if ctx.only is not None else assets


# --- prices -------------------------------------------------------------------------------------

def _symbol_for(source: str, al: dict[str, str]) -> str | None:
    yahoo = al.get("yahoo_symbol")
    if source == "yahoo":
        return yahoo
    if source == "tiingo":
        return al.get("us_ticker")
    if source == "eodhd":
        if al.get("us_ticker"):
            return f"{al['us_ticker'].replace('-', '.')}.US"
        if yahoo and yahoo.endswith(".AS"):
            return yahoo
    return None


def update_prices(ctx: StockContext) -> None:
    with ctx.sf() as session:
        work = [(a.id, a.slug, list(a.price_sources or ["yahoo"]), aliases(session, a.id))
                for a in stock_targets(ctx, session)]
    for asset_id, slug, sources, al in work:
        done = False
        for source in sources:
            if not _available(ctx, source):
                continue
            symbol = _symbol_for(source, al)
            if not symbol:
                continue
            try:
                _update_source(ctx, asset_id, source, symbol)
                done = True
                break
            except ProviderError as exc:
                ctx.report.add(f"price_errors_{source}")
                ctx.report.note_once(f"{source}: {exc}")
        if not done:
            ctx.report.error(f"geen koersen voor {slug}")


def _stored_closes(session: Session, asset_id: int, source: str, since: date) -> dict[date, Decimal]:
    return {ts: close for ts, close in session.execute(
        select(PriceBar.ts, PriceBar.close).where(PriceBar.asset_id == asset_id, PriceBar.source == source,
                                                  PriceBar.interval == "1d", PriceBar.ts >= since))}


def _update_source(ctx: StockContext, asset_id: int, source: str, symbol: str) -> None:
    update_adjusted_series(ctx.sf, ctx.providers.get(source), asset_id, source, symbol, ctx.price_start,
                           ctx.today, ctx.stocks.prices.recheck_days, ctx.report)


def update_adjusted_series(sf: sessionmaker[Session], provider, asset_id: int, source: str, symbol: str,
                           history_start: date, today: date, recheck_days: int, report: Report, *,
                           store_raw: bool = True, **series_kw) -> None:
    """Adjusted daily bars (and the closes as traded): new days, plus a full re-read when an adjusted close
    of the last `recheck_days` changed (a dividend or split since the last run)."""
    with sf() as session:
        last = session.scalar(select(func.max(PriceBar.ts)).where(
            PriceBar.asset_id == asset_id, PriceBar.source == source, PriceBar.interval == "1d"))
    if last is None:
        series = provider.series(symbol, history_start, today, **series_kw)
    else:
        since = last - timedelta(days=recheck_days)
        series = provider.series(symbol, since, today, **series_kw)
        with sf() as session:
            stored = _stored_closes(session, asset_id, source, since)
        if _adjustment_changed(stored, series):
            report.add("price_history_readjusted")
            series = provider.series(symbol, history_start, today, **series_kw)
    fetched_at = datetime.now(UTC)
    with sf() as session:
        report.add("bars_written", upsert_bars(session, asset_id, source, series.bars, fetched_at))
        if store_raw:
            facts = [Fact(field="close_raw", as_of=d, value=v, unit=series.currency, call_id=series.call_id)
                     for d, v in series.raw_closes]
            report.add("facts_added", insert_facts(session, asset_id, source, facts, fetched_at))
        session.commit()


def _adjustment_changed(stored: dict[date, Decimal], series: PriceSeries) -> bool:
    for b in series.bars:
        old = stored.get(b.ts)
        if old is not None and old != 0 and abs(b.close / old - 1) > RECHECK_TOLERANCE:
            return True
    return False


# --- fundamentals -------------------------------------------------------------------------------

def update_fundamentals(ctx: StockContext) -> None:
    """Company facts from SEC: after every new filing, and at least every `refresh_days`."""
    sec = ctx.providers.get("sec")
    start = date.fromisoformat(ctx.stocks.fundamentals.history_start)
    refresh = timedelta(days=ctx.stocks.fundamentals.refresh_days)
    now = datetime.now(UTC)
    with ctx.sf() as session:
        work = []
        for a in stock_targets(ctx, session, ("stock",)):
            al = aliases(session, a.id)
            if "sec_cik" not in al:
                continue
            last_fetch = session.scalar(select(func.max(FundamentalFact.fetched_at)).where(
                FundamentalFact.asset_id == a.id, FundamentalFact.source == "sec"))
            last_filed = (ctx.last_filed or {}).get(a.id, "")
            new_filing = bool(last_filed) and (last_fetch is None or last_filed >= last_fetch.date().isoformat())
            if last_fetch is None or new_filing or now - last_fetch > refresh:
                work.append((a.id, a.slug, al["sec_cik"]))
    for asset_id, slug, cik in work:
        try:
            facts = sec.get_fundamentals(cik, start)
        except ProviderError as exc:
            ctx.report.error(f"SEC company facts {slug}: {exc}")
            continue
        with ctx.sf() as session:
            ctx.report.add("fundamental_facts_added", insert_facts(session, asset_id, "sec", facts, datetime.now(UTC)))
            session.commit()
        ctx.report.add("company_facts_fetched")


# --- market value and lists ---------------------------------------------------------------------

def market_values_eur(ctx: StockContext, as_of: date, knowledge: datetime) -> dict[int, float]:
    """Market value in euro per stock, computed exactly as the grading does (share count checked against
    net income per share, manual share counts, Berkshire's share classes)."""
    from app.grading.stocks import fact_table, load_stock_data, market_value

    with ctx.sf() as session:
        data = load_stock_data(session, ctx.stocks, as_of, knowledge)
    out = {}
    for s in data.stocks:
        df = data.facts.get(s.id)
        if df is None or df.empty:
            continue
        mv = market_value(data, s, fact_table(df), df, as_of)
        if mv.value is not None:
            eur = data.convert(mv.value, mv.report_ccy, "EUR", as_of)
            if eur is not None:
                out[s.id] = eur
    return out


def record_us_universe(ctx: StockContext) -> None:
    size = us_list_size(ctx.universes)
    fetched_at = datetime.now(UTC)
    with ctx.sf() as session:
        us = [a for a in stock_targets(ctx, session, ("stock",)) if "us_ticker" in aliases(session, a.id)]
        values = market_values_eur(ctx, ctx.today, fetched_at)
        ranked = sorted(us, key=lambda a: -(values.get(a.id) or 0))
        rows = []
        for rank, a in enumerate(ranked, start=1):
            mv = values.get(a.id)
            exclusion = None if mv else "no_market_value"
            rows.append({
                "universe": US_UNIVERSE, "as_of": ctx.today, "asset_id": a.id, "rank": rank if mv else None,
                "market_cap_eur": mv, "included": mv is not None and rank <= size, "exclusion": exclusion,
                "source": "sec", "fetched_at": fetched_at, "call_id": None,
            })
        ctx.report.add("membership_added", insert_membership(session, rows))
        session.commit()


def record_aex_universe(ctx: StockContext) -> None:
    fetched_at = datetime.now(UTC)
    slugs = [f"{m.ticker.lower()}-as" for m in ctx.stocks.aex.members]
    with ctx.sf() as session:
        assets = {a.slug: a for a in session.scalars(select(Asset).where(Asset.slug.in_(slugs)))}
        values = market_values_eur(ctx, ctx.today, fetched_at)
        rows = [{
            "universe": AEX_UNIVERSE, "as_of": ctx.today, "asset_id": assets[s].id, "rank": i,
            "market_cap_eur": values.get(assets[s].id), "included": True, "exclusion": None,
            "source": "config", "fetched_at": fetched_at, "call_id": None,
        } for i, s in enumerate(slugs, start=1) if s in assets]
        ctx.report.add("membership_added", insert_membership(session, rows))
        session.commit()
