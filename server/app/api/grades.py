"""Latest grades per tab for the ranking table."""

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

router = APIRouter(prefix="/api")

STATUS_ORDER = {"graded": 0, "provisional": 0, "speculative": 1, "peg_safety": 2, "no_grade": 3}


def _pillar_note(pillars: list[dict], best: bool) -> str | None:
    scored = [p for p in pillars if p.get("score") is not None and p.get("effective_weight")]
    if len(scored) < 2:
        return None
    p = max(scored, key=lambda x: x["score"]) if best else min(scored, key=lambda x: x["score"])
    word = "sterk" if best else "zwak"
    return f"{p['name_nl']} {word} ({p['score']:.0f})"


# tab -> (asset class, universes whose membership marks the default list)
TAB_SOURCES = {
    "crypto": ("crypto", ["crypto_top"]),
    "stocks": ("stock", ["stocks_us", "stocks_aex"]),
    "etfs": ("etf", []),          # static lists: every followed asset is in the list
    "bonds": ("bond", []),
    "indices": ("index", []),
}
# The list is recorded on the day of the run: the crypto run just after midnight grades the day before,
# a stock run can grade Friday's close on Monday.
LIST_LAG_DAYS = {"crypto": 1, "stocks": 4, "watchlist": 4, "etfs": 4, "bonds": 4, "indices": 4}
LIST_LABELS = {"crypto_top": "top", "stocks_us": "VS", "stocks_aex": "AEX"}


@router.get("/grades")
def grades(request: Request, tab: str = "crypto") -> dict:
    config = request.app.state.model_config
    if tab not in TAB_SOURCES and tab != "watchlist":
        return {"tab": tab, "as_of": None, "rows": [], "model_version": config.version}
    jobs = request.app.state.jobs
    if jobs.model_version_id is None:
        raise HTTPException(503, "Geen modelversie geladen")
    if tab == "watchlist":
        classes = [c for c, _ in TAB_SOURCES.values()]
        universes = [u for _, us in TAB_SOURCES.values() for u in us]
    else:
        classes, universes = [TAB_SOURCES[tab][0]], TAB_SOURCES[tab][1]
    with jobs.sf() as session:
        as_of = session.execute(text(
            "SELECT max(g.as_of) FROM grade_snapshot g JOIN asset a ON a.id = g.asset_id "
            "WHERE g.model_version_id = :v AND a.asset_class = ANY(:c)"
        ), {"v": jobs.model_version_id, "c": classes}).scalar()
        if as_of is None:
            return {"tab": tab, "as_of": None, "rows": [], "model_version": config.version}
        rows = session.execute(text(
            """
            WITH membership AS (
                SELECT DISTINCT ON (asset_id, universe) asset_id, universe, rank, included, exclusion,
                       market_cap_eur
                FROM universe_membership
                WHERE universe = ANY(:u) AND as_of <= :d + :lag ORDER BY asset_id, universe, as_of DESC
            ), list AS (
                SELECT asset_id, min(rank) FILTER (WHERE universe <> 'stocks_aex') AS rank,
                       bool_or(included) AS included, min(exclusion) AS exclusion,
                       max(market_cap_eur) AS market_cap_eur,
                       array_agg(universe ORDER BY universe) FILTER (WHERE included) AS lists
                FROM membership GROUP BY asset_id
            ), month_ago AS (
                SELECT DISTINCT ON (asset_id) asset_id, letter FROM grade_snapshot
                WHERE model_version_id = :v AND as_of <= :d - 30 ORDER BY asset_id, as_of DESC
            ), spark AS (
                SELECT asset_id, array_agg(round(close_eur::numeric, 10)::float8 ORDER BY ts) AS closes
                FROM price_daily_eur WHERE ts > :d - 90 AND ts <= :d GROUP BY asset_id
            )
            SELECT a.slug, a.asset_class, a.sector, a.country, a.name, a.symbol, g.template_id, g.status,
                   g.letter, g.score, g.quality, g.timing, g.coverage, g.peg_safety, g.price_eur, g.result,
                   l.rank AS mcap_rank, l.included, l.exclusion, l.market_cap_eur, l.lists,
                   m.letter AS letter_month_ago, sp.closes AS spark, (w.asset_id IS NOT NULL) AS watched
            FROM grade_snapshot g
            JOIN asset a ON a.id = g.asset_id
            LEFT JOIN list l ON l.asset_id = g.asset_id
            LEFT JOIN month_ago m ON m.asset_id = g.asset_id
            LEFT JOIN spark sp ON sp.asset_id = g.asset_id
            LEFT JOIN watchlist_item w ON w.asset_id = g.asset_id
            WHERE a.asset_class = ANY(:c)
              AND g.as_of = (SELECT max(as_of) FROM grade_snapshot x
                             WHERE x.asset_id = g.asset_id AND x.model_version_id = :v)
              AND g.model_version_id = :v AND g.as_of > :d - 7
            """
        ), {"d": as_of, "v": jobs.model_version_id, "c": classes, "u": universes,
            "lag": LIST_LAG_DAYS[tab]}).mappings().all()
    out = []
    for r in rows:
        res = r["result"]
        out.append({
            "id": r["slug"], "name": r["name"], "ticker": r["symbol"], "sector": r["sector"],
            "country": r["country"],
            "template": config.templates[r["template_id"]].name_nl, "status": r["status"], "letter": r["letter"],
            "letter_low": res.get("letter_low"), "letter_high": res.get("letter_high"), "score": r["score"],
            "quality": r["quality"], "timing": r["timing"], "coverage": r["coverage"], "peg_safety": r["peg_safety"],
            "price_eur": r["price_eur"], "labels": res.get("labels", []), "reason": res.get("reason_nl"),
            "plus": _pillar_note(res.get("pillars", []), True), "minus": _pillar_note(res.get("pillars", []), False),
            "letter_month_ago": r["letter_month_ago"],
            "in_list": bool(r["included"]) or (tab in TAB_SOURCES and not TAB_SOURCES[tab][1]),
            "exclusion": r["exclusion"],
            "mcap_rank": r["mcap_rank"], "btc_relative": (res.get("btc_relative") or {}).get("letter"),
            "spark": r["spark"] or [], "watched": bool(r["watched"]), "asset_class": r["asset_class"],
            "market_cap_eur": float(r["market_cap_eur"]) if r["market_cap_eur"] is not None else None,
            "lists": [LIST_LABELS.get(u, u) for u in (r["lists"] or [])],
        })
    if tab == "watchlist":
        out = [r for r in out if r["watched"]]
    out.sort(key=lambda x: (STATUS_ORDER.get(x["status"], 9), -(x["score"] or 0), x["mcap_rank"] or 999))
    for i, row in enumerate(out, 1):
        row["rank"] = i
    return {"tab": tab, "as_of": as_of, "rows": out, "model_version": config.version}


@router.get("/regime")
def regime(request: Request, days: int = 400) -> dict:
    """The market regime of the latest day with its three inputs, and the weekly history."""
    jobs = request.app.state.jobs
    with jobs.sf() as session:
        rows = session.execute(text(
            """
            SELECT date, state, score, week_end, inputs FROM market_regime
            WHERE model_version_id = :v ORDER BY date DESC LIMIT :n
            """), {"v": jobs.model_version_id, "n": days}).mappings().all()
    if not rows:
        return {"latest": None, "history": []}
    weekly = {}
    for r in reversed(rows):
        weekly[r["week_end"]] = {"week_end": r["week_end"], "state": r["state"], "score": r["score"]}
    return {"latest": dict(rows[0]), "history": list(weekly.values())}


@router.get("/rates")
def rates(request: Request) -> list[dict]:
    """Government yields for comparison on the bonds tab (latest value and a year ago)."""
    jobs = request.app.state.jobs
    out = []
    with jobs.sf() as session:
        for r in jobs.markets.rates if jobs.markets else []:
            rows = session.execute(text(
                """
                SELECT DISTINCT ON (date) date, value FROM macro_observation WHERE series_id = :s
                ORDER BY date DESC, available_at DESC LIMIT 400
                """), {"s": r.series}).all()
            if not rows:
                continue
            year_ago = next((v for d, v in rows if (rows[0][0] - d).days >= 365), None)
            out.append({"series": r.series, "name": r.name, "date": rows[0][0], "value": float(rows[0][1]),
                        "year_ago": float(year_ago) if year_ago is not None else None})
    return out
