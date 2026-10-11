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


@router.get("/grades")
def grades(request: Request, tab: str = "crypto") -> dict:
    if tab not in ("crypto", "watchlist"):
        return {"tab": tab, "as_of": None, "rows": [], "model_version": request.app.state.model_config.version}
    jobs = request.app.state.jobs
    if jobs.model_version_id is None:
        raise HTTPException(503, "Geen modelversie geladen")
    config = request.app.state.model_config
    with jobs.sf() as session:
        as_of = session.execute(text(
            "SELECT max(as_of) FROM grade_snapshot WHERE model_version_id = :v"
        ), {"v": jobs.model_version_id}).scalar()
        if as_of is None:
            return {"tab": tab, "as_of": None, "rows": [], "model_version": config.version}
        rows = session.execute(text(
            """
            WITH list AS (
                SELECT DISTINCT ON (asset_id) asset_id, rank, included, exclusion FROM universe_membership
                WHERE universe = 'crypto_top' AND as_of <= :d + 1 ORDER BY asset_id, as_of DESC
            ), month_ago AS (
                SELECT DISTINCT ON (asset_id) asset_id, letter FROM grade_snapshot
                WHERE model_version_id = :v AND as_of <= :d - 30 ORDER BY asset_id, as_of DESC
            )
            , spark AS (
                SELECT asset_id, array_agg(round(close_eur::numeric, 10)::float8 ORDER BY ts) AS closes
                FROM price_daily_eur WHERE ts > :d - 90 AND ts <= :d GROUP BY asset_id
            )
            SELECT a.coingecko_id, a.name, a.symbol, g.template_id, g.status, g.letter, g.score, g.quality,
                   g.timing, g.coverage, g.peg_safety, g.price_eur, g.result, l.rank AS mcap_rank, l.included,
                   l.exclusion, m.letter AS letter_month_ago, sp.closes AS spark,
                   (w.asset_id IS NOT NULL) AS watched
            FROM grade_snapshot g
            JOIN asset a ON a.id = g.asset_id
            LEFT JOIN list l ON l.asset_id = g.asset_id
            LEFT JOIN month_ago m ON m.asset_id = g.asset_id
            LEFT JOIN spark sp ON sp.asset_id = g.asset_id
            LEFT JOIN watchlist_item w ON w.asset_id = g.asset_id
            WHERE g.as_of = (SELECT max(as_of) FROM grade_snapshot x
                             WHERE x.asset_id = g.asset_id AND x.model_version_id = :v)
              AND g.model_version_id = :v AND g.as_of > :d - 7
            """
        ), {"d": as_of, "v": jobs.model_version_id}).mappings().all()
    out = []
    for r in rows:
        res = r["result"]
        out.append({
            "id": r["coingecko_id"], "name": r["name"], "ticker": r["symbol"],
            "template": config.templates[r["template_id"]].name_nl, "status": r["status"], "letter": r["letter"],
            "letter_low": res.get("letter_low"), "letter_high": res.get("letter_high"), "score": r["score"],
            "quality": r["quality"], "timing": r["timing"], "coverage": r["coverage"], "peg_safety": r["peg_safety"],
            "price_eur": r["price_eur"], "labels": res.get("labels", []), "reason": res.get("reason_nl"),
            "plus": _pillar_note(res.get("pillars", []), True), "minus": _pillar_note(res.get("pillars", []), False),
            "letter_month_ago": r["letter_month_ago"], "in_list": bool(r["included"]), "exclusion": r["exclusion"],
            "mcap_rank": r["mcap_rank"], "btc_relative": (res.get("btc_relative") or {}).get("letter"),
            "spark": r["spark"] or [], "watched": bool(r["watched"]), "asset_class": "crypto",
        })
    if tab == "watchlist":
        out = [r for r in out if r["watched"]]
    out.sort(key=lambda x: (STATUS_ORDER.get(x["status"], 9), -(x["score"] or 0), x["mcap_rank"] or 999))
    for i, row in enumerate(out, 1):
        row["rank"] = i
    return {"tab": tab, "as_of": as_of, "rows": out, "model_version": config.version}
