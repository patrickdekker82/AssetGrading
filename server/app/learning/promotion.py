"""The tests a challenger must pass before the owner can promote it (chapter 8, "Kampioen en uitdager").

Everything is measured only on the templates whose weights the challenger changes, pooled per month with
equal weight per template. Backtest numbers come from the latest finished backtest of each model version.
"""

import json
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.evaluation import metrics
from app.evaluation.outcomes import EvaluationSettings, measurement_frame, to_json
from app.learning import stats
from app.learning.registry import config_of, last_switch, weights_of


def changed_templates(session: Session, challenger_vid: int, champion_vid: int) -> list[str]:
    a, b = config_of(session, challenger_vid), config_of(session, champion_vid)
    return [t for t in a.templates if a.templates[t].pillars and weights_of(a, t) != weights_of(b, t)]


def latest_run(session: Session, model_version_id: int) -> int | None:
    return session.execute(text("SELECT max(id) FROM backtest_run WHERE status = 'ok' AND model_version_id = :v"),
                           {"v": model_version_id}).scalar()


def _frame(session, source, run_id, vid, h, templates) -> pd.DataFrame:
    df = measurement_frame(session, source, run_id, vid, h)
    return df[df["template_id"].isin(templates)] if not df.empty else df


def pooled_ic(df: pd.DataFrame, min_assets: int) -> pd.Series:
    """Per month the average rank correlation over the templates (equal weight per template)."""
    if df.empty:
        return pd.Series(dtype=float)
    per = [metrics.ic_series(g, "score", "excess", min_assets) for _, g in df.groupby("template_id")]
    per = [s for s in per if len(s)]
    return pd.concat(per, axis=1).mean(axis=1).sort_index() if per else pd.Series(dtype=float)


def pooled_long_short(df: pd.DataFrame, min_assets: int) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)
    per = [stats.long_short(g, min_assets=min_assets) for _, g in df.groupby("template_id")]
    per = [s for s in per if len(s)]
    return pd.concat(per, axis=1).mean(axis=1).sort_index() if per else pd.Series(dtype=float)


def _check(id_: str, label: str, passed: bool, value, required: str) -> dict:
    return {"id": id_, "label_nl": label, "passed": bool(passed), "value": value, "required": required}


def run_checks(session: Session, settings: EvaluationSettings, challenger_id: int,
               now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    cfg = settings.raw["learning"]["promotion"]
    h = int(cfg["horizon_months"])
    min_assets = int(settings.raw.get("min_assets_per_month", 5))
    c = session.execute(text("SELECT * FROM challenger WHERE id = :i"), {"i": challenger_id}).mappings().first()
    ch, champ = c["model_version_id"], c["champion_version_id"]
    templates = changed_templates(session, ch, champ)
    checks = []

    months = (now.year - c["started_at"].year) * 12 + now.month - c["started_at"].month \
        - (1 if now.day < c["started_at"].day else 0)
    checks.append(_check("shadow_months", "Minstens 6 maanden schaduwgrades", months >= cfg["min_shadow_months"],
                         months, f">= {cfg['min_shadow_months']} maanden"))

    run_ch, run_champ = latest_run(session, ch), latest_run(session, champ)
    checks.append(_check("backtests", "Terugtest van uitdager en kampioen",
                         run_ch is not None and run_champ is not None,
                         {"uitdager": run_ch, "kampioen": run_champ}, "beide klaar"))
    lags = max(h - 1, 0)
    if run_ch and run_champ:
        f_ch = _frame(session, "backtest", run_ch, ch, h, templates)
        f_cp = _frame(session, "backtest", run_champ, champ, h, templates)
        ic_ch, ic_cp = pooled_ic(f_ch, min_assets), pooled_ic(f_cp, min_assets)
        own = metrics.newey_west(ic_ch, lags)["t"]
        checks.append(_check("t_own", "Eigen t-waarde in de terugtest", own is not None and own >= cfg["min_t_own"],
                             own, f">= {cfg['min_t_own']}"))
        diff = (ic_ch - ic_cp).dropna()
        imp = metrics.newey_west(diff, lags)["t"]
        checks.append(_check("t_improvement", "Verbetering ten opzichte van de kampioen (t-waarde)",
                             imp is not None and imp >= cfg["min_t_improvement"], imp,
                             f">= {cfg['min_t_improvement']}"))

        # Deflated Sharpe and PBO over every model configuration ever backtested (the recorded trials).
        trials = session.execute(text("SELECT count(*) FROM model_version")).scalar()
        series = {}
        for vid, run in session.execute(text(
                "SELECT model_version_id, max(id) FROM backtest_run WHERE status = 'ok' GROUP BY model_version_id")):
            ls = pooled_long_short(_frame(session, "backtest", run, vid, 1, templates), min_assets)
            if len(ls):
                series[vid] = ls
        srs = [s for s in (stats.sharpe(x) for x in series.values()) if s is not None]
        var = float(pd.Series(srs).var()) if len(srs) >= 2 else None
        dsr = stats.deflated_sharpe(series.get(ch, pd.Series(dtype=float)), trials, var)
        checks.append(_check("deflated_sharpe", "Deflated Sharpe Ratio", dsr["dsr"] is not None
                             and dsr["dsr"] > cfg["min_deflated_sharpe"], dsr, f"> {cfg['min_deflated_sharpe']}"))
        p = stats.pbo(pd.DataFrame(series))
        checks.append(_check("pbo", "Kans op overfitting (PBO)", p["pbo"] is not None and p["pbo"] < cfg["max_pbo"],
                             p, f"< {cfg['max_pbo']}"))

        order_ok, turn_ok, dd_ok, detail = True, True, True, {}
        for t in templates:
            a, b = f_ch[f_ch["template_id"] == t], f_cp[f_cp["template_id"] == t]
            la = metrics.letter_stats(a, lags, [], -1)
            lb = metrics.letter_stats(b, lags, [], -1)
            inv_a, inv_b = la["order"]["inversions"], lb["order"]["inversions"]
            if inv_a is not None and inv_b is not None and inv_a > inv_b:
                order_ok = False
            ta, tb = metrics.turnover(a)["letter_changed"], metrics.turnover(b)["letter_changed"]
            if ta is not None and tb is not None and ta > tb * cfg["max_turnover_ratio"]:
                turn_ok = False
            da = a[a["letter"].str.startswith("A", na=False)]["drawdown"].mean()
            db = b[b["letter"].str.startswith("A", na=False)]["drawdown"].mean()
            if pd.notna(da) and pd.notna(db) and da < db - 1e-9:
                dd_ok = False
            detail[t] = {"inversions": [inv_a, inv_b], "turnover": [ta, tb],
                         "a_drawdown": [None if pd.isna(da) else float(da), None if pd.isna(db) else float(db)]}
        checks.append(_check("order", "Volgorde A tot F niet slechter", order_ok, detail, "omkeringen <= kampioen"))
        checks.append(_check("turnover", "Wisselingen hoogstens 20% hoger", turn_ok, detail,
                             f"<= {cfg['max_turnover_ratio']} x kampioen"))
        checks.append(_check("drawdown", "Daling van de beste groep niet groter", dd_ok, detail,
                             "gemiddelde daling A >= kampioen"))

    live_ch = pooled_ic(_frame(session, "live", None, ch, 1, templates), min_assets)
    live_cp = pooled_ic(_frame(session, "live", None, champ, 1, templates), min_assets)
    live_diff = (live_ch - live_cp).dropna()
    nw = metrics.newey_west(live_diff, 0, min_n=3)
    live_ok = nw["n"] >= 3 and (nw["t"] is None or nw["t"] >= cfg["live_not_worse_t"])
    checks.append(_check("live", "Live schaduwresultaat niet duidelijk slechter", live_ok,
                         {"months": nw["n"], "mean_difference": nw["mean"], "t": nw["t"]},
                         f"minstens 3 maanden, t >= {cfg['live_not_worse_t']}"))

    previous = last_switch(session)
    gap = None if previous is None else round((now - previous).days / 30.44, 1)
    checks.append(_check("frequency", "Hoogstens één wissel per 6 maanden",
                         gap is None or gap >= cfg["min_months_between_switches"], gap,
                         f">= {cfg['min_months_between_switches']} maanden sinds de vorige wissel"))
    session.execute(text("UPDATE challenger SET checks = :c, checked_at = now() WHERE id = :i"),
                    {"c": json.dumps(to_json(checks)), "i": challenger_id})
    session.commit()
    return checks
