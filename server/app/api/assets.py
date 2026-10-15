"""Asset page, chart data, search, fetch-on-request and watchlist."""

import re
import time
from datetime import UTC, date, datetime, timedelta

import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from app.ai.explanation import Snapshot, shown_explanation
from app.charting.indicators import (
    BOND_DEFAULT_ON,
    BOND_INDICATORS,
    COMMODITY_DEFAULT_ON,
    COMMODITY_INDICATORS,
    CRYPTO_INDICATORS,
    DEFAULT_ON,
    FX_DEFAULT_ON,
    FX_INDICATORS,
    INDEX_DEFAULT_ON,
    INDEX_INDICATORS,
    STOCK_DEFAULT_ON,
    STOCK_INDICATORS,
    aggregate_ohlc,
    bond_indicators,
    commodity_indicators,
    daily_indicators,
    fx_indicators,
    index_indicators,
    sample,
    sig,
    stock_indicators,
    to_points,
)
from app.grading.crypto import grade_crypto
from app.ingest.crypto import ingest_single
from app.models import Asset, WatchlistItem
from app.providers import ProviderError

router = APIRouter(prefix="/api")

CONTRACT_PLATFORMS = ["ethereum", "solana", "binance-smart-chain", "base", "arbitrum-one", "polygon-pos"]
EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
SOLANA_ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def _ctx(request: Request):
    return request.app.state.jobs


def _labels(request: Request) -> dict[str, str]:
    g = request.app.state.glossary
    return {k: v.label for k, v in g.metrics.items()}


def _asset(session, key: str) -> Asset:
    asset = session.scalar(select(Asset).where(Asset.slug == key))
    if asset is None:
        raise HTTPException(404, "Asset niet gevonden")
    return asset


@router.get("/assets/{key}")
def asset_detail(key: str, request: Request) -> dict:
    jobs = _ctx(request)
    config = request.app.state.model_config
    with jobs.sf() as session:
        asset = _asset(session, key)
        aliases = dict(session.execute(text("SELECT kind, value FROM asset_alias WHERE asset_id = :a"),
                                       {"a": asset.id}).all())
        snap = session.execute(text(
            """
            SELECT g.*, mv.version FROM grade_snapshot g JOIN model_version mv ON mv.id = g.model_version_id
            WHERE g.asset_id = :a AND g.model_version_id = :v ORDER BY g.as_of DESC LIMIT 1
            """
        ), {"a": asset.id, "v": jobs.model_version_id}).mappings().first()
        history = session.execute(text(
            """
            SELECT as_of, score, letter, status, coverage, peg_safety FROM grade_snapshot
            WHERE asset_id = :a AND model_version_id = :v ORDER BY as_of
            """
        ), {"a": asset.id, "v": jobs.model_version_id}).mappings().all()
        native = session.execute(text(
            """
            SELECT ts, source, quote_currency, close_native, close_eur FROM price_daily_eur
            WHERE asset_id = :a ORDER BY ts DESC LIMIT 1
            """
        ), {"a": asset.id}).mappings().first()
        watched = session.get(WatchlistItem, asset.id) is not None
    out = {
        "asset": {
            "id": asset.slug, "name": asset.name, "ticker": asset.symbol, "asset_class": asset.asset_class,
            "sector": asset.sector, "country": asset.country,
            "categories": asset.categories or [], "aliases": aliases, "tracked": asset.tracked,
            "in_watchlist": watched, "price_sources": asset.price_sources or [],
        },
        "price": dict(native) if native else None,
        "history": [dict(h) for h in history],
        "snapshot": None,
    }
    if snap is None:
        return out
    res, inputs = snap["result"], snap["inputs"]
    template = config.templates[snap["template_id"]]
    grade_input = inputs["grade_input"]["metrics"]
    peers = inputs.get("peers", {})
    provenance = inputs.get("provenance", {})
    pillars = []
    for p in res.get("pillars", []):
        metrics = []
        for m in p["metrics"]:
            meta = config.metrics.get(m["id"])
            gi = grade_input.get(m["id"], {})
            peer = peers.get(m["id"], {})
            metrics.append({
                **m, "unit": meta.unit if meta else None, "direction": meta.direction if meta else None,
                "peer_pct": gi.get("peer_pct"), "own_pct": gi.get("own_pct"), "source": provenance.get(m["id"]),
                "peer_group": peer.get("group"), "peer_count": len(peer.get("values") or []) or None,
            })
        cfg_pillar = next((x for x in template.pillars if x.id == p["id"]), None)
        pillars.append({**p, "metrics": metrics,
                        "horizon_months": cfg_pillar.horizon_months if cfg_pillar else None})
    out["asset"]["template"] = snap["template_id"]
    out["asset"]["template_name"] = template.name_nl
    out["snapshot"] = {
        "as_of": snap["as_of"], "model_version": snap["version"], "status": snap["status"], "letter": snap["letter"],
        "letter_low": res.get("letter_low"), "letter_high": res.get("letter_high"), "score": snap["score"],
        "quality": snap["quality"], "timing": snap["timing"], "coverage": snap["coverage"],
        "peg_safety": snap["peg_safety"], "labels": res.get("labels", []), "reason": res.get("reason_nl"),
        "price_eur": snap["price_eur"], "knowledge_time": snap["knowledge_time"],
        "btc_relative": res.get("btc_relative"),
        "horizon_months": template.horizon_months or config.settings.default_horizon_months,
        "notes": res.get("notes", []), "technical": inputs.get("technical"),
        "data_notes": inputs.get("notes", []),
    }
    out["pillars"] = pillars
    # A pillar-agreement gate in mode "exact" sets the grade instead of capping it (fx "geen voordeel").
    exact = {g.id for g in template.gates if getattr(g, "mode", None) == "exact"}
    out["gates"] = [{**g, "sets_grade": g["id"] in exact} for g in res.get("gates", [])]
    snapshot = Snapshot(asset.id, asset.name, snap["as_of"], snap["model_version_id"], res, snap["status"],
                        snap["letter"], snap["score"], snap["peg_safety"])
    with jobs.sf() as session:
        shown = shown_explanation(session, request.app.state.ai_config, config, snapshot, _labels(request))
    out["explanation"] = shown["text"]
    out["explanation_source"] = shown["source"]
    out["explanation_meta"] = {k: v for k, v in shown.items() if k not in ("text", "source")}
    return out


_chart_cache: dict[tuple, tuple[float, dict]] = {}
CHART_CACHE_SECONDS = 900  # data changes only with the nightly run


@router.get("/assets/{key}/chart")
def asset_chart(key: str, request: Request, interval: str = "1d") -> dict:
    if interval not in ("1d", "1w", "1M"):
        raise HTTPException(400, "interval moet 1d, 1w of 1M zijn")
    jobs = _ctx(request)
    cache_key = (key, interval, jobs.model_version_id)
    hit = _chart_cache.get(cache_key)
    if hit and time.monotonic() - hit[0] < CHART_CACHE_SECONDS:
        return hit[1]
    data = _build_chart(key, interval, jobs)
    if len(_chart_cache) > 200:
        _chart_cache.clear()
    _chart_cache[cache_key] = (time.monotonic(), data)
    return data


def clear_chart_cache() -> None:
    _chart_cache.clear()


def _benchmark_for(session, asset: Asset) -> tuple[str | None, str | None]:
    """(slug, name) of the series an asset's chart is compared with."""
    if asset.asset_class == "crypto":
        return ("bitcoin", "Bitcoin") if asset.slug != "bitcoin" else (None, None)
    if asset.asset_class == "stock":
        us = session.execute(text("SELECT 1 FROM asset_alias WHERE asset_id = :a AND kind = 'us_ticker'"),
                             {"a": asset.id}).first()
        return ("sp500", "S&P 500") if us else ("aex", "AEX")
    if asset.asset_class == "index" and asset.slug != "msci-world":
        return "msci-world", "MSCI World"
    if asset.asset_class == "etf":
        group = next((c.split(":", 1)[1] for c in asset.categories or [] if str(c).startswith("index_group:")), None)
        index = {"msci_world": "msci-world", "sp500": "sp500", "nasdaq100": "nasdaq-100", "aex": "aex",
                 "eurostoxx50": "euro-stoxx-50"}.get(group or "")
        return (index, "de index") if index else (None, None)
    return None, None


def _build_chart(key: str, interval: str, jobs) -> dict:
    with jobs.sf() as session:
        asset = _asset(session, key)
        stock = asset.asset_class in ("stock", "index", "etf", "bond", "reference", "commodity", "etc", "fx")
        conn = session.connection()
        # Stocks are charted in their own currency (adjusted for splits and dividends), crypto in euro.
        cols = ("open_eur AS open, high_eur AS high, low_eur AS low, close_eur AS close" if not stock else
                "close_native * open_eur / close_eur AS open, close_native * high_eur / close_eur AS high, "
                "close_native * low_eur / close_eur AS low, close_native AS close")
        prices = pd.read_sql(text(
            f"SELECT ts, {cols}, volume, quote_currency FROM price_daily_eur WHERE asset_id = :a ORDER BY ts"),
            conn, params={"a": asset.id})
        bench_slug, bench_name = _benchmark_for(session, asset)
        bench_col = "close_native" if stock else "close_eur"
        bench = pd.read_sql(text(
            f"SELECT p.ts, p.{bench_col} AS close FROM price_daily_eur p JOIN asset a ON a.id = p.asset_id "
            "WHERE a.slug = :b ORDER BY p.ts"), conn, params={"b": bench_slug or ""})
        facts = pd.read_sql(text(
            """
            SELECT DISTINCT ON (field, source, as_of) field, source, as_of, value::float8 AS value
            FROM fundamental_fact WHERE asset_id = :a AND field IN ('funding_rate_daily', 'open_interest_usd')
            ORDER BY field, source, as_of, available_at DESC
            """), conn, params={"a": asset.id})
        snaps = session.execute(text(
            "SELECT as_of, letter, status, result->'gates' AS gates FROM grade_snapshot "
            "WHERE asset_id = :a AND model_version_id = :v ORDER BY as_of"),
            {"a": asset.id, "v": jobs.model_version_id}).mappings().all()
        regime_rows = session.execute(text(
            "SELECT date, state FROM market_regime WHERE model_version_id = :v ORDER BY date"),
            {"v": jobs.model_version_id}).all()
        macro = {}
        cats = dict(str(c).split(":", 1) for c in asset.categories or [] if ":" in str(c))
        cftc_code = cats.get("cftc")
        if asset.asset_class == "fx" and jobs.commodities:
            cur = jobs.commodities.currencies
            base, quote = cats.get("base"), cats.get("quote")
            sign, code = (1, cur[base].cftc) if base in cur and cur[base].cftc and quote == "USD" else \
                (-1, cur[quote].cftc) if quote in cur and cur[quote].cftc and base == "USD" else (1, None)
            cftc_code = code
        if cftc_code:
            rows = session.execute(text(
                "SELECT DISTINCT ON (date) date, value FROM macro_observation WHERE series_id = :s "
                "ORDER BY date, available_at DESC"), {"s": f"CFTC_{cftc_code}"}).all()
            factor = sign if asset.asset_class == "fx" else 1
            macro["cftc"] = pd.Series([float(r[1]) * factor for r in rows], index=[r[0] for r in rows], dtype=float)
        def macro_series(sid: str) -> pd.Series:
            rows = session.execute(text(
                "SELECT DISTINCT ON (date) date, value FROM macro_observation WHERE series_id = :s "
                "ORDER BY date, available_at DESC"), {"s": sid}).all()
            return pd.Series([float(r[1]) for r in rows], index=[r[0] for r in rows], dtype=float)

        if asset.asset_class == "fx" and jobs.commodities:
            cur = jobs.commodities.currencies
            base, quote = cats.get("base"), cats.get("quote")
            if base in cur and quote in cur and cur[base].rates and cur[quote].rates:
                # The 3-month interbank rate (last in the list) exists for every currency.
                macro["rate_diff"] = (macro_series(cur[base].rates[-1]) - macro_series(cur[quote].rates[-1])).dropna()
        if asset.asset_class == "bond":
            macro["curve_us_2_10"] = macro_series("T10Y2Y")
            macro["curve_us_3m_10"] = macro_series("T10Y3M")
            macro["curve_ea_2_10"] = (macro_series("EA_AAA_10Y") - macro_series("EA_AAA_2Y")).dropna()
        if asset.asset_class in ("index", "etf"):
            for sid in ("VIXCLS", "VXVCLS"):
                rows = session.execute(text(
                    "SELECT DISTINCT ON (date) date, value FROM macro_observation WHERE series_id = :s "
                    "ORDER BY date, available_at DESC"), {"s": sid}).all()
                macro[sid] = pd.Series([float(r[1]) for r in rows], index=[r[0] for r in rows], dtype=float)
    if prices.empty:
        return {"candles": [], "volume": [], "indicators": {}, "catalog": [], "benchmark": None, "markers": [],
                "gate_zones": []}
    currency = "EUR" if not stock else str(prices["quote_currency"].iloc[-1])
    prices = prices.drop(columns="quote_currency")
    prices["ts"] = pd.to_datetime(prices["ts"]).dt.date
    ohlc = prices.set_index("ts").astype(float)
    benchmark = None
    if not bench.empty:
        benchmark = pd.Series(bench["close"].astype(float).to_numpy(), index=pd.to_datetime(bench["ts"]).dt.date)

    def fact_series(field: str) -> pd.Series | None:
        df = facts[facts["field"] == field]
        if df.empty:
            return None
        best = df.sort_values("as_of").iloc[-1]["source"]
        df = df[df["source"] == best]
        return pd.Series(df["value"].to_numpy(dtype=float), index=list(df["as_of"]))

    if asset.asset_class in ("commodity", "etc"):
        ind, defs, default_on = commodity_indicators(ohlc, macro.get("cftc")), COMMODITY_INDICATORS, \
            COMMODITY_DEFAULT_ON
    elif asset.asset_class == "fx":
        ind, defs, default_on = fx_indicators(ohlc, macro.get("cftc"), macro.get("rate_diff")), FX_INDICATORS, \
            FX_DEFAULT_ON
    elif asset.asset_class == "bond":
        curves = {k: macro.get(k) for k in ("curve_us_2_10", "curve_us_3m_10", "curve_ea_2_10")}
        ind, defs, default_on = bond_indicators(ohlc, curves), BOND_INDICATORS, BOND_DEFAULT_ON
    elif asset.asset_class in ("index", "etf", "reference"):
        breadth = None
        if asset.asset_class == "index":
            breadth = _breadth_for(jobs, asset)
        ind = index_indicators(ohlc, benchmark, macro.get("VIXCLS"), macro.get("VXVCLS"), breadth)
        defs, default_on = INDEX_INDICATORS, INDEX_DEFAULT_ON
    elif stock:
        ind, defs, default_on = stock_indicators(ohlc, benchmark), STOCK_INDICATORS, STOCK_DEFAULT_ON
    else:
        ind = daily_indicators(ohlc, benchmark, fact_series("funding_rate_daily"), fact_series("open_interest_usd"))
        defs, default_on = CRYPTO_INDICATORS, DEFAULT_ON
    candles = aggregate_ohlc(ohlc, interval)
    candle_rows = []
    for d, r in candles.iterrows():
        has_ohlc = not any(pd.isna(r[c]) for c in ("open", "high", "low"))
        o, h, low = (r["open"], r["high"], r["low"]) if has_ohlc else (r["close"],) * 3
        candle_rows.append({"time": d.isoformat(), "open": sig(o), "high": sig(h), "low": sig(low),
                            "close": sig(r["close"])})
    volume = [{"time": d.isoformat(), "value": sig(float(v), 4)} for d, v in candles["volume"].items() if pd.notna(v)]
    indicators = {k: to_points(sample(v, interval)) for k, v in ind.items()}
    bench_points = None
    if benchmark is not None:
        b = sample(benchmark.loc[benchmark.index >= ohlc.index[0]], interval)
        if not b.empty:
            bench_points = to_points(b * (ohlc["close"].iloc[0] / b.iloc[0]))
    markers, previous = [], None
    for s in snaps:
        letter = s["letter"] or ("–" if s["status"] == "no_grade" else None)
        if previous is not None and letter != previous:
            markers.append({"time": s["as_of"].isoformat(), "text": f"{previous}→{letter}"})
        previous = letter
    zones, current = [], None
    for s in snaps:
        hit = [g["id"] for g in (s["gates"] or []) if g["status"] == "hit"]
        day = s["as_of"].isoformat()
        if hit and current and current["labels"] == hit:
            current["end"] = day
        elif hit:
            current = {"start": day, "end": day, "labels": hit}
            zones.append(current)
        else:
            current = None
    catalog = [{**d.__dict__, "available": d.id in indicators and bool(indicators[d.id]),
                "default_on": d.id in default_on} for d in defs]
    return {"interval": interval, "candles": candle_rows, "volume": volume, "indicators": indicators,
            "catalog": catalog, "benchmark": bench_points, "benchmark_name": bench_name if bench_points else None,
            "markers": markers, "gate_zones": zones, "currency": currency,
            "adjusted": asset.asset_class in ("stock", "etf", "bond", "index", "etc"),
            "regime_zones": _risk_off_zones(regime_rows, ohlc.index[0]),
            "tradingview_symbol": _tradingview_symbol(asset)}


def _risk_off_zones(rows, first_day) -> list[dict]:
    zones, current = [], None
    for day, state in rows:
        if day < first_day:
            continue
        if state == "risk_off":
            if current is None:
                current = {"start": day.isoformat(), "end": day.isoformat(), "state": state}
                zones.append(current)
            current["end"] = day.isoformat()
        else:
            current = None
    return zones


def _breadth_for(jobs, asset: Asset) -> pd.Series | None:
    from app.grading.markets import breadth_series, load_market_data

    universe = next((c.split(":", 1)[1] for c in asset.categories or [] if str(c).startswith("breadth:")), None)
    if not universe:
        return None
    today = datetime.now(UTC).date()
    with jobs.sf() as session:
        data = load_market_data(session, today, datetime.now(UTC), jobs.model_version_id)
    return breadth_series(data, universe, today)


TRADINGVIEW_INDEX = {"sp500": "SP:SPX", "aex": "EURONEXT:AEX"}


def _tradingview_symbol(asset: Asset) -> str:
    if asset.asset_class == "crypto":
        return f"COINBASE:{asset.symbol}EUR" if asset.symbol else ""
    if asset.asset_class == "index":
        return TRADINGVIEW_INDEX.get(asset.slug or "", "")
    if asset.slug and asset.slug.endswith("-as"):
        return f"EURONEXT:{asset.symbol}"
    return asset.symbol.replace("-", ".") if asset.symbol else ""


TICKER = re.compile(r"^[A-Za-z]{1,5}([.-][A-Za-z])?$")


@router.get("/search")
def search(request: Request, q: str) -> dict:
    q = q.strip()
    if len(q) < 2:
        return {"local": [], "remote": [], "message": "Typ minstens twee tekens."}
    jobs = _ctx(request)
    with jobs.sf() as session:
        local = session.execute(text(
            """
            SELECT a.slug AS id, a.name, a.symbol AS ticker, a.asset_class, a.tracked,
                   g.letter, g.status, g.coverage, g.as_of
            FROM asset a
            LEFT JOIN LATERAL (SELECT letter, status, coverage, as_of FROM grade_snapshot x
                               WHERE x.asset_id = a.id AND x.model_version_id = :v
                               ORDER BY as_of DESC LIMIT 1) g ON true
            WHERE a.name ILIKE :like OR a.symbol ILIKE :q OR a.slug = :lower
               OR EXISTS (SELECT 1 FROM asset_alias al WHERE al.asset_id = a.id AND al.value IN (:q, :upper))
            ORDER BY a.tracked DESC, a.name LIMIT 20
            """), {"like": f"%{q}%", "q": q, "lower": q.lower(), "v": jobs.model_version_id,
                   "upper": q.upper()}).mappings().all()
    local = [dict(r) for r in local]
    remote, message = [], None
    if any(r["tracked"] for r in local):
        return {"local": local, "remote": [], "message": None, "model_version": jobs.model.version}
    errors = []
    if ISIN.match(q.upper()):
        remote, message = _isin_lookup(jobs, q.upper(), local)
        tracked = _tracked_stocks(jobs, [r["id"] for r in remote if r.get("source") == "sec"])
        if tracked:
            return {"local": tracked, "remote": [], "message": None, "model_version": jobs.model.version}
    else:
        try:
            if EVM_ADDRESS.match(q) or (SOLANA_ADDRESS.match(q) and not q.isalpha()):
                remote = _contract_lookup(jobs, q)
            else:
                remote = [{**r, "source": "coingecko"} for r in jobs.providers.coingecko.search(q)[:10]]
        except ProviderError as exc:
            errors.append(f"CoinGecko: {exc}")
        try:
            remote = _sec_lookup(jobs, q) + remote
        except ProviderError as exc:
            errors.append(f"SEC: {exc}")
    known = {r["id"] for r in local}
    remote = [r for r in remote if r.get("id") and r["id"] not in known]
    if errors and not remote:
        message = "Zoeken lukte niet bij " + "; ".join(errors)
    if not local and not remote and message is None:
        message = "Deze asset staat in geen enkele bron. Er is daarom geen grade."
    return {"local": local, "remote": remote, "message": message, "model_version": jobs.model.version}


def _tracked_stocks(jobs, tickers: list[str]) -> list[dict]:
    """Followed stocks among US tickers found for an ISIN (the ISIN itself is not stored for US stocks)."""
    if not tickers:
        return []
    with jobs.sf() as session:
        return [dict(r) for r in session.execute(text(
            """
            SELECT a.slug AS id, a.name, a.symbol AS ticker, a.asset_class, a.tracked,
                   g.letter, g.status, g.coverage, g.as_of
            FROM asset a JOIN asset_alias al ON al.asset_id = a.id AND al.kind = 'us_ticker'
            LEFT JOIN LATERAL (SELECT letter, status, coverage, as_of FROM grade_snapshot x
                               WHERE x.asset_id = a.id AND x.model_version_id = :v
                               ORDER BY as_of DESC LIMIT 1) g ON true
            WHERE al.value = ANY(:t) AND a.tracked
            """), {"t": tickers, "v": jobs.model_version_id}).mappings()]


def _sec_lookup(jobs, q: str) -> list[dict]:
    """US companies by exact ticker, or by name for longer queries."""
    rows = jobs.providers.get("sec").company_tickers()
    hits = [r for r in rows if r["ticker"] == q.upper()] if TICKER.match(q) else []
    if len(q) >= 4:
        hits += [r for r in rows if q.lower() in r["title"].lower() and r not in hits][:5]
    return [{"id": r["ticker"], "name": r["title"].title() if r["title"].isupper() else r["title"],
             "symbol": r["ticker"], "market_cap_rank": None, "source": "sec"} for r in hits[:6]]


def _isin_lookup(jobs, isin: str, local: list[dict]) -> tuple[list[dict], str | None]:
    """An ISIN that is not known locally: OpenFIGI gives the tickers; a US listing can be fetched via SEC."""
    try:
        listings = jobs.providers.get("openfigi").isin(isin)
    except ProviderError as exc:
        return [], f"OpenFIGI gaf geen antwoord: {exc}"
    if not listings:
        return [], "Dit ISIN is bij OpenFIGI niet bekend. Er is daarom geen grade."
    us = [x["ticker"] for x in listings if x.get("exchCode") == "US" and x.get("ticker")]
    if us:
        try:
            hits = _sec_lookup(jobs, us[0].replace("/", "-"))
        except ProviderError:
            hits = []
        if hits:
            return hits, None
    name = listings[0].get("name") or isin
    return [], (f"{name} is gevonden bij OpenFIGI, maar heeft geen notering met SEC-cijfers. Voor Europese "
                "aandelen buiten de AEX is geen gratis bron met jaarcijfers; er is daarom geen grade.")


def _contract_lookup(jobs, address: str) -> list[dict]:
    platforms = ["solana"] if not address.startswith("0x") else [p for p in CONTRACT_PLATFORMS if p != "solana"]
    for platform in platforms:
        found = jobs.providers.coingecko.by_contract(platform, address)
        if found and found.get("id"):
            return [{**found, "market_cap_rank": None, "platform": platform, "source": "coingecko"}]
    return []


class FetchRequest(BaseModel):
    coingecko_id: str | None = None
    ticker: str | None = None      # a US stock (SEC)


@router.post("/assets/fetch")
def fetch_asset(body: FetchRequest, request: Request) -> dict:
    """Fetch, store and grade one asset on request. Takes up to a minute (provider rate limits)."""
    jobs = _ctx(request)
    if body.ticker:
        return _fetch_stock(jobs, body.ticker)
    if not body.coingecko_id:
        raise HTTPException(400, "Geef coingecko_id of ticker op")
    asset_id, report = ingest_single(jobs.sf, jobs.providers, jobs.cfg, jobs.universes, body.coingecko_id, jobs.model)
    if asset_id is None:
        raise HTTPException(404, "Deze munt staat niet bij CoinGecko. Er is daarom geen grade.")
    with jobs.sf() as session:
        as_of = session.execute(text("SELECT max(as_of) FROM grade_snapshot WHERE model_version_id = :v"),
                                {"v": jobs.model_version_id}).scalar()
    as_of = as_of or datetime.now(UTC).date() - timedelta(days=1)
    graded = grade_crypto(jobs.sf, jobs.model, jobs.model_version_id, as_of,
                          date.fromisoformat(jobs.cfg.crypto.history_start))
    clear_chart_cache()
    return {"id": body.coingecko_id, "tab": "crypto", "errors": report.errors + graded.errors,
            "snapshots_added": graded.counts.get("snapshots_added", 0)}


def _fetch_stock(jobs, ticker: str) -> dict:
    from app.grading.stocks import grade_stocks
    from app.ingest.stocks import ingest_single_stock
    from app.jobs import last_trading_day

    asset_id, report = ingest_single_stock(jobs.sf, jobs.providers, jobs.cfg, jobs.stocks, jobs.universes,
                                           jobs.model, ticker)
    if asset_id is None:
        raise HTTPException(404, "Geen Amerikaans aandeel met een 10-K bij SEC onder deze ticker. "
                                 "Er is daarom geen grade.")
    graded = grade_stocks(jobs.sf, jobs.model, jobs.model_version_id, jobs.stocks, last_trading_day(datetime.now(UTC)))
    clear_chart_cache()
    with jobs.sf() as session:
        slug = session.get(Asset, asset_id).slug
    return {"id": slug, "tab": "stocks", "errors": report.errors + graded.errors,
            "snapshots_added": graded.counts.get("snapshots_added", 0)}


@router.get("/watchlist")
def watchlist(request: Request) -> list[str]:
    with _ctx(request).sf() as session:
        return list(session.execute(text(
            "SELECT a.slug FROM watchlist_item w JOIN asset a ON a.id = w.asset_id ORDER BY w.added_at"
        )).scalars())


@router.post("/watchlist/{key}")
def watch(key: str, request: Request) -> dict:
    with _ctx(request).sf() as session:
        asset = _asset(session, key)
        session.execute(insert(WatchlistItem).values(asset_id=asset.id).on_conflict_do_nothing())
        session.commit()
    return {"id": key, "in_watchlist": True}


@router.delete("/watchlist/{key}")
def unwatch(key: str, request: Request) -> dict:
    with _ctx(request).sf() as session:
        asset = _asset(session, key)
        item = session.get(WatchlistItem, asset.id)
        if item:
            session.delete(item)
            session.commit()
    return {"id": key, "in_watchlist": False}


@router.get("/assets/{key}/peers")
def etf_peers(key: str, request: Request) -> dict:
    """ETFs on the same index side by side: tracking difference split into costs and the rest."""
    jobs = _ctx(request)
    with jobs.sf() as session:
        asset = _asset(session, key)
        group = next((c.split(":", 1)[1] for c in asset.categories or [] if str(c).startswith("index_group:")), None)
        if asset.asset_class != "etf" or not group:
            return {"group": None, "rows": []}
        rows = session.execute(text(
            """
            SELECT DISTINCT ON (a.id) a.slug, a.name, a.categories, g.letter, g.status, g.score, g.coverage,
                   g.inputs->'grade_input'->'metrics' AS metrics, g.inputs->'provenance' AS provenance, g.as_of
            FROM asset a JOIN grade_snapshot g ON g.asset_id = a.id AND g.model_version_id = :v
            WHERE a.asset_class = 'etf' AND a.categories @> CAST(:cat AS jsonb)
            ORDER BY a.id, g.as_of DESC
            """), {"v": jobs.model_version_id, "cat": f'["index_group:{group}"]'}).mappings().all()
    out = []
    for r in rows:
        m = {k: (v or {}).get("value") for k, v in (r["metrics"] or {}).items()}
        cats = dict(str(c).split(":", 1) for c in r["categories"] or [] if ":" in str(c))
        td, ter = m.get("tracking_difference"), m.get("ongoing_charges")
        out.append({
            "id": r["slug"], "name": r["name"], "letter": r["letter"], "status": r["status"], "score": r["score"],
            "coverage": r["coverage"], "tracking_difference": td, "ongoing_charges": ter,
            "rest_after_costs": None if td is None or ter is None else td + ter,
            "fund_size": m.get("fund_size"), "domicile": cats.get("domicile"), "replication": cats.get("replication"),
            "distribution": cats.get("distribution"), "securities_lending": cats.get("securities_lending"),
            "td_source": (r["provenance"] or {}).get("tracking_difference"), "as_of": r["as_of"],
        })
    out.sort(key=lambda x: -(x["score"] or 0))
    group_name = jobs.markets.index_groups[group].name if jobs.markets and group in jobs.markets.index_groups else group
    return {"group": group_name, "rows": out, "model_version": jobs.model.version}



@router.get("/assets/{key}/products")
def commodity_products(key: str, request: Request) -> dict:
    """For a commodity: the products (ETCs) to hold it, with their product judgement. For an ETC or a currency
    pair: the commodity it tracks, or the mirror pair."""
    jobs = _ctx(request)
    with jobs.sf() as session:
        asset = _asset(session, key)
        cats = dict(str(c).split(":", 1) for c in asset.categories or [] if ":" in str(c))
        if asset.asset_class == "commodity":
            where, params = "a.asset_class = 'etc' AND a.categories @> CAST(:cat AS jsonb)", \
                {"cat": f'["commodity:{key}"]'}
        elif asset.asset_class == "etc":
            where, params = "a.slug = :s", {"s": cats.get("commodity", "")}
        elif asset.asset_class == "fx":
            where, params = "a.slug = :s", {"s": cats.get("mirror", "")}
        else:
            return {"rows": []}
        rows = session.execute(text(
            f"""
            SELECT DISTINCT ON (a.id) a.slug, a.name, a.asset_class, a.categories, g.letter, g.status, g.score,
                   g.coverage, g.as_of, g.inputs->'grade_input'->'metrics' AS metrics
            FROM asset a JOIN grade_snapshot g ON g.asset_id = a.id AND g.model_version_id = :v
            WHERE {where}
            ORDER BY a.id, g.as_of DESC
            """), {**params, "v": jobs.model_version_id}).mappings().all()
    out = []
    for r in rows:
        m = {k: (v or {}).get("value") for k, v in (r["metrics"] or {}).items()}
        c = dict(str(x).split(":", 1) for x in r["categories"] or [] if ":" in str(x))
        out.append({"id": r["slug"], "name": r["name"], "asset_class": r["asset_class"], "letter": r["letter"],
                    "status": r["status"], "score": r["score"], "coverage": r["coverage"], "as_of": r["as_of"],
                    "structure": c.get("structure"),
                    "collateralized": c.get("collateralized"), "ongoing_charges": m.get("ongoing_charges"),
                    "roll_yield_12m": m.get("roll_yield_12m"), "tracking_difference": m.get("tracking_difference")})
    out.sort(key=lambda x: -(x["score"] or 0))
    return {"rows": out, "model_version": jobs.model.version}
