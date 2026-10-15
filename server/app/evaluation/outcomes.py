"""Outcome labels after 1, 3, 6 and 12 months (chapter 8): total return, return above the benchmark of the
class and the largest fall within the period. Only closed periods count: an outcome exists once the end of
its horizon has passed and prices up to that day are stored.
"""

import calendar
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml
from sqlalchemy import text
from sqlalchemy.orm import Session

STALE_DAYS = 7          # a price older than this at the start or end of a period does not count
# A one-day move beyond this factor outside crypto is a data error (e.g. a pence/pound switch in a London
# listing), not a return: such a period gets no outcome.
MAX_DAILY_JUMP = 5.0


def month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def add_months(d: date, months: int) -> date:
    """The last calendar day of the month `months` after d's month."""
    y, m = divmod(d.month - 1 + months, 12)
    return month_end(date(d.year + y, m + 1, 1))


def last_weekday(d: date) -> date:
    """The last weekday of d's month: the month-end grading day (also for crypto, to keep one calendar)."""
    e = month_end(d)
    while e.weekday() >= 5:
        e -= timedelta(days=1)
    return e


def month_ends(start: date, end: date) -> list[date]:
    out, d = [], date(start.year, start.month, 1)
    while d <= end:
        e = last_weekday(d)
        if start <= e <= end:
            out.append(e)
        d = month_end(d) + timedelta(days=1)
    return out


@dataclass
class EvaluationSettings:
    horizons: list[int]
    benchmarks: dict
    raw: dict

    @classmethod
    def load(cls, path: Path) -> "EvaluationSettings":
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls([int(h) for h in raw["horizons_months"]], raw["benchmarks"], raw)

    def benchmark_for(self, template_id: str, country: str | None) -> str | None:
        b = self.benchmarks.get(template_id)
        if isinstance(b, dict):
            return (b.get("by_country") or {}).get(country or "", b.get("default"))
        return b


@dataclass
class GradeRow:
    asset_id: int
    asset_class: str
    country: str | None
    template_id: str
    as_of: date


def load_prices(session: Session, asset_ids: list[int]) -> dict[int, pd.Series]:
    """Daily closes in euro; currency pairs in their own quote (the pair rate is the return)."""
    rows = session.execute(text(
        """
        SELECT p.asset_id, p.ts, CASE WHEN a.asset_class = 'fx' THEN p.close_native ELSE p.close_eur END AS c
        FROM price_daily_eur p JOIN asset a ON a.id = p.asset_id
        WHERE p.asset_id = ANY(:ids) ORDER BY p.asset_id, p.ts
        """), {"ids": asset_ids}).all()
    by: dict[int, list] = defaultdict(list)
    for r in rows:
        if r.c is not None:
            by[r.asset_id].append((r.ts if isinstance(r.ts, date) else r.ts.date(), float(r.c)))
    return {k: pd.Series([v for _, v in xs], index=[d for d, _ in xs]) for k, xs in by.items()}


def period(s: pd.Series, start: date, end: date, max_jump: float | None = MAX_DAILY_JUMP) -> tuple[float, float] | None:
    """Total return and largest fall from the close at `start` to the close at `end`, or None."""
    if s is None or s.empty:
        return None
    before = s.loc[:start]
    upto = s.loc[:end]
    if before.empty or upto.empty or (start - before.index[-1]).days > STALE_DAYS \
            or (end - upto.index[-1]).days > STALE_DAYS:
        return None
    path = s.loc[before.index[-1]:upto.index[-1]]
    # A price at or below zero (WTI futures, April 2020) makes a return meaningless.
    if len(path) < 2 or (path <= 0).any():
        return None
    if max_jump is not None:
        step = path / path.shift()
        if ((step > max_jump) | (step < 1 / max_jump)).any():
            return None
    drawdown = float((path / path.cummax() - 1).min())
    return float(path.iloc[-1] / path.iloc[0] - 1), drawdown


def compute_outcomes(grades: list[GradeRow], prices: dict[int, pd.Series], bench: dict[str, pd.Series],
                     settings: EvaluationSettings, today: date) -> list[dict]:
    out = []
    pending_avg: list[dict] = []
    for g in grades:
        for h in settings.horizons:
            end = add_months(g.as_of, h)
            if end >= today:
                continue
            res = period(prices.get(g.asset_id), g.as_of, end, None if g.asset_class == "crypto" else MAX_DAILY_JUMP)
            if res is None:
                continue
            total, dd = res
            row = {"asset_id": g.asset_id, "as_of": g.as_of, "horizon_months": h, "end_date": end,
                   "total_return": total, "max_drawdown": dd, "template_id": g.template_id,
                   "asset_class": g.asset_class}
            b = settings.benchmark_for(g.template_id, g.country)
            if b == "class_average":
                pending_avg.append(row)
                continue
            if b is None:
                out.append({**row, "benchmark": None, "benchmark_return": None, "excess_return": total})
                continue
            br = period(bench.get(b), g.as_of, end)
            if br is None:
                continue
            out.append({**row, "benchmark": b, "benchmark_return": br[0], "excess_return": total - br[0]})
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in pending_avg:
        groups[(r["template_id"], r["asset_class"], r["as_of"], r["horizon_months"])].append(r)
    for rows in groups.values():
        avg = sum(r["total_return"] for r in rows) / len(rows)
        for r in rows:
            out.append({**r, "benchmark": "class_average", "benchmark_return": avg,
                        "excess_return": r["total_return"] - avg})
    return out


def benchmark_ids(session: Session, settings: EvaluationSettings) -> dict[str, int]:
    slugs = set()
    for b in settings.benchmarks.values():
        if isinstance(b, dict):
            slugs |= set((b.get("by_country") or {}).values()) | {b.get("default")}
        elif b and b != "class_average":
            slugs.add(b)
    rows = session.execute(text("SELECT slug, id FROM asset WHERE slug = ANY(:s)"),
                           {"s": sorted(x for x in slugs if x)})
    return {r.slug: r.id for r in rows}


def store_outcomes(session: Session, rows: list[dict], source: str, run_id: int | None, model_version_id: int) -> int:
    added = 0
    for i in range(0, len(rows), 1000):
        chunk = [{**{k: r[k] for k in ("asset_id", "as_of", "horizon_months", "end_date", "total_return",
                                        "benchmark", "benchmark_return", "excess_return", "max_drawdown")},
                  "source": source, "run_id": run_id, "v": model_version_id} for r in rows[i:i + 1000]]
        if not chunk:
            continue
        res = session.execute(text(
            """
            INSERT INTO outcome (source, run_id, model_version_id, asset_id, as_of, horizon_months, end_date,
                                 total_return, benchmark, benchmark_return, excess_return, max_drawdown)
            VALUES (:source, :run_id, :v, :asset_id, :as_of, :horizon_months, :end_date, :total_return,
                    :benchmark, :benchmark_return, :excess_return, :max_drawdown)
            ON CONFLICT DO NOTHING
            """), chunk)
        added += res.rowcount or 0
    return added


def grade_source_sql(source: str) -> str:
    """Month-end grades: the backtest rows of a run, or per asset the last live grade of each closed month
    (only when it falls in the last days of that month)."""
    if source == "backtest":
        return "SELECT * FROM backtest_snapshot WHERE run_id = :run AND model_version_id = :v"
    return """
        SELECT * FROM (
            SELECT DISTINCT ON (asset_id, date_trunc('month', as_of)) * FROM grade_snapshot
            WHERE model_version_id = :v ORDER BY asset_id, date_trunc('month', as_of), as_of DESC
        ) m
        WHERE as_of >= (date_trunc('month', as_of) + interval '1 month' - interval '4 days')::date
    """


def update_outcomes(session: Session, settings: EvaluationSettings, source: str, run_id: int | None,
                    model_version_id: int, today: date) -> int:
    """Compute and store every outcome that has become known and is not stored yet."""
    rows = session.execute(text(
        f"""
        SELECT g.asset_id, a.asset_class, a.country, g.template_id, g.as_of
        FROM ({grade_source_sql(source)}) g JOIN asset a ON a.id = g.asset_id
        WHERE g.status IN ('graded', 'provisional', 'speculative')
        """), {"run": run_id, "v": model_version_id}).all()
    grades = [GradeRow(r.asset_id, r.asset_class, r.country, r.template_id, r.as_of) for r in rows]
    if not grades:
        return 0
    bench_ids = benchmark_ids(session, settings)
    prices = load_prices(session, sorted({g.asset_id for g in grades} | set(bench_ids.values())))
    bench = {slug: prices.get(i) for slug, i in bench_ids.items()}
    return store_outcomes(session, compute_outcomes(grades, prices, bench, settings, today), source, run_id,
                          model_version_id)


def measurement_frame(session: Session, source: str, run_id: int | None, model_version_id: int,
                      horizon: int) -> pd.DataFrame:
    """One row per graded month-end with its outcome over `horizon`, for metrics.measure()."""
    rows = session.execute(text(
        f"""
        SELECT g.asset_id, g.as_of, g.template_id, g.score, g.letter, g.result, g.inputs,
               o.excess_return AS excess, o.max_drawdown AS drawdown
        FROM ({grade_source_sql(source)}) g
        LEFT JOIN outcome o ON o.asset_id = g.asset_id AND o.as_of = g.as_of AND o.horizon_months = :h
             AND o.source = :src AND o.model_version_id = :v AND COALESCE(o.run_id, 0) = COALESCE(:run, 0)
        WHERE g.status IN ('graded', 'provisional') AND g.score IS NOT NULL
        """), {"run": run_id, "v": model_version_id, "h": horizon, "src": source}).all()
    records = []
    for r in rows:
        rec = {"asset_id": r.asset_id, "as_of": r.as_of, "template_id": r.template_id, "score": r.score,
               "letter": r.letter, "excess": r.excess, "drawdown": r.drawdown,
               "regime": ((r.inputs or {}).get("grade_input") or {}).get("regime")}
        for p in (r.result or {}).get("pillars", []):
            rec[f"p_{p['id']}"] = p.get("score")
        records.append(rec)
    return pd.DataFrame.from_records(records)


def to_json(obj):
    """JSON-safe copy (dates and numpy numbers)."""
    return json.loads(json.dumps(obj, default=lambda o: o.isoformat() if hasattr(o, "isoformat") else float(o)))
