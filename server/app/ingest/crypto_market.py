"""Phase 2 data for crypto grading: order books, MiCA venues, derivatives, memecoin safety, stablecoin supply.

Live values (order books, open interest, 24-hour volumes, safety reports) are stored as snapshot facts
for the day that just closed (`ctx.yesterday`): the first value of a day is kept.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.grading.assign import assign_crypto
from app.ingest.store import insert_facts, insert_macro
from app.models import FundamentalFact
from app.providers import Fact, ProviderError
from app.providers.derivatives import PerpProvider, daily_mean_funding

if TYPE_CHECKING:
    from app.ingest.crypto import CryptoContext

STABLECOIN_SERIES = "STABLECOIN_SUPPLY_USD"


def _tracked(ctx: "CryptoContext"):
    from app.ingest.crypto import _aliases, targets

    with ctx.sf() as session:
        return [(a.id, a.coingecko_id, a.symbol.upper(), list(a.categories or []), a.template_override,
                 _aliases(session, a.id)) for a in targets(ctx, session)]


def _store(ctx: "CryptoContext", asset_id: int, source: str, facts: list[Fact], snapshot: bool = True) -> None:
    with ctx.sf() as session:
        ctx.report.add("facts_added", insert_facts(session, asset_id, source, facts, datetime.now(UTC),
                                                   snapshot=snapshot))
        session.commit()


def update_stablecoin_supply(ctx: "CryptoContext") -> None:
    try:
        rows = ctx.providers.get("defillama_stablecoins").total_supply()
    except ProviderError as exc:
        ctx.report.error(f"stablecoin supply: {exc}")
        return
    with ctx.sf() as session:
        ctx.report.add("macro_added", insert_macro(session, STABLECOIN_SERIES, "defillama", rows, datetime.now(UTC)))
        session.commit()


def update_order_books(ctx: "CryptoContext") -> None:
    """Depth within 2% of mid and bid-ask spread on Coinbase (a MiCA-licensed venue)."""
    book = ctx.providers.get("coinbase_book")
    for asset_id, gecko_id, _, _, _, aliases in _tracked(ctx):
        product = aliases.get("coinbase_product")
        if not product:
            continue
        try:
            data, call_id = book.depth(product)
        except ProviderError as exc:
            if not exc.not_found:
                ctx.report.error(f"order book {gecko_id}: {exc}")
            continue
        quote = product.split("-")[1].lower()
        _store(ctx, asset_id, "coinbase", [
            Fact(f"orderbook_depth_2pct_{quote}", ctx.yesterday, Decimal(str(data["depth_quote"])), quote, call_id),
            Fact("bid_ask_spread", ctx.yesterday, Decimal(str(data["spread"])), "ratio", call_id),
        ])


def update_mica_venues(ctx: "CryptoContext", market_rows: dict[str, dict]) -> None:
    """Bitvavo EUR volume and the MiCA-venue flag (listed at Coinbase or, price-checked, at Bitvavo)."""
    listing: dict[str, dict] = {}
    bitvavo_call = None
    if "bitvavo" in ctx.cfg.crypto.mica_venues:
        try:
            listing, bitvavo_call = ctx.providers.get("bitvavo").eur_markets()
        except ProviderError as exc:
            ctx.report.error(f"bitvavo: {exc}")
            return  # without the listing the flag would be wrong; keep yesterday's knowledge instead
    tolerance = ctx.cfg.crypto.mapping_price_tolerance
    for asset_id, gecko_id, symbol, _, _, aliases in _tracked(ctx):
        facts = []
        on_bitvavo = False
        entry = listing.get(symbol)
        reference = (market_rows.get(gecko_id) or {}).get("current_price")
        if entry and reference:
            # Same ticker, different coin? Only accept when Bitvavo's price matches CoinGecko's.
            on_bitvavo = abs(entry["last"] / float(reference) - 1) <= tolerance
            if on_bitvavo and entry["volume_eur"] is not None:
                facts.append(Fact("bitvavo_volume_24h_eur", ctx.yesterday, Decimal(str(entry["volume_eur"])), "eur",
                                  bitvavo_call))
        if not reference and not aliases.get("coinbase_product"):
            continue  # nothing to check against today
        on_coinbase = "coinbase" in ctx.cfg.crypto.mica_venues and "coinbase_product" in aliases
        flag = 0 if (on_coinbase or on_bitvavo) else 1
        facts.append(Fact("flag_not_on_mica_venue", ctx.yesterday, Decimal(flag), "flag", bitvavo_call))
        _store(ctx, asset_id, "derived", facts)


def _reachable_perp_sources(ctx: "CryptoContext") -> list[tuple[str, PerpProvider, set[str]]]:
    out = []
    for name in ctx.cfg.crypto.derivatives_sources:
        provider = ctx.providers.get(name)
        try:
            out.append((name, provider, provider.perp_bases()))
        except ProviderError as exc:
            ctx.report.notes.append(f"{name} niet bereikbaar ({exc}); overgeslagen in deze run")
    return out


def update_derivatives(ctx: "CryptoContext") -> None:
    """Daily mean funding rate and open interest per coin, from the first venue that lists a USDT perpetual."""
    sources = _reachable_perp_sources(ctx)
    if not sources:
        return
    for asset_id, gecko_id, symbol, categories, _, _ in _tracked(ctx):
        if any("stablecoin" in c.lower() for c in categories):
            continue
        for name, provider, bases in sources:
            if symbol not in bases:
                continue
            with ctx.sf() as session:
                last = session.scalar(select(func.max(FundamentalFact.as_of)).where(
                    FundamentalFact.asset_id == asset_id, FundamentalFact.source == name,
                    FundamentalFact.field == "funding_rate_daily"))
            backfill = ctx.today - timedelta(days=ctx.cfg.crypto.derivatives_backfill_days)
            start = last + timedelta(days=1) if last else backfill
            facts = []
            try:
                if start <= ctx.yesterday:
                    daily = daily_mean_funding(provider.funding_history(symbol, start), before=ctx.today)
                    facts += [Fact("funding_rate_daily", d, Decimal(str(rate)), "ratio", call_id)
                              for d, (rate, call_id) in sorted(daily.items())]
                oi, oi_call = provider.open_interest_usd(symbol)
            except ProviderError as exc:
                ctx.report.error(f"derivatives {gecko_id} {name}: {exc}")
                continue
            _store(ctx, asset_id, name, facts, snapshot=False)
            if oi is not None:
                oi_fact = Fact("open_interest_usd", ctx.yesterday, Decimal(str(oi)), "usd", oi_call)
                _store(ctx, asset_id, name, [oi_fact])
            ctx.report.add(f"derivatives_from_{name}")
            break


def update_memecoin_safety(ctx: "CryptoContext") -> None:
    """RugCheck safety report (Solana) and DexScreener liquidity for coins graded as memecoins."""
    for asset_id, gecko_id, _, categories, override, aliases in _tracked(ctx):
        if assign_crypto(gecko_id, categories, override, ctx.model.assignment) != "crypto_memecoin":
            continue
        mint = aliases.get("contract:solana")
        chain, address = ("solana", mint) if mint else ("ethereum", aliases.get("contract:ethereum"))
        if address:
            try:
                liquidity, call_id = ctx.providers.get("dexscreener").liquidity_usd(chain, address)
                if liquidity is not None:
                    _store(ctx, asset_id, "dexscreener",
                           [Fact("dex_liquidity_usd", ctx.yesterday, Decimal(str(liquidity)), "usd", call_id)])
            except ProviderError as exc:
                ctx.report.error(f"dexscreener {gecko_id}: {exc}")
        if mint:
            try:
                report, call_id = ctx.providers.get("rugcheck").report(mint)
            except ProviderError as exc:
                ctx.report.error(f"rugcheck {gecko_id}: {exc}")
                continue
            units = {"holders_top10_pct": "pct", "lp_locked_pct": "pct"}
            _store(ctx, asset_id, "rugcheck", [
                Fact(k, ctx.yesterday, Decimal(str(v)), units.get(k, "flag"), call_id) for k, v in report.items()
            ])


