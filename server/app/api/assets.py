"""Asset page, chart data, search, fetch-on-request and watchlist."""

import re
import time
from datetime import UTC, date, datetime, timedelta

import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from app.charting.indicators import (
    CRYPTO_INDICATORS,
    DEFAULT_ON,
    aggregate_ohlc,
    daily_indicators,
    sample,
    sig,
    to_points,
)
from app.grading.crypto import grade_crypto
from app.grading.explain import explain
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
    asset = session.scalar(select(Asset).where(Asset.coingecko_id == key))
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
            "id": asset.coingecko_id, "name": asset.name, "ticker": asset.symbol, "asset_class": asset.asset_class,
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
        pillars.append({**p, "metrics": metrics})
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
    }
    out["pillars"] = pillars
    out["gates"] = res.get("gates", [])
    out["explanation"] = explain(asset.name, res, config, _labels(request))
    out["explanation_source"] = "sjabloon"
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


def _build_chart(key: str, interval: str, jobs) -> dict:
    with jobs.sf() as session:
        asset = _asset(session, key)
        conn = session.connection()
        prices = pd.read_sql(text(
            "SELECT ts, open_eur AS open, high_eur AS high, low_eur AS low, close_eur AS close, volume "
            "FROM price_daily_eur WHERE asset_id = :a ORDER BY ts"), conn, params={"a": asset.id})
        bench = pd.read_sql(text(
            "SELECT p.ts, p.close_eur FROM price_daily_eur p JOIN asset a ON a.id = p.asset_id "
            "WHERE a.coingecko_id = 'bitcoin' ORDER BY p.ts"), conn)
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
    if prices.empty:
        return {"candles": [], "volume": [], "indicators": {}, "catalog": [], "benchmark": None, "markers": [],
                "gate_zones": []}
    prices["ts"] = pd.to_datetime(prices["ts"]).dt.date
    ohlc = prices.set_index("ts").astype(float)
    benchmark = None
    if not bench.empty and key != "bitcoin":
        benchmark = pd.Series(bench["close_eur"].astype(float).to_numpy(), index=pd.to_datetime(bench["ts"]).dt.date)

    def fact_series(field: str) -> pd.Series | None:
        df = facts[facts["field"] == field]
        if df.empty:
            return None
        best = df.sort_values("as_of").iloc[-1]["source"]
        df = df[df["source"] == best]
        return pd.Series(df["value"].to_numpy(dtype=float), index=list(df["as_of"]))

    ind = daily_indicators(ohlc, benchmark, fact_series("funding_rate_daily"), fact_series("open_interest_usd"))
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
                "default_on": d.id in DEFAULT_ON} for d in CRYPTO_INDICATORS]
    return {"interval": interval, "candles": candle_rows, "volume": volume, "indicators": indicators,
            "catalog": catalog, "benchmark": bench_points, "benchmark_name": "Bitcoin" if bench_points else None,
            "markers": markers, "gate_zones": zones,
            "tradingview_symbol": _tradingview_symbol(asset)}


def _tradingview_symbol(asset: Asset) -> str:
    return f"COINBASE:{asset.symbol}EUR" if asset.symbol else ""


@router.get("/search")
def search(request: Request, q: str) -> dict:
    q = q.strip()
    if len(q) < 2:
        return {"local": [], "remote": [], "message": "Typ minstens twee tekens."}
    jobs = _ctx(request)
    with jobs.sf() as session:
        local = session.execute(text(
            """
            SELECT DISTINCT a.coingecko_id AS id, a.name, a.symbol AS ticker, a.asset_class, a.tracked,
                   (SELECT letter FROM grade_snapshot g WHERE g.asset_id = a.id AND g.model_version_id = :v
                    ORDER BY as_of DESC LIMIT 1) AS letter,
                   (SELECT status FROM grade_snapshot g WHERE g.asset_id = a.id AND g.model_version_id = :v
                    ORDER BY as_of DESC LIMIT 1) AS status
            FROM asset a LEFT JOIN asset_alias al ON al.asset_id = a.id
            WHERE a.name ILIKE :like OR a.symbol ILIKE :q OR a.coingecko_id = :lower OR al.value = :q
            ORDER BY a.tracked DESC, a.name LIMIT 20
            """), {"like": f"%{q}%", "q": q, "lower": q.lower(), "v": jobs.model_version_id}).mappings().all()
    local = [dict(r) for r in local]
    remote, message = [], None
    if ISIN.match(q.upper()):
        message = "Zoeken op ISIN werkt zodra aandelen en ETF's zijn aangesloten (fase 4 en 5)."
    elif not any(r["tracked"] for r in local):
        try:
            if EVM_ADDRESS.match(q) or (SOLANA_ADDRESS.match(q) and not q.isalpha()):
                remote = _contract_lookup(jobs, q)
            else:
                remote = jobs.providers.coingecko.search(q)[:10]
        except ProviderError as exc:
            message = f"Zoeken bij CoinGecko lukte niet: {exc}"
        known = {r["id"] for r in local}
        remote = [r for r in remote if r.get("id") and r["id"] not in known]
        if not local and not remote and message is None:
            message = "Deze asset staat in geen enkele bron. Er is daarom geen grade."
    return {"local": local, "remote": remote, "message": message}


def _contract_lookup(jobs, address: str) -> list[dict]:
    platforms = ["solana"] if not address.startswith("0x") else [p for p in CONTRACT_PLATFORMS if p != "solana"]
    for platform in platforms:
        found = jobs.providers.coingecko.by_contract(platform, address)
        if found and found.get("id"):
            return [{**found, "market_cap_rank": None, "platform": platform}]
    return []


class FetchRequest(BaseModel):
    coingecko_id: str


@router.post("/assets/fetch")
def fetch_asset(body: FetchRequest, request: Request) -> dict:
    """Fetch, store and grade one coin on request. Takes up to a minute (provider rate limits)."""
    jobs = _ctx(request)
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
    return {"id": body.coingecko_id, "errors": report.errors + graded.errors,
            "snapshots_added": graded.counts.get("snapshots_added", 0)}


@router.get("/watchlist")
def watchlist(request: Request) -> list[str]:
    with _ctx(request).sf() as session:
        return list(session.execute(text(
            "SELECT a.coingecko_id FROM watchlist_item w JOIN asset a ON a.id = w.asset_id ORDER BY w.added_at"
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
