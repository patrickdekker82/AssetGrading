"""Point-in-time inputs for crypto grading: loads what was known at `knowledge` about day `as_of`, then
derives each model metric. Every metric carries its source and date; a metric without data stays None.
"""

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

STALE_SNAPSHOT_DAYS = 3
MIN_HISTORY_POINTS = 180
STABLECOIN_SERIES = "STABLECOIN_SUPPLY_USD"
FACT_FIELDS = [
    "market_cap_eur", "fdv_eur", "circulating_supply", "dev_commits_4w", "watchlist_users", "audits_count",
    "fees_usd", "revenue_usd", "holders_revenue_usd", "tvl_usd", "cm_CapMVRVCur", "cm_CapMrktCurUSD",
    "cm_AdrActCnt", "cm_SplyCur", "cm_IssTotUSD", "funding_rate_daily", "open_interest_usd",
    "orderbook_depth_2pct_usd", "orderbook_depth_2pct_eur", "bid_ask_spread", "bitvavo_volume_24h_eur",
    "flag_not_on_mica_venue", "dex_liquidity_usd", "mint_authority_active", "freeze_authority_active",
    "lp_locked_pct", "holders_top10_pct",
]


@dataclass
class AssetRow:
    id: int
    coingecko_id: str
    symbol: str
    name: str
    categories: list[str]
    template_override: str | None
    alias_kinds: list[str]


@dataclass
class CryptoData:
    as_of: date
    knowledge: datetime
    assets: list[AssetRow]
    closes: dict[int, pd.Series]
    coinbase_volume_eur: dict[int, pd.Series]
    facts: pd.DataFrame            # asset_id, field, source, as_of, value (latest known version per day)
    usd_per_eur: pd.Series         # ECB EUR/USD by date
    macro: dict[str, pd.Series]

    @property
    def eur_per_usd(self) -> float | None:
        known = self.usd_per_eur.loc[:self.as_of]
        return None if known.empty else 1 / float(known.iloc[-1])


@dataclass
class Metrics:
    values: dict[str, float | None] = field(default_factory=dict)
    history: dict[str, pd.Series] = field(default_factory=dict)  # for own-history percentiles
    provenance: dict[str, str] = field(default_factory=dict)
    flags: dict[str, bool | None] = field(default_factory=dict)
    raw: dict[str, float | None] = field(default_factory=dict)   # helper values shown on the asset page
    notes: list[str] = field(default_factory=list)               # data remarks shown with the grade

    def set(self, metric: str, value: float | None, source: str) -> None:
        if value is not None and math.isfinite(value):
            self.values[metric] = float(value)
            self.provenance[metric] = source


def load_crypto_data(session: Session, as_of: date, knowledge: datetime, history_start: date) -> CryptoData:
    params = {"d": as_of, "k": knowledge, "start": history_start}
    assets = [
        AssetRow(id=r.id, coingecko_id=r.coingecko_id, symbol=r.symbol, name=r.name, categories=r.categories or [],
                 template_override=r.template_override, alias_kinds=list(r.kinds or []))
        for r in session.execute(text(
            """
            SELECT a.id, a.coingecko_id, a.symbol, a.name, a.categories, a.template_override,
                   array_remove(array_agg(al.kind), NULL) AS kinds
            FROM asset a LEFT JOIN asset_alias al ON al.asset_id = a.id
            WHERE a.asset_class = 'crypto' AND a.tracked
            GROUP BY a.id ORDER BY a.id
            """
        ))
    ]
    prices = pd.read_sql(text(
        "SELECT asset_id, ts, close_eur FROM price_daily_eur WHERE ts <= :d AND ts >= :start ORDER BY asset_id, ts"
    ), session.connection(), params=params)
    closes = {int(k): g.set_index("ts")["close_eur"].astype(float) for k, g in prices.groupby("asset_id")}
    for s in closes.values():
        s.index = pd.to_datetime(s.index).date

    vol = pd.read_sql(text(
        """
        SELECT asset_id, ts, volume * close_eur AS volume_eur FROM price_bar_eur
        WHERE source = 'coinbase' AND ts <= :d AND ts > :d - 40 AND volume IS NOT NULL AND close_eur IS NOT NULL
        """
    ), session.connection(), params=params)
    coinbase_volume = {int(k): g.set_index("ts")["volume_eur"].astype(float) for k, g in vol.groupby("asset_id")}

    facts = pd.read_sql(text(
        """
        SELECT DISTINCT ON (asset_id, field, source, as_of) asset_id, field, source, as_of, value::float8 AS value
        FROM fundamental_fact
        WHERE available_at <= :k AND as_of <= :d AND as_of >= :start AND (field = ANY(:fields) OR source = 'manual')
        ORDER BY asset_id, field, source, as_of, available_at DESC, id DESC
        """
    ), session.connection(), params={**params, "fields": FACT_FIELDS})

    fx = pd.read_sql(text(
        "SELECT date, rate::float8 AS rate FROM fx_rate "
        "WHERE base = 'EUR' AND quote = 'USD' AND date <= :d ORDER BY date"
    ), session.connection(), params=params)
    usd_per_eur = pd.Series(fx["rate"].to_numpy(), index=pd.to_datetime(fx["date"]).dt.date)

    macro_rows = pd.read_sql(text(
        """
        SELECT DISTINCT ON (series_id, date) series_id, date, value FROM macro_observation
        WHERE available_at <= :k AND date <= :d AND series_id = ANY(:series)
        ORDER BY series_id, date, available_at DESC, id DESC
        """
    ), session.connection(), params={**params, "series": ["DFII10", "DTWEXBGS", STABLECOIN_SERIES]})
    macro = {}
    for sid, g in macro_rows.groupby("series_id"):
        macro[sid] = pd.Series(g["value"].to_numpy(dtype=float), index=pd.to_datetime(g["date"]).dt.date)
    return CryptoData(as_of, knowledge, assets, closes, coinbase_volume, facts, usd_per_eur, macro)


class AssetFacts:
    """Convenient access to one asset's facts."""

    def __init__(self, data: CryptoData, asset_id: int):
        self.data = data
        self.df = data.facts[data.facts["asset_id"] == asset_id]

    def series(self, field_name: str, source: str | None = None) -> pd.Series:
        df = self.df[self.df["field"] == field_name]
        if source:
            df = df[df["source"] == source]
        elif df["source"].nunique() > 1:
            # Several sources (e.g. derivatives venues): use the one with the most recent value.
            best = df.sort_values("as_of").iloc[-1]["source"]
            df = df[df["source"] == best]
        s = pd.Series(df["value"].to_numpy(dtype=float), index=list(df["as_of"]))
        return s.sort_index()

    def latest(self, field_name: str, source: str | None = None,
               max_age: int | None = STALE_SNAPSHOT_DAYS) -> tuple[float | None, str | None]:
        s = self.series(field_name, source)
        if s.empty:
            return None, None
        day = s.index[-1]
        if max_age is not None and (self.data.as_of - day).days > max_age:
            return None, None
        src = source or self.df[(self.df["field"] == field_name) & (self.df["as_of"] == day)]["source"].iloc[0]
        return float(s.iloc[-1]), f"{src} {day.isoformat()}"


def _window_sum(s: pd.Series, end: date, days: int, min_points: int) -> float | None:
    w = s.loc[end - timedelta(days=days - 1):end] if not s.empty else s
    return float(w.sum()) if len(w) >= min_points else None


def _window_mean(s: pd.Series, end: date, days: int, min_points: int) -> float | None:
    w = s.loc[end - timedelta(days=days - 1):end] if not s.empty else s
    return float(w.mean()) if len(w) >= min_points else None


def compute_metrics(data: CryptoData, asset: AssetRow, template_id: str, safety: dict[str, float]) -> Metrics:
    m = Metrics()
    f = AssetFacts(data, asset.id)
    d = data.as_of
    eur = data.eur_per_usd

    mcap, mcap_src = f.latest("market_cap_eur", "coingecko")
    if mcap is None:
        cm_mcap, src = f.latest("cm_CapMrktCurUSD", "coinmetrics")
        if cm_mcap is not None and eur:
            mcap, mcap_src = cm_mcap * eur, src
    fdv, fdv_src = f.latest("fdv_eur", "coingecko")
    m.raw.update({"market_cap_eur": mcap, "fdv_eur": fdv})

    if mcap and fdv and fdv > 0:
        m.set("mcap_to_fdv", mcap / fdv, f"{mcap_src} / {fdv_src}")

    supply = f.series("cm_SplyCur", "coinmetrics")
    if len(supply) > 300:
        now_s, then_s = supply.loc[:d], supply.loc[:d - timedelta(days=365)]
        if not now_s.empty and not then_s.empty and then_s.iloc[-1] > 0:
            m.set("net_inflation", now_s.iloc[-1] / then_s.iloc[-1] - 1, "coinmetrics SplyCur")

    adr = f.series("cm_AdrActCnt", "coinmetrics")
    active = _window_mean(adr, d, 30, 20)
    m.set("active_addresses", active, "coinmetrics AdrActCnt, 30 dagen")

    fees = _window_sum(f.series("fees_usd", "defillama"), d, 30, 25)
    revenue = _window_sum(f.series("revenue_usd", "defillama"), d, 30, 25)
    holders_rev = _window_sum(f.series("holders_revenue_usd", "defillama"), d, 30, 25)
    if fees is not None and eur:
        m.set("protocol_fees", fees * 365 / 30 * eur, "defillama fees, 30 dagen op jaarbasis")
    if revenue is not None and eur:
        m.set("protocol_revenue", revenue * 365 / 30 * eur, "defillama revenue, 30 dagen op jaarbasis")
        # No free source separates paying customers from subsidised use; protocol revenue is the closest.
        m.set("real_customer_revenue", revenue * 365 / 30 * eur, "defillama revenue (benadering)")
    if holders_rev is not None and revenue:
        m.set("holder_payout", holders_rev / revenue, "defillama holders revenue / revenue")

    commits, src = f.latest("dev_commits_4w", "coingecko", max_age=45)
    m.set("developer_activity", commits, f"{src} (commits 4 weken)")
    audits, src = f.latest("audits_count", "defillama", max_age=45)
    m.set("audit_score", audits, f"{src}")
    watchers, src = f.latest("watchlist_users", "coingecko", max_age=45)
    if watchers is not None:
        m.set("attention_score", math.log10(watchers + 1), f"{src} (volglijsten, log)")

    if mcap and active:
        m.set("mcap_to_active_addresses", mcap / active, "marktwaarde / actieve adressen")
    if mcap and m.values.get("protocol_fees"):
        m.set("mcap_to_fees", mcap / m.values["protocol_fees"], "marktwaarde / fees op jaarbasis")
    _valuation_history(m, f, d)

    cb_vol = data.coinbase_volume_eur.get(asset.id)
    cb_avg = _window_mean(cb_vol, d, 30, 20) if cb_vol is not None else None
    bv, _ = f.latest("bitvavo_volume_24h_eur", "derived")
    if cb_avg is not None or bv is not None:
        m.set("regulated_volume", (cb_avg or 0) + (bv or 0), "coinbase 30 dagen gemiddeld + bitvavo 24 uur")
    depth_usd, src_u = f.latest("orderbook_depth_2pct_usd", "coinbase")
    depth_eur, src_e = f.latest("orderbook_depth_2pct_eur", "coinbase")
    if depth_eur is not None:
        m.set("orderbook_depth_2pct", depth_eur, f"{src_e}")
    elif depth_usd is not None and eur:
        m.set("orderbook_depth_2pct", depth_usd * eur, f"{src_u}")
    spread, src = f.latest("bid_ask_spread", "coinbase")
    m.set("bid_ask_spread", spread, f"{src}")

    funding = f.series("funding_rate_daily")
    m.set("funding_rate", _window_mean(funding, d, 30, 20), "funding 30 dagen gemiddeld")
    if len(funding) >= MIN_HISTORY_POINTS:
        m.history["funding_rate"] = funding.rolling(30, min_periods=20).mean().dropna()
    oi, src = f.latest("open_interest_usd")
    if oi is not None and mcap and eur:
        m.set("open_interest_to_mcap", oi * eur / mcap, f"{src} / marktwaarde")

    flag, _ = f.latest("flag_not_on_mica_venue", "derived")
    m.flags["not_on_mica_venue"] = None if flag is None else bool(flag)

    if template_id == "crypto_bitcoin":
        _bitcoin_metrics(m, f, data)
    if template_id == "crypto_stablecoin":
        _stablecoin_metrics(m, data, asset)
    if template_id == "crypto_memecoin":
        _memecoin_metrics(m, f, eur, safety)

    _manual(m, f)
    return m


def _valuation_history(m: Metrics, f: AssetFacts, d: date) -> None:
    """Daily history of the valuation ratios (in USD) where Coin Metrics has market cap and activity."""
    mcap = f.series("cm_CapMrktCurUSD", "coinmetrics")
    if mcap.empty:
        return
    adr = f.series("cm_AdrActCnt", "coinmetrics").rolling(30, min_periods=20).mean()
    ratio = (mcap / adr).dropna()
    if len(ratio) >= MIN_HISTORY_POINTS:
        m.history["mcap_to_active_addresses"] = ratio.loc[:d]
    fees = f.series("fees_usd", "defillama")
    if not fees.empty:
        annual = fees.rolling(30, min_periods=25).sum() * 365 / 30
        fr = (mcap / annual).replace([float("inf")], float("nan")).dropna()
        if len(fr) >= MIN_HISTORY_POINTS:
            m.history["mcap_to_fees"] = fr.loc[:d]


def _bitcoin_metrics(m: Metrics, f: AssetFacts, data: CryptoData) -> None:
    d = data.as_of
    mc = f.series("cm_CapMrktCurUSD", "coinmetrics")
    mvrv = f.series("cm_CapMVRVCur", "coinmetrics")
    joined = pd.concat({"mc": mc, "mvrv": mvrv}, axis=1).dropna()
    if len(joined) >= MIN_HISTORY_POINTS:
        realized = joined["mc"] / joined["mvrv"]
        z = (joined["mc"] - realized) / joined["mc"].expanding(min_periods=365).std()
        nupl = 1 - 1 / joined["mvrv"]
        for metric, series, label in (("mvrv_z", z.dropna(), "MVRV Z-score"), ("nupl", nupl, "NUPL"),
                                      ("price_to_realized", joined["mvrv"], "koers / gerealiseerde prijs")):
            if not series.empty and (d - series.index[-1]).days <= STALE_SNAPSHOT_DAYS:
                m.set(metric, float(series.iloc[-1]), f"coinmetrics {series.index[-1]} ({label})")
                m.history[metric] = series
    iss = f.series("cm_IssTotUSD", "coinmetrics")
    if len(iss) >= 365 + MIN_HISTORY_POINTS:
        puell = (iss / iss.rolling(365).mean()).dropna()
        if not puell.empty and (d - puell.index[-1]).days <= STALE_SNAPSHOT_DAYS:
            m.set("puell_multiple", float(puell.iloc[-1]), f"coinmetrics {puell.index[-1]} (Puell)")
            m.history["puell_multiple"] = puell
    for metric, sid, label in (("real_rate", "DFII10", "FRED DFII10"), ("dollar_index", "DTWEXBGS", "FRED DTWEXBGS")):
        s = data.macro.get(sid)
        if s is not None and not s.empty and (d - s.index[-1]).days <= 10:
            m.set(metric, float(s.iloc[-1]), f"{label} {s.index[-1]}")
            m.history[metric] = s
    supply = data.macro.get(STABLECOIN_SERIES)
    if supply is not None and len(supply) > 400:
        growth = (supply / supply.shift(30) - 1).dropna()
        if (d - growth.index[-1]).days <= STALE_SNAPSHOT_DAYS:
            m.set("stablecoin_supply_growth", float(growth.iloc[-1]), f"defillama stablecoins {growth.index[-1]}")
            m.history["stablecoin_supply_growth"] = growth


def _stablecoin_metrics(m: Metrics, data: CryptoData, asset: AssetRow) -> None:
    closes = data.closes.get(asset.id)
    cats = {c.lower() for c in asset.categories}
    peg_eur = "eur stablecoin" in cats
    if closes is not None:
        window = closes.loc[data.as_of - timedelta(days=364):data.as_of]
        if peg_eur:
            pegged = window
        else:
            rates = data.usd_per_eur.reindex(sorted(set(data.usd_per_eur.index) | set(window.index))).ffill()
            pegged = window * rates.reindex(window.index)
        pegged = pegged.dropna()
        if len(pegged) >= 60:
            m.set("peg_deviation", float((pegged - 1).abs().mean()), f"dagkoersen {len(pegged)} dagen, peg "
                  f"{'EUR' if peg_eur else 'USD'}")
            m.raw["peg_max_deviation"] = float((pegged - 1).abs().max())
    m.set("mica_status", 1.0 if "mica-compliant stablecoin" in cats else 0.0, "coingecko categorie")


def _memecoin_metrics(m: Metrics, f: AssetFacts, eur: float | None, safety: dict[str, float]) -> None:
    liq, src = f.latest("dex_liquidity_usd", "dexscreener")
    if liq is not None and eur:
        m.set("dex_liquidity", liq * eur, f"{src}")
    for fact, flag in (("mint_authority_active", "mint_authority_active"),
                       ("freeze_authority_active", "freeze_authority_active")):
        v, _ = f.latest(fact, "rugcheck")
        m.flags[flag] = None if v is None else bool(v)
    locked, _ = f.latest("lp_locked_pct", "rugcheck")
    m.flags["liquidity_not_locked"] = None if locked is None else locked < safety.get("lp_locked_min_pct", 50)
    top10, src = f.latest("holders_top10_pct", "rugcheck")
    if top10 is not None:
        m.set("holders_top10", top10 / 100, f"{src} (zonder pools en beurzen)")


def _manual(m: Metrics, f: AssetFacts) -> None:
    """Manually entered facts (source 'manual') fill metrics and flags that no free source provides."""
    manual = f.df[f.df["source"] == "manual"]
    for field_name in manual["field"].unique():
        value, src = f.latest(field_name, "manual", max_age=None)
        if field_name.startswith("flag_"):
            m.flags[field_name.removeprefix("flag_")] = bool(value)
        elif field_name not in m.values:
            m.set(field_name, value, f"handmatig ({src.split(' ', 1)[1]})")
