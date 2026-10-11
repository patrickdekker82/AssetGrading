"""Nightly crypto run (00:05 UTC).

Steps: ECB rates -> CoinGecko top list and exclusions -> assets and daily membership -> market facts ->
metadata and source mapping (monthly) -> daily price bars with fallback -> DefiLlama and Coin Metrics.
Every step is idempotent; a failure for one asset is reported and the run continues.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.ingest.fx_macro import update_fx
from app.ingest.report import Report
from app.ingest.store import insert_bars, insert_facts, insert_membership, last_bar_date, last_fact_date
from app.models import Asset, AssetAlias, FxRate, PriceBar
from app.providers import ProviderError
from app.providers.coingecko import CoinGeckoProvider
from app.providers.config import ProvidersConfig
from app.providers.registry import Providers
from app.universes import Universes

UNIVERSE = "crypto_top"
VENUE_ALIAS = {"binance": "binance_symbol", "coinbase": "coinbase_product"}
DEFILLAMA_SKIP_CATEGORIES = {"CEX", "Treasury"}


@dataclass
class CryptoContext:
    sf: sessionmaker[Session]
    providers: Providers
    cfg: ProvidersConfig
    universes: Universes
    today: date
    report: Report

    @property
    def yesterday(self) -> date:
        return self.today - timedelta(days=1)

    @property
    def history_start(self) -> date:
        return date.fromisoformat(self.cfg.crypto.history_start)


def run_crypto(sf: sessionmaker[Session], providers: Providers, cfg: ProvidersConfig, universes: Universes,
               today: date | None = None) -> Report:
    ctx = CryptoContext(sf, providers, cfg, universes, today or datetime.now(UTC).date(), Report())
    update_fx(sf, providers, cfg, ctx.report, ctx.today)
    try:
        rows, exclusions, call_id = fetch_market_list(ctx)
    except ProviderError as exc:
        # Without the list we still update prices of assets we already follow.
        ctx.report.error(f"coingecko markets: {exc}")
        rows, exclusions, call_id = [], {}, None
    market_rows = {r["id"]: r for r in rows}
    if rows:
        record_universe(ctx, rows, exclusions, call_id)
    refresh_metadata(ctx)
    map_sources(ctx, market_rows)
    update_prices(ctx)
    update_defillama(ctx)
    update_coinmetrics(ctx)
    return ctx.report


# --- list and membership -------------------------------------------------------------------------

def fetch_market_list(ctx: CryptoContext) -> tuple[list[dict], dict[str, str], int | None]:
    cg = ctx.providers.coingecko
    res = cg.markets(per_page=ctx.cfg.crypto.markets_page_size)
    exclusions: dict[str, str] = {}
    for category, label in ctx.cfg.crypto.excluded_categories.items():
        cat = cg.markets(per_page=250, category=category)
        for row in cat.data:
            exclusions.setdefault(row["id"], label)
    ctx.report.add("market_rows", len(res.data))
    return res.data, exclusions, res.call_id


def crypto_list_size(universes: Universes) -> int:
    tab = next(t for t in universes.tabs if t.slug == "crypto")
    return tab.size or 50


def record_universe(ctx: CryptoContext, rows: list[dict], exclusions: dict[str, str], call_id: int | None) -> None:
    size = crypto_list_size(ctx.universes)
    fetched_at = datetime.now(UTC)
    with ctx.sf() as session:
        assets = {a.coingecko_id: a for a in session.scalars(select(Asset).where(Asset.asset_class == "crypto"))}
        included_count = stable_count = 0
        membership = []
        for row in rows:
            asset = assets.get(row["id"])
            if asset is None:
                asset = Asset(asset_class="crypto", coingecko_id=row["id"], symbol=row["symbol"].upper(),
                              name=row["name"], price_sources=None)
                session.add(asset)
                session.flush()
                assets[row["id"]] = asset
                ctx.report.add("assets_created")
            else:
                asset.symbol, asset.name = row["symbol"].upper(), row["name"]
            exclusion = exclusions.get(row["id"])
            if row.get("market_cap") in (None, 0):
                exclusion = exclusion or "no_market_cap"
            included = exclusion is None and included_count < size
            included_count += included
            track_stable = exclusion == "stablecoin" and stable_count < ctx.cfg.crypto.track_stablecoins
            stable_count += exclusion == "stablecoin"
            if (included or track_stable) and not asset.tracked:
                asset.tracked, asset.tracked_since = True, ctx.today
                ctx.report.add("assets_newly_tracked")
            membership.append({
                "universe": UNIVERSE, "as_of": ctx.today, "asset_id": asset.id, "rank": row.get("market_cap_rank"),
                "market_cap_eur": row.get("market_cap"), "included": included, "exclusion": exclusion,
                "source": "coingecko", "fetched_at": fetched_at, "call_id": call_id,
            })
            if asset.tracked:
                facts = CoinGeckoProvider.market_facts(row, ctx.today, call_id)
                ctx.report.add("facts_added", insert_facts(session, asset.id, "coingecko", facts, fetched_at,
                                                           snapshot=True))
        ctx.report.add("membership_added", insert_membership(session, membership))
        session.commit()


# --- metadata and mapping ------------------------------------------------------------------------

def _stale(moment: datetime | None, days: int, now: datetime) -> bool:
    return moment is None or now - moment > timedelta(days=days)


def tracked_assets(session: Session) -> list[Asset]:
    return list(session.scalars(
        select(Asset).where(Asset.asset_class == "crypto", Asset.tracked.is_(True)).order_by(Asset.id)
    ))


def refresh_metadata(ctx: CryptoContext) -> None:
    """Categories and contract addresses from CoinGecko, refreshed monthly."""
    now = datetime.now(UTC)
    with ctx.sf() as session:
        days = ctx.cfg.crypto.metadata_refresh_days
        todo = [a for a in tracked_assets(session) if _stale(a.meta_updated_at, days, now)]
        for asset in todo:
            try:
                res = ctx.providers.coingecko.coin_detail(asset.coingecko_id)
            except ProviderError as exc:
                ctx.report.error(f"metadata {asset.coingecko_id}: {exc}")
                continue
            asset.categories = [c for c in res.data.get("categories") or [] if c]
            for platform, address in (res.data.get("platforms") or {}).items():
                if platform and address:
                    _set_alias(session, asset.id, f"contract:{platform}", address, "coingecko")
            asset.meta_updated_at = now
            ctx.report.add("metadata_refreshed")
            session.commit()


def _set_alias(session: Session, asset_id: int, kind: str, value: str, source: str) -> bool:
    """Add an alias unless another asset already owns it. Returns whether the alias is this asset's."""
    owner = session.scalar(select(AssetAlias).where(AssetAlias.kind == kind, AssetAlias.value == value))
    if owner is not None:
        return owner.asset_id == asset_id
    session.add(AssetAlias(asset_id=asset_id, kind=kind, value=value, source=source))
    session.flush()
    return True


def _aliases(session: Session, asset_id: int) -> dict[str, str]:
    return {a.kind: a.value for a in session.scalars(select(AssetAlias).where(AssetAlias.asset_id == asset_id))}


def latest_eur_per_usd(session: Session) -> Decimal | None:
    rate = session.scalar(
        select(FxRate.rate).where(FxRate.base == "EUR", FxRate.quote == "USD").order_by(FxRate.date.desc()).limit(1)
    )
    return 1 / Decimal(rate) if rate else None


def map_sources(ctx: CryptoContext, market_rows: dict[str, dict]) -> None:
    """Link each tracked coin to its Binance and Coinbase symbols, after a price sanity check."""
    now = datetime.now(UTC)
    with ctx.sf() as session:
        todo = [a for a in tracked_assets(session)
                if a.coingecko_id in market_rows
                and _stale(a.mapping_checked_at, ctx.cfg.crypto.metadata_refresh_days, now)]
        if not todo:
            return
        eur_per_usd = latest_eur_per_usd(session)
        venues = _venue_listings(ctx)
        for asset in todo:
            reference = market_rows[asset.coingecko_id].get("current_price")
            sources: list[str] = []
            for venue in ctx.cfg.crypto.price_sources:
                if venue == "coingecko":
                    sources.append("coingecko")
                    continue
                symbol = _validated_symbol(ctx, venue, venues.get(venue, {}), asset, reference, eur_per_usd)
                kind = VENUE_ALIAS[venue]
                session.execute(delete(AssetAlias).where(AssetAlias.asset_id == asset.id, AssetAlias.kind == kind))
                if symbol and _set_alias(session, asset.id, kind, symbol, venue):
                    sources.append(venue)
            asset.price_sources = sources
            asset.mapping_checked_at = now
            ctx.report.add("assets_mapped")
            session.commit()
        _map_defillama(ctx, session, todo)
        _map_coinmetrics(ctx, session, todo)
        session.commit()


def _venue_listings(ctx: CryptoContext) -> dict[str, dict[str, dict[str, str]]]:
    """{venue: {BASE: {QUOTE: symbol}}} for the quotes we accept."""
    out: dict[str, dict[str, dict[str, str]]] = {}
    quotes = {"binance": ctx.cfg.crypto.binance_quotes, "coinbase": ctx.cfg.crypto.coinbase_quotes}
    for venue, provider in (("binance", ctx.providers.binance), ("coinbase", ctx.providers.coinbase)):
        try:
            listing = provider.get_meta()
        except ProviderError as exc:
            ctx.report.error(f"{venue} listing: {exc}")
            continue
        table: dict[str, dict[str, str]] = {}
        for item in listing:
            if item["quote"] in quotes[venue]:
                table.setdefault(item["base"].upper(), {})[item["quote"]] = item["symbol"]
        out[venue] = table
    return out


def _validated_symbol(ctx: CryptoContext, venue: str, table: dict[str, dict[str, str]], asset: Asset,
                      reference_eur: float | None, eur_per_usd: Decimal | None) -> str | None:
    quotes = ctx.cfg.crypto.binance_quotes if venue == "binance" else ctx.cfg.crypto.coinbase_quotes
    candidates = table.get(asset.symbol.upper(), {})
    if not candidates or not reference_eur:
        return None
    for quote in quotes:
        symbol = candidates.get(quote)
        if not symbol:
            continue
        try:
            bars = ctx.providers.get(venue).get_bars(symbol, ctx.yesterday - timedelta(days=3), ctx.yesterday)
        except ProviderError as exc:
            ctx.report.error(f"mapping {asset.coingecko_id} {venue}: {exc}")
            continue
        if not bars:
            continue
        close = bars[-1].close
        if quote in ("USD", "USDT"):
            if eur_per_usd is None:
                continue
            close = close * eur_per_usd  # approximate for USDT: only used for this sanity check
        ratio = abs(float(close) / float(reference_eur) - 1)
        if ratio <= ctx.cfg.crypto.mapping_price_tolerance:
            return symbol
        ctx.report.notes.append(
            f"{asset.coingecko_id}: {venue} {symbol} rejected, price differs {ratio:.0%} from CoinGecko"
        )
    return None


def _map_defillama(ctx: CryptoContext, session: Session, assets: list[Asset]) -> None:
    candidates = [a for a in assets if "stablecoin" not in _exclusion_labels(a)]
    if not candidates:
        return
    try:
        protocols = ctx.providers.defillama.protocols()
        chains = ctx.providers.defillama.chains()
    except ProviderError as exc:
        ctx.report.error(f"defillama listing: {exc}")
        return
    by_gecko: dict[str, dict] = {}
    for p in protocols:
        gid = p.get("gecko_id")
        # A coin's exchange or treasury is not the protocol the coin belongs to.
        if not gid or p.get("category") in DEFILLAMA_SKIP_CATEGORIES:
            continue
        if gid not in by_gecko or (p.get("tvl") or 0) > (by_gecko[gid].get("tvl") or 0):
            by_gecko[gid] = p
    chain_by_gecko = {c["gecko_id"]: c["name"] for c in chains if c.get("gecko_id")}
    for asset in candidates:
        gid = asset.coingecko_id
        session.execute(delete(AssetAlias).where(
            AssetAlias.asset_id == asset.id, AssetAlias.kind.in_(["defillama_chain", "defillama_protocol"])
        ))
        # A chain's own coin (ETH, BNB, MNT) is measured as a chain, not as one protocol on it.
        if gid in chain_by_gecko:
            _set_alias(session, asset.id, "defillama_chain", chain_by_gecko[gid], "defillama")
        elif gid in by_gecko:
            _set_alias(session, asset.id, "defillama_protocol", by_gecko[gid]["slug"], "defillama")
        else:
            # Parent protocols (e.g. Uniswap) are not listed with a gecko_id; accept the slug only when
            # DefiLlama itself confirms the CoinGecko id.
            try:
                info, _ = ctx.providers.defillama.fees(gid, "dailyFees")
                if info.get("gecko_id") == gid:
                    _set_alias(session, asset.id, "defillama_protocol", gid, "defillama")
            except ProviderError:
                pass


def _exclusion_labels(asset: Asset) -> set[str]:
    cats = {c.lower() for c in asset.categories or []}
    return {"stablecoin"} if any("stablecoin" in c for c in cats) else set()


def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _map_coinmetrics(ctx: CryptoContext, session: Session, assets: list[Asset]) -> None:
    try:
        catalog = ctx.providers.coinmetrics.catalog(ctx.cfg.crypto.coinmetrics_metrics)
    except ProviderError as exc:
        ctx.report.error(f"coinmetrics catalog: {exc}")
        return
    wanted = {a.symbol.lower() for a in assets if a.symbol.lower() in catalog}
    overrides = ctx.cfg.crypto.coinmetrics_overrides
    names: dict[str, str] = {}
    if wanted:
        try:
            names = ctx.providers.coinmetrics.asset_names(sorted(wanted))
        except ProviderError as exc:
            ctx.report.error(f"coinmetrics names: {exc}")
    for asset in assets:
        session.execute(delete(AssetAlias).where(AssetAlias.asset_id == asset.id, AssetAlias.kind == "coinmetrics"))
        cm_id = overrides.get(asset.coingecko_id)
        if cm_id is None:
            sym = asset.symbol.lower()
            full = _normalise(names.get(sym, ""))
            mine = _normalise(asset.name)
            # Symbols are not unique; require the names to agree as well.
            if sym in catalog and full and (full == mine or full.startswith(mine) or mine.startswith(full)):
                cm_id = sym
        if cm_id and cm_id in catalog:
            _set_alias(session, asset.id, "coinmetrics", cm_id, "coinmetrics")


# --- prices --------------------------------------------------------------------------------------

def update_prices(ctx: CryptoContext) -> None:
    """Bring every mapped venue of each tracked asset up to yesterday.

    All venues are kept so the view price_daily_eur can pick, day by day, the bar of the most preferred
    source and fall back to the next one when it is missing. CoinGecko (budgeted, EUR closes only, one
    year deep) is only used when the venues are not up to date or cover less than a year.
    """
    with ctx.sf() as session:
        assets = [(a.id, a.coingecko_id, list(a.price_sources or ["coingecko"]), _aliases(session, a.id))
                  for a in tracked_assets(session)]
    year_ago = ctx.yesterday - timedelta(days=364)
    for asset_id, gecko_id, sources, aliases in assets:
        venue_first: list[date] = []
        venue_current = False
        for source in sources:
            if source == "coingecko":
                continue
            symbol = aliases.get(VENUE_ALIAS.get(source, ""))
            if not symbol:
                continue
            first, last = _update_source(ctx, asset_id, gecko_id, source, symbol)
            if first:
                venue_first.append(first)
            venue_current |= last == ctx.yesterday
        with ctx.sf() as session:
            has_gecko = last_bar_date(session, asset_id, "coingecko") is not None
        short_history = not venue_first or min(venue_first) > max(year_ago, ctx.history_start)
        if "coingecko" in sources and (not venue_current or short_history or has_gecko):
            _update_source(ctx, asset_id, gecko_id, "coingecko", gecko_id)
        elif not venue_current:
            ctx.report.add("assets_without_new_prices")


def _update_source(ctx: CryptoContext, asset_id: int, gecko_id: str, source: str,
                   symbol: str) -> tuple[date | None, date | None]:
    """Fetch missing days from one source. Returns (first, last) stored bar dates afterwards."""
    with ctx.sf() as session:
        last = last_bar_date(session, asset_id, source)
    start = last + timedelta(days=1) if last else ctx.history_start
    if start <= ctx.yesterday:
        try:
            bars = ctx.providers.get(source).get_bars(symbol, start, ctx.yesterday)
        except ProviderError as exc:
            ctx.report.error(f"prices {gecko_id} {source}: {exc}")
            bars = []
        if bars:
            with ctx.sf() as session:
                ctx.report.add("bars_added", insert_bars(session, asset_id, source, bars, datetime.now(UTC)))
                session.commit()
            ctx.report.add(f"prices_from_{source}")
    with ctx.sf() as session:
        first = session.scalar(
            select(func.min(PriceBar.ts)).where(PriceBar.asset_id == asset_id, PriceBar.source == source)
        )
        return first, last_bar_date(session, asset_id, source)


# --- fundamentals --------------------------------------------------------------------------------

def update_defillama(ctx: CryptoContext) -> None:
    with ctx.sf() as session:
        assets = [(a.id, a.coingecko_id, _aliases(session, a.id)) for a in tracked_assets(session)]
    dl = ctx.providers.defillama
    for asset_id, gecko_id, aliases in assets:
        if "defillama_chain" in aliases:
            chain = aliases["defillama_chain"]
            calls = [lambda c=chain: dl.chain_tvl(c),
                     lambda c=chain: dl.fees(c.lower(), "dailyFees")[1],
                     lambda c=chain: dl.fees(c.lower(), "dailyRevenue")[1]]
        elif "defillama_protocol" in aliases:
            slug = aliases["defillama_protocol"]
            calls = [lambda s=slug: dl.protocol_tvl(s)[1],
                     lambda s=slug: dl.fees(s, "dailyFees")[1],
                     lambda s=slug: dl.fees(s, "dailyRevenue")[1]]
        else:
            continue
        facts = []
        for call in calls:
            try:
                facts += call()
            except ProviderError as exc:
                if exc.not_found:
                    ctx.report.add("defillama_not_available")  # e.g. a chain without fee data
                else:
                    ctx.report.error(f"defillama {gecko_id}: {exc}")
        with ctx.sf() as session:
            ctx.report.add("facts_added", insert_facts(session, asset_id, "defillama", facts, datetime.now(UTC)))
            session.commit()


def update_coinmetrics(ctx: CryptoContext) -> None:
    with ctx.sf() as session:
        mapped = {}
        for a in tracked_assets(session):
            cm = _aliases(session, a.id).get("coinmetrics")
            if cm:
                mapped[cm] = (a.id, last_fact_date(session, a.id, "coinmetrics", "cm_"))
    if not mapped:
        return
    # New assets get full history; the rest only the days since their last value.
    groups: dict[date, list[str]] = {}
    for cm, (_, last) in mapped.items():
        start = last + timedelta(days=1) if last else ctx.history_start
        if start <= ctx.yesterday:
            groups.setdefault(start, []).append(cm)
    for start, cms in groups.items():
        try:
            series = ctx.providers.coinmetrics.timeseries(sorted(cms), ctx.cfg.crypto.coinmetrics_metrics, start)
        except ProviderError as exc:
            ctx.report.error(f"coinmetrics: {exc}")
            continue
        with ctx.sf() as session:
            for cm, facts in series.items():
                if cm in mapped:
                    ctx.report.add("facts_added", insert_facts(session, mapped[cm][0], "coinmetrics", facts,
                                                               datetime.now(UTC)))
            session.commit()
