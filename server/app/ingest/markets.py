"""Markets run (weekdays 21:45 UTC): indices, ETFs and bond ETFs, then the market regime and their grades.

Steps: ECB rates and macro series (FRED, ECB yield curve) -> index assets and prices -> ETFs and bond ETFs
from the hand-maintained files (characteristics as facts, known from the moment they were loaded) ->
prices -> ten largest holdings (Yahoo, monthly) -> regime for every day up to today.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.ingest.fx_macro import update_fx, update_macro, update_treasury
from app.ingest.report import Report
from app.ingest.stocks import _set_alias, _upsert_asset, aliases, update_adjusted_series
from app.ingest.store import insert_facts, insert_macro
from app.markets_config import FundRow, MarketsConfig
from app.models import Asset, FundamentalFact
from app.providers import Fact, ProviderError, ProviderUnavailable
from app.providers.config import ProvidersConfig
from app.providers.registry import Providers

PRICE_START = date(2005, 1, 1)
RECHECK_DAYS = 10
HOLDINGS_REFRESH_DAYS = 30
# Numeric columns of the fund files stored as facts: column -> (field, unit, scale)
ETF_FACTS = {
    "ter_pct": ("ongoing_charges", "ratio", Decimal("0.01")),
    "fund_size_eur_m": ("fund_size_eur", "eur", Decimal("1000000")),
    "index_constituents": ("index_constituents", "count", Decimal(1)),
}
BOND_FACTS = {
    "ter_pct": ("ongoing_charges", "ratio", Decimal("0.01")),
    "fund_size_eur_m": ("fund_size_eur", "eur", Decimal("1000000")),
    "ytm_pct": ("yield_to_maturity", "ratio", Decimal("0.01")),
    "effective_duration": ("duration", "years", Decimal(1)),
    "top10_issuers_pct": ("issuer_concentration", "ratio", Decimal("0.01")),
    "holdings_count": ("holdings_count", "count", Decimal(1)),
    **{f"rating_{r}": (f"rating_{r}", "ratio", Decimal("0.01"))
       for r in ("aaa", "aa", "a", "bbb", "bb", "b", "ccc_lower", "nr")},
}
STATIC_COLUMNS = ["issuer", "domicile", "replication", "distribution", "securities_lending", "launch_date",
                  "leveraged_inverse", "index_group", "category", "currency_hedged", "fund_currency"]


@dataclass
class MarketsContext:
    sf: sessionmaker[Session]
    providers: Providers
    cfg: ProvidersConfig
    markets: MarketsConfig
    today: date
    report: Report


def run_markets(sf: sessionmaker[Session], providers: Providers, cfg: ProvidersConfig, markets: MarketsConfig,
                today: date | None = None) -> Report:
    ctx = MarketsContext(sf, providers, cfg, markets, today or datetime.now(UTC).date(), Report())
    update_fx(sf, providers, cfg, ctx.report, ctx.today)
    update_macro(sf, providers, cfg, ctx.report)
    update_treasury(sf, providers, cfg, ctx.report, ctx.today)
    sync_indices(ctx)
    update_shiller(ctx)
    sync_funds(ctx, markets.etfs, "etf")
    sync_funds(ctx, markets.bonds, "bond")
    sync_references(ctx)
    update_prices(ctx)
    update_holdings(ctx)
    return ctx.report


def sync_indices(ctx: MarketsContext) -> None:
    for i in ctx.markets.indices:
        with ctx.sf() as session:
            asset, created = _upsert_asset(session, i.slug, asset_class="index", symbol=i.yahoo, name=i.name)
            if created:
                ctx.report.add("assets_created")
            asset.price_sources = ["yahoo"]
            asset.sector, asset.tracked = i.region, True
            asset.tracked_since = asset.tracked_since or ctx.today
            asset.categories = [f"currency:{i.currency}"] + ([f"curve:{i.curve}"] if i.curve else []) + \
                ([f"breadth:{i.breadth}"] if i.breadth else []) + (["world"] if i.world else []) + \
                ([f"valuation:{i.valuation}"] if i.valuation else [])
            _set_alias(session, asset.id, "yahoo_symbol", i.yahoo, "config")
            session.commit()


SHILLER_EVERY_DAYS = 7          # the spreadsheet changes about once a month
SHILLER_RELEASE_LAG = timedelta(days=31)   # a month's CAPE counts as known a month after the month ends


def update_shiller(ctx: MarketsContext) -> None:
    """Shiller's CAPE and excess CAPE yield for the S&P 500 (only for indices with `valuation: shiller`)."""
    if "shiller" not in ctx.cfg.providers or not any(i.valuation == "shiller" for i in ctx.markets.indices):
        return
    with ctx.sf() as session:
        recent = session.execute(text(
            # Only a fetched spreadsheet counts: reading the data page alone is not a success.
            "SELECT 1 FROM provider_call_log WHERE provider = 'shiller' AND ok AND endpoint LIKE '%ie_data%' "
            "AND started_at > :t LIMIT 1"),
            {"t": datetime.now(UTC) - timedelta(days=SHILLER_EVERY_DAYS)}).first()
    if recent:
        return
    try:
        rows, call_id = ctx.providers.get("shiller").monthly()
    except ProviderError as exc:
        ctx.report.error(f"shiller: {exc}")
        return
    now = datetime.now(UTC)
    with ctx.sf() as session:
        for sid, idx in (("SHILLER_CAPE", 1), ("SHILLER_ECY", 2)):
            obs = [(r[0], r[idx], call_id) for r in rows if r[idx] is not None]
            ctx.report.add("macro_added", insert_macro(session, sid, "shiller", obs, now, SHILLER_RELEASE_LAG))
        session.commit()


def sync_references(ctx: MarketsContext) -> None:
    """Total-return series of an index, used only as the yardstick for tracking difference."""
    for key, g in ctx.markets.index_groups.items():
        if not g.reference:
            continue
        with ctx.sf() as session:
            slug = f"ref-{key}"
            asset, _ = _upsert_asset(session, slug, asset_class="reference", symbol=g.reference,
                                     name=f"{g.name} (totaalrendement)")
            asset.price_sources, asset.tracked = ["yahoo"], True
            asset.tracked_since = asset.tracked_since or ctx.today
            _set_alias(session, asset.id, "yahoo_symbol", g.reference, "config")
            session.commit()


def static_categories(row: FundRow, kind: str) -> list[str]:
    cats = [f"{c}:{row.get(c)}" for c in STATIC_COLUMNS if row.get(c)]
    return cats + [f"kind:{kind}"]


def sync_funds(ctx: MarketsContext, rows: list[FundRow], asset_class: str) -> None:
    """ETF or bond ETF assets with their characteristics. Numbers from the file are stored as facts dated
    with the file's date and known from the moment they were loaded (never earlier)."""
    facts_map = ETF_FACTS if asset_class == "etf" else BOND_FACTS
    now = datetime.now(UTC)
    for row in rows:
        with ctx.sf() as session:
            if asset_class == "etf":
                group = ctx.markets.index_groups.get(row.get("index_group") or "")
                sector = group.name if group else row.get("index_name")
            else:
                sector = ctx.markets.bond_categories.get(row.get("category") or "", row.get("category"))
            asset, created = _upsert_asset(session, row.slug, asset_class=asset_class,
                                           symbol=(row.get("yahoo") or "").split(".")[0], name=row.get("name"),
                                           country=row.get("domicile"))
            if created:
                ctx.report.add("assets_created")
            asset.sector, asset.tracked, asset.price_sources = sector, True, ["yahoo"]
            asset.tracked_since = asset.tracked_since or ctx.today
            asset.categories = static_categories(row, asset_class)
            _set_alias(session, asset.id, "isin", row.isin, "config")
            _set_alias(session, asset.id, "yahoo_symbol", row.get("yahoo"), "config")
            as_of_text = row.get("as_of_date") or row.get("fund_size_date") or row.get("verified_on")
            as_of = date.fromisoformat(as_of_text) if as_of_text else ctx.today
            facts = []
            for col, (field, unit, scale) in facts_map.items():
                v = row.num(col)
                if v is None:
                    continue
                facts.append(Fact(field=field, as_of=as_of, value=Decimal(str(v)) * scale, unit=unit,
                                  available_at=now))
            ctx.report.add("fund_facts_added", insert_facts(session, asset.id, "csv", facts, now))
            session.commit()


def update_prices(ctx: MarketsContext) -> None:
    yahoo = ctx.providers.get("yahoo")
    currencies = {i.slug: i.currency for i in ctx.markets.indices}
    with ctx.sf() as session:
        work = [(a.id, a.slug, aliases(session, a.id).get("yahoo_symbol")) for a in session.scalars(
            select(Asset).where(Asset.asset_class.in_(("index", "etf", "bond", "reference")),
                                Asset.tracked.is_(True)).order_by(Asset.id))]
    for asset_id, slug, symbol in work:
        if not symbol:
            continue
        try:
            update_adjusted_series(ctx.sf, yahoo, asset_id, "yahoo", symbol, PRICE_START, ctx.today, RECHECK_DAYS,
                                   ctx.report, store_raw=False, default_currency=currencies.get(slug))
        except ProviderUnavailable as exc:
            ctx.report.unavailable(exc, "koersen van indices, ETF's en obligatie-ETF's")
            break
        except ProviderError as exc:
            ctx.report.error(f"koersen {slug}: {exc}")


def update_holdings(ctx: MarketsContext) -> None:
    """Weight of the ten largest holdings (Yahoo), monthly. Missing when Yahoo has no holdings."""
    provider = ctx.providers.get("yahoo_fund")
    with ctx.sf() as session:
        work = []
        for a in session.scalars(select(Asset).where(Asset.asset_class == "etf", Asset.tracked.is_(True))):
            last = session.scalar(select(func.max(FundamentalFact.as_of)).where(
                FundamentalFact.asset_id == a.id, FundamentalFact.field == "top10_weight"))
            if last is None or (ctx.today - last).days >= HOLDINGS_REFRESH_DAYS:
                work.append((a.id, a.slug, aliases(session, a.id).get("yahoo_symbol")))
    for asset_id, slug, symbol in work:
        try:
            h = provider.top_holdings(symbol)
        except ProviderUnavailable as exc:
            ctx.report.unavailable(exc, "posities van ETF's")
            break
        except ProviderError as exc:
            ctx.report.add("holdings_errors")
            if exc.status_code == 429 or "crumb" in str(exc):
                # Yahoo refuses the session: stop for this run instead of asking again for every fund.
                ctx.report.note_once(f"posities: Yahoo weigert nu ({exc}); volgende run opnieuw")
                break
            ctx.report.note_once(f"posities {slug}: {exc}")
            continue
        if h["top10_weight"] is None:
            continue
        with ctx.sf() as session:
            fact = Fact("top10_weight", ctx.today - timedelta(days=1), Decimal(str(round(h["top10_weight"], 6))),
                        "ratio", h["call_id"])
            ctx.report.add("facts_added", insert_facts(session, asset_id, "yahoo", [fact], datetime.now(UTC),
                                                       snapshot=True))
            session.commit()
