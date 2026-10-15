"""Insider filings (SEC Form 4) for the followed US companies.

History comes from SEC's quarterly data sets (one download per quarter, from `insider.history_start`); after
the last published quarter, single filings are fetched from each company's filing list, which the stocks run
already reads. A company added later gets its history filing by filing (`new_company_years`). Every row is
stored once (append-only, keyed by filing and owner).
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.ingest.report import Report
from app.providers import ProviderError
from app.providers.config import ProvidersConfig
from app.providers.registry import Providers
from app.providers.sec_insider import InsiderFiling


def quarter_of(d: date) -> str:
    return f"{d.year}q{(d.month - 1) // 3 + 1}"


def quarter_end(q: str) -> date:
    year, n = int(q[:4]), int(q[5])
    return date(year + (n == 4), (n * 3) % 12 + 1, 1) - timedelta(days=1)


def quarters(start: date, until: date) -> list[str]:
    """Completed quarters from the one containing `start` up to the last that ended before `until`."""
    out, q = [], quarter_of(start)
    while quarter_end(q) < until:
        out.append(q)
        year, n = int(q[:4]), int(q[5])
        q = f"{year + (n == 4)}q{n % 4 + 1}"
    return out


def store(session: Session, asset_of: dict[int, int], rows: list[InsiderFiling], source: str) -> int:
    added = 0
    now = datetime.now(UTC)
    for r in rows:
        asset_id = asset_of.get(r.issuer_cik)
        if asset_id is None:
            continue
        added += session.execute(text(
            """INSERT INTO insider_filing (asset_id, accession, owner_cik, owner_name, is_director, is_officer,
                   is_ten_pct, plan_10b5_1, first_trade, last_trade, purchase_shares, purchase_value, sale_shares,
                   sale_value, filed_at, source, fetched_at, call_id)
               VALUES (:a, :acc, :o, :name, :d, :off, :ten, :plan, :first, :last, :ps, :pv, :ss, :sv, :filed, :src,
                       :now, :call)
               ON CONFLICT (accession, owner_cik) DO NOTHING"""),
            {"a": asset_id, "acc": r.accession, "o": r.owner_cik, "name": r.owner_name, "d": r.is_director,
             "off": r.is_officer, "ten": r.is_ten_pct, "plan": r.plan_10b5_1, "first": r.first_trade,
             "last": r.last_trade, "ps": r.purchase_shares, "pv": r.purchase_value, "ss": r.sale_shares,
             "sv": r.sale_value, "filed": r.filed_at, "src": source, "now": now, "call": r.call_id}).rowcount
    return added


def _followed(session: Session) -> dict[int, int]:
    """SEC CIK -> asset id of every followed stock with a CIK."""
    rows = session.execute(text(
        """SELECT DISTINCT ON (al.value) al.value::int AS cik, a.id
           FROM asset_alias al JOIN asset a ON a.id = al.asset_id
           WHERE al.kind = 'sec_cik' AND a.tracked AND a.asset_class = 'stock' ORDER BY al.value, a.id"""))
    return {r.cik: r.id for r in rows}


def update_insiders(sf: sessionmaker[Session], providers: Providers, cfg: ProvidersConfig,
                    filings_by_asset: dict[int, tuple[int, list[dict]]], report: Report,
                    today: date | None = None) -> None:
    if "sec_insider" not in cfg.providers:
        return
    today = today or datetime.now(UTC).date()
    settings = cfg.insider
    provider = providers.get("sec_insider")
    with sf() as session:
        asset_of = _followed(session)
        done = {r.quarter: r.processed_at for r in session.execute(
            text("SELECT quarter, processed_at FROM insider_dataset"))}
    if not asset_of:
        return
    # 1. Quarterly data sets not read yet. A quarter is published some weeks after it ends; a missing one is
    #    tried again the next run.
    for q in quarters(date.fromisoformat(settings.history_start), today):
        if q in done:
            continue
        try:
            rows = provider.dataset(q, set(asset_of))
        except ProviderError as exc:
            report.error(f"insider {q}: {exc}")
            break
        if rows is None:
            break                                   # not published yet: later quarters are not either
        with sf() as session:
            report.add("insider_rows_added", store(session, asset_of, rows, "sec_bulk"))
            session.execute(text("INSERT INTO insider_dataset (quarter, processed_at, filings) VALUES (:q, :t, :n)"),
                            {"q": q, "t": datetime.now(UTC), "n": len(rows)})
            session.commit()
        done[q] = datetime.now(UTC)
        report.add("insider_quarters_read")
    # 2. Single filings after the last quarter read; for a company added after the first data set, its history.
    covered_until = max((quarter_end(q) for q in done), default=None)
    first_read = min(done.values(), default=None)
    with sf() as session:
        known = {r.accession for r in session.execute(text(
            "SELECT DISTINCT accession FROM insider_filing WHERE asset_id = ANY(:ids)"),
            {"ids": list(asset_of.values())})}
        since = {r.id: r.tracked_since for r in session.execute(text(
            "SELECT id, tracked_since FROM asset WHERE id = ANY(:ids)"), {"ids": list(asset_of.values())})}
    budget = settings.max_filings_per_run
    for asset_id, (cik, filings) in filings_by_asset.items():
        if asset_id not in asset_of.values():
            continue
        added_later = first_read is not None and since.get(asset_id) is not None \
            and since[asset_id] > first_read.date()
        if covered_until is not None and not added_later:
            cutoff = covered_until
        else:
            cutoff = today - timedelta(days=round(365.25 * settings.new_company_years))
        for f in filings:
            if f["accession"] in known or date.fromisoformat(f["filed"]) <= cutoff:
                continue
            if budget <= 0:
                report.notes.append("insider: maximum aantal formulieren per run bereikt; de rest volgt de "
                                    "volgende run")
                return
            budget -= 1
            accepted = _accepted(f)
            try:
                rows = provider.form4(cik, f["accession"], f["primary"], accepted)
            except ProviderError as exc:
                report.error(f"insider {f['accession']}: {exc}")
                continue
            with sf() as session:
                report.add("insider_rows_added", store(session, {cik: asset_id}, rows, "sec_form4"))
                session.commit()
            known.add(f["accession"])


def _accepted(f: dict) -> datetime:
    """When the filing became public: EDGAR's acceptance time, else the end of the filing day."""
    raw = f.get("accepted")
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.combine(date.fromisoformat(f["filed"]), datetime.max.time(), tzinfo=UTC)
