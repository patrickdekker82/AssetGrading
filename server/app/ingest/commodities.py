"""Commodities and currencies run (weekdays 22:00 UTC).

Steps: ECB rates -> FRED rates and real effective exchange rates per currency -> World Bank (current
account, terms of trade) -> CFTC positions -> EIA inventories (with a key) -> commodity assets with front
contract prices and the futures curve -> ETC products -> currency pairs from ECB reference rates (both
directions).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pandas as pd
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.commodities_config import CommoditiesConfig, CommodityEntry
from app.ingest.fx_macro import update_fx
from app.ingest.markets import static_categories
from app.ingest.report import Report
from app.ingest.stocks import _set_alias, _upsert_asset, aliases, update_adjusted_series
from app.ingest.store import insert_facts, insert_macro, upsert_bars
from app.models import Asset, MacroObservation
from app.providers import Bar, Fact, ProviderError, ProviderUnavailable
from app.providers.config import ProvidersConfig
from app.providers.registry import Providers

MONTH_CODES = "FGHJKMNQUVXZ"
CURVE_MONTHS_AHEAD = 18
CURVE_CONTRACTS = 2
MACRO_REVISION_DAYS = 120
CFTC_LAG = timedelta(days=3, hours=21)      # Tuesday positions, published Friday 15:30 New York
WORLD_BANK_LAG = timedelta(days=180)        # yearly figures appear months after the year
WB_INDICATORS = {"CA": "BN.CAB.XOKA.GD.ZS", "TOT": "TT.PRI.MRCH.XD.WD"}
ETC_FACTS = {"ter_pct": ("ongoing_charges", "ratio", Decimal("0.01"))}


@dataclass
class CommodityContext:
    sf: sessionmaker[Session]
    providers: Providers
    cfg: ProvidersConfig
    cc: CommoditiesConfig
    today: date
    report: Report

    @property
    def start(self) -> date:
        return date.fromisoformat(self.cc.history_start)


def run_commodities(sf: sessionmaker[Session], providers: Providers, cfg: ProvidersConfig, cc: CommoditiesConfig,
                    today: date | None = None) -> Report:
    ctx = CommodityContext(sf, providers, cfg, cc, today or datetime.now(UTC).date(), Report())
    update_fx(sf, providers, cfg, ctx.report, ctx.today)
    update_fred(ctx)
    update_world_bank(ctx)
    update_cftc(ctx)
    update_eia(ctx)
    sync_commodities(ctx)
    sync_etcs(ctx)
    sync_fx_pairs(ctx)
    update_prices(ctx)
    update_curves(ctx)
    return ctx.report


# --- macro inputs ---------------------------------------------------------------------------------

def _last_date(sf, series_id: str, source: str) -> date | None:
    with sf() as session:
        return session.scalar(select(func.max(MacroObservation.date)).where(
            MacroObservation.series_id == series_id, MacroObservation.source == source))


def _store(ctx: CommodityContext, series_id: str, source: str, obs, lag: timedelta | None = None) -> None:
    with ctx.sf() as session:
        ctx.report.add("macro_added", insert_macro(session, series_id, source, obs, datetime.now(UTC), lag))
        session.commit()


def update_fred(ctx: CommodityContext) -> None:
    fred = ctx.providers.fred
    series = sorted({s for c in ctx.cc.currencies.values() for s in c.rates + ([c.reer] if c.reer else [])})
    for sid in series:
        last = _last_date(ctx.sf, sid, "fred")
        start = max(last - timedelta(days=MACRO_REVISION_DAYS), ctx.start) if last else ctx.start
        try:
            _store(ctx, sid, "fred", fred.observations(sid, start))
        except ProviderError as exc:
            ctx.report.error(f"fred {sid}: {exc}")


def update_world_bank(ctx: CommodityContext) -> None:
    wb = ctx.providers.get("worldbank")
    countries = sorted({c.worldbank for c in ctx.cc.currencies.values() if c.worldbank})
    for key, indicator in WB_INDICATORS.items():
        try:
            rows = wb.indicator(indicator, countries, ctx.start.year, ctx.today.year)
        except ProviderError as exc:
            ctx.report.error(f"worldbank {indicator}: {exc}")
            continue
        by_country: dict[str, list] = {}
        for country, year, value, call_id in rows:
            by_country.setdefault(country, []).append((date(year, 12, 31), value, call_id))
        for country, obs in by_country.items():
            _store(ctx, f"WB_{key}_{country}", "worldbank", sorted(obs), WORLD_BANK_LAG)
        missing = [c for c in countries if c not in by_country]
        if missing:
            ctx.report.note_once(f"Wereldbank {indicator}: geen cijfers voor {', '.join(missing)}")


def update_cftc(ctx: CommodityContext) -> None:
    cftc = ctx.providers.get("cftc")
    jobs = [("disaggregated", c.cftc) for c in ctx.cc.commodities if c.cftc]
    jobs += [("financial", c.cftc) for c in ctx.cc.currencies.values() if c.cftc]
    for report, code in jobs:
        sid = f"CFTC_{code}"
        last = _last_date(ctx.sf, sid, "cftc")
        start = last - timedelta(days=28) if last else ctx.start
        try:
            _store(ctx, sid, "cftc", cftc.net_positions(report, code, start), CFTC_LAG)
        except ProviderError as exc:
            ctx.report.error(f"cftc {code}: {exc}")


def update_eia(ctx: CommodityContext) -> None:
    eia = ctx.providers.get("eia")
    if not eia.api_key:
        ctx.report.note_once("EIA_API_KEY ontbreekt: geen voorraadcijfers voor energie")
        return
    for key in sorted({c.eia for c in ctx.cc.commodities if c.eia}):
        sid = f"EIA_{key}"
        last = _last_date(ctx.sf, sid, "eia")
        start = last - timedelta(days=60) if last else ctx.start
        try:
            # Weekly figures for the week ending Friday appear the next Wednesday.
            _store(ctx, sid, "eia", eia.weekly(key, start), timedelta(days=5, hours=16))
        except ProviderError as exc:
            ctx.report.error(f"eia {key}: {exc}")


# --- assets ---------------------------------------------------------------------------------------

def sync_commodities(ctx: CommodityContext) -> None:
    for c in ctx.cc.commodities:
        with ctx.sf() as session:
            asset, created = _upsert_asset(session, c.slug, asset_class="commodity", symbol=c.front, name=c.name)
            if created:
                ctx.report.add("assets_created")
            asset.sector, asset.tracked, asset.price_sources = c.group, True, ["yahoo"]
            asset.tracked_since = asset.tracked_since or ctx.today
            asset.template_override = c.template
            asset.categories = [f"template:{c.template}"] + ([f"eia:{c.eia}"] if c.eia else []) + \
                ([f"cftc:{c.cftc}"] if c.cftc else [])
            _set_alias(session, asset.id, "yahoo_symbol", c.front, "config")
            session.commit()


def sync_etcs(ctx: CommodityContext) -> None:
    names = {c.slug: c.name for c in ctx.cc.commodities}
    now = datetime.now(UTC)
    for row in ctx.cc.etcs:
        commodity = row.get("commodity") or ""
        with ctx.sf() as session:
            asset, created = _upsert_asset(session, row.slug, asset_class="etc",
                                           symbol=(row.get("yahoo") or "").split(".")[0], name=row.get("name"),
                                           country=row.get("domicile"))
            if created:
                ctx.report.add("assets_created")
            asset.sector, asset.tracked, asset.price_sources = names.get(commodity, commodity), True, ["yahoo"]
            asset.tracked_since = asset.tracked_since or ctx.today
            asset.categories = static_categories(row, "etc") + [f"commodity:{commodity}"] + \
                [f"{k}:{row.get(k)}" for k in ("structure", "collateralized") if row.get(k)]
            _set_alias(session, asset.id, "isin", row.isin, "config")
            _set_alias(session, asset.id, "yahoo_symbol", row.get("yahoo"), "config")
            as_of = date.fromisoformat(row.get("verified_on") or ctx.today.isoformat())
            facts = [Fact(field=f, as_of=as_of, value=Decimal(str(row.num(col))) * scale, unit=unit, available_at=now)
                     for col, (f, unit, scale) in ETC_FACTS.items() if row.num(col) is not None]
            ctx.report.add("fund_facts_added", insert_facts(session, asset.id, "csv", facts, now))
            session.commit()


def sync_fx_pairs(ctx: CommodityContext) -> None:
    for pair in ctx.cc.all_pairs:
        base_dir = pair in ctx.cc.pairs
        with ctx.sf() as session:
            asset, created = _upsert_asset(session, pair.slug, asset_class="fx", symbol=f"{pair.base}{pair.quote}",
                                           name=pair.name)
            if created:
                ctx.report.add("assets_created")
            asset.sector = "EUR-paren" if "EUR" in (pair.base, pair.quote) else "Dollarparen"
            asset.tracked, asset.price_sources = True, ["ecb"]
            asset.tracked_since = asset.tracked_since or ctx.today
            mirror = pair.inverse().slug
            asset.categories = [f"base:{pair.base}", f"quote:{pair.quote}", f"mirror:{mirror}",
                                "direction:configured" if base_dir else "direction:inverse"]
            session.commit()
    write_fx_bars(ctx)


def write_fx_bars(ctx: CommodityContext) -> None:
    """Daily closes of every pair from ECB reference rates: X/Y = (EUR in Y) / (EUR in X)."""
    with ctx.sf() as session:
        fx = pd.read_sql(text("SELECT date, quote, rate::float8 AS rate FROM fx_rate WHERE base = 'EUR' "
                              "AND date >= :s ORDER BY date"), session.connection(), params={"s": ctx.start})
        last = dict(session.execute(text(
            "SELECT a.slug, max(b.ts) FROM price_bar b JOIN asset a ON a.id = b.asset_id "
            "WHERE a.asset_class = 'fx' GROUP BY a.slug")).all())
        ids = dict(session.execute(text("SELECT slug, id FROM asset WHERE asset_class = 'fx'")).all())
    table = fx.pivot(index="date", columns="quote", values="rate")
    table["EUR"] = 1.0
    fetched = datetime.now(UTC)
    for pair in ctx.cc.all_pairs:
        if pair.base not in table or pair.quote not in table:
            continue
        series = (table[pair.quote] / table[pair.base]).dropna()
        since = last.get(pair.slug)
        if since is not None:
            series = series[series.index > since]
        bars = [Bar(ts=d, close=Decimal(str(round(v, 10))), quote=pair.quote) for d, v in series.items()]
        with ctx.sf() as session:
            ctx.report.add("bars_written", upsert_bars(session, ids[pair.slug], "ecb", bars, fetched))
            session.commit()


def update_prices(ctx: CommodityContext) -> None:
    yahoo = ctx.providers.get("yahoo")
    with ctx.sf() as session:
        work = [(a.id, a.slug, aliases(session, a.id).get("yahoo_symbol")) for a in session.scalars(
            select(Asset).where(Asset.asset_class.in_(("commodity", "etc")), Asset.tracked.is_(True)))]
    for asset_id, slug, symbol in work:
        if not symbol:
            continue
        try:
            update_adjusted_series(ctx.sf, yahoo, asset_id, "yahoo", symbol, ctx.start, ctx.today, 10, ctx.report,
                                   store_raw=False, default_currency="USD")
        except ProviderUnavailable as exc:
            ctx.report.unavailable(exc, "koersen van grondstoffen en ETC's")
            break
        except ProviderError as exc:
            ctx.report.error(f"koersen {slug}: {exc}")


# --- futures curve --------------------------------------------------------------------------------

def contract_candidates(c: CommodityEntry, today: date) -> list[tuple[str, date]]:
    """Listed contracts from this month on: (Yahoo symbol, mid-month of the contract month)."""
    out = []
    for k in range(CURVE_MONTHS_AHEAD):
        year, month = today.year + (today.month - 1 + k) // 12, (today.month - 1 + k) % 12 + 1
        code = MONTH_CODES[month - 1]
        if code in c.months:
            out.append((f"{c.root}{code}{year % 100:02d}.{c.exchange}", date(year, month, 15)))
    return out


def update_curves(ctx: CommodityContext) -> None:
    """Price of the first two listed contracts that trade, stored daily (the curve slope and, after a year,
    basis momentum are computed from these)."""
    yahoo = ctx.providers.get("yahoo")
    for c in ctx.cc.commodities:
        found = []
        for symbol, month in contract_candidates(c, ctx.today):
            if len(found) == CURVE_CONTRACTS:
                break
            try:
                s = yahoo.series(symbol, ctx.today - timedelta(days=10), ctx.today, default_currency="USD")
            except ProviderUnavailable as exc:
                ctx.report.unavailable(exc, "termijncurves")
                return
            except ProviderError:
                continue
            if s.bars and (ctx.today - s.bars[-1].ts).days <= 5:
                found.append((symbol, month, s.bars[-1]))
        if len(found) < CURVE_CONTRACTS:
            ctx.report.note_once(f"termijncurve {c.slug}: te weinig contracten met een koers")
            continue
        day = min(b.ts for _, _, b in found)
        facts = []
        for i, (_symbol, month, bar) in enumerate(found, start=1):
            facts.append(Fact(f"curve_f{i}", day, bar.close, "price", bar.call_id))
            facts.append(Fact(f"curve_f{i}_month", day, Decimal(month.year * 100 + month.month), "yyyymm",
                              bar.call_id))
        with ctx.sf() as session:
            asset_id = session.scalar(select(Asset.id).where(Asset.slug == c.slug))
            ctx.report.add("facts_added", insert_facts(session, asset_id, "yahoo", facts, datetime.now(UTC),
                                                       snapshot=True))
            session.commit()

