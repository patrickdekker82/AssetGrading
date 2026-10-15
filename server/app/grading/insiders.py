"""Insider buying for stocks (chapter 6, Aandeel algemeen, pillar Revisies en sentiment).

The metric is the number of different directors and officers who bought shares on the open market in the six
months up to the grading day, as known from their Form 4 filings on that day. Left out:
- trades under a pre-arranged 10b5-1 plan (stated on forms since April 2023);
- routine buyers: an insider who bought in the same calendar month in each of the three years before
  (Cohen, Malloy and Pomorski, 2012) – their trades carry no information.
Only US companies file Form 4; for the others the metric stays empty.
"""

from datetime import date, timedelta

import pandas as pd

WINDOW_DAYS = 182
ROUTINE_YEARS = 3
HISTORY_DAYS = WINDOW_DAYS + 365 * ROUTINE_YEARS + 31
INSIDER_MAX_GAP_DAYS = 21       # newest known filing at most this long before the grading day


def insider_buyers(df: pd.DataFrame, as_of: date) -> int:
    """`df`: purchase rows known on the grading day (owner_cik, is_director, is_officer, plan_10b5_1,
    first_trade, last_trade, purchase_value)."""
    if df is None or df.empty:
        return 0
    rows = df[(df["purchase_value"] > 0) & (df["is_director"] | df["is_officer"])]
    rows = rows[rows["plan_10b5_1"].fillna(False).astype(bool) == False]  # noqa: E712 - pandas mask
    if rows.empty:
        return 0
    start = as_of - timedelta(days=WINDOW_DAYS)
    trade = rows["last_trade"].where(rows["last_trade"].notna(), rows["first_trade"])
    in_window = rows[(trade > start) & (trade <= as_of)]
    buyers = 0
    for owner, g in in_window.groupby("owner_cik"):
        history = rows[rows["owner_cik"] == owner]
        months = {(d.year, d.month) for d in history["first_trade"].dropna()}
        recent = {(d.year, d.month) for d in g["first_trade"].dropna()} or {(as_of.year, as_of.month)}
        routine = all(all((y - k, m) in months for k in range(1, ROUTINE_YEARS + 1)) for y, m in recent)
        if not routine:
            buyers += 1
    return buyers
