"""Insider transactions from SEC Form 4 (free, the same User-Agent rule as the rest of EDGAR).

Two routes to the same rows:
- the quarterly "Insider Transactions Data Sets" (one zip per quarter, all Form 3/4/5 filings): history, read
  once per quarter and filtered to the companies the app follows;
- the Form 4 XML of a single filing: everything after the last published quarter.

Per filing and reporting owner the adapter keeps the open-market purchases (code P) and sales (code S) of
non-derivative securities; grants, option exercises and gifts are left out. Amendments (4/A) are skipped so a
corrected filing never counts twice.
"""

import csv
import io
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from app.providers.base import Provider, ProviderError

DATASET_URL = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{q}_form345.zip"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"


@dataclass
class InsiderFiling:
    accession: str
    issuer_cik: int
    owner_cik: str
    owner_name: str | None
    is_director: bool
    is_officer: bool
    is_ten_pct: bool
    plan_10b5_1: bool | None
    filed_at: datetime
    first_trade: date | None = None
    last_trade: date | None = None
    purchase_shares: float = 0.0
    purchase_value: float = 0.0
    sale_shares: float = 0.0
    sale_value: float = 0.0
    call_id: int | None = None


@dataclass
class _Trades:
    first: date | None = None
    last: date | None = None
    buy_shares: float = 0.0
    buy_value: float = 0.0
    sell_shares: float = 0.0
    sell_value: float = 0.0

    def add(self, day: date | None, code: str, acq: str, shares: float | None, price: float | None) -> None:
        if code not in ("P", "S") or not shares:
            return
        value = shares * (price or 0.0)
        if code == "P" and acq == "A":
            self.buy_shares += shares
            self.buy_value += value
        elif code == "S" and acq == "D":
            self.sell_shares += shares
            self.sell_value += value
        else:
            return
        if day:
            self.first = min(self.first or day, day)
            self.last = max(self.last or day, day)


def _float(s: str | None) -> float | None:
    try:
        return float(s) if s not in (None, "") else None
    except ValueError:
        return None


def _flag(s: str | None) -> bool | None:
    if s is None or s.strip() == "":
        return None
    return s.strip().lower() in ("1", "true")


def _dmy(s: str) -> date | None:
    try:
        return datetime.strptime(s.strip(), "%d-%b-%Y").date()
    except (ValueError, AttributeError):
        return None


def _end_of_day(d: date) -> datetime:
    return datetime.combine(d, time(23, 59, 59), tzinfo=UTC)


def _owners(relationship: str) -> tuple[bool, bool, bool]:
    r = relationship.lower()
    return "director" in r, "officer" in r, "tenpercentowner" in r.replace(" ", "")


def parse_dataset(content: bytes, issuer_ciks: set[int]) -> list[InsiderFiling]:
    """Form 4 filings of the given issuers from one quarterly data set (zip)."""
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        def rows(name: str):
            with z.open(name) as f:
                text = io.TextIOWrapper(f, encoding="utf-8", errors="replace", newline="")
                yield from csv.DictReader(text, delimiter="\t", quoting=csv.QUOTE_NONE)

        subs = {}
        for r in rows("SUBMISSION.tsv"):
            if r.get("DOCUMENT_TYPE") != "4":
                continue
            try:
                cik = int(r.get("ISSUERCIK") or 0)
            except ValueError:
                continue
            filed = _dmy(r.get("FILING_DATE") or "")
            if cik in issuer_ciks and filed:
                subs[r["ACCESSION_NUMBER"]] = (cik, filed, _flag(r.get("AFF10B5ONE")))
        trades: dict[str, _Trades] = {acc: _Trades() for acc in subs}
        for r in rows("NONDERIV_TRANS.tsv"):
            t = trades.get(r.get("ACCESSION_NUMBER", ""))
            if t is not None:
                t.add(_dmy(r.get("TRANS_DATE") or ""), (r.get("TRANS_CODE") or "").strip(),
                      (r.get("TRANS_ACQUIRED_DISP_CD") or "").strip(), _float(r.get("TRANS_SHARES")),
                      _float(r.get("TRANS_PRICEPERSHARE")))
        out = []
        for r in rows("REPORTINGOWNER.tsv"):
            acc = r.get("ACCESSION_NUMBER", "")
            if acc not in subs:
                continue
            cik, filed, plan = subs[acc]
            d, o, ten = _owners(r.get("RPTOWNER_RELATIONSHIP") or "")
            t = trades[acc]
            out.append(InsiderFiling(acc, cik, (r.get("RPTOWNERCIK") or "").lstrip("0") or "0",
                                     (r.get("RPTOWNERNAME") or "").strip() or None, d, o, ten, plan,
                                     _end_of_day(filed), t.first, t.last, t.buy_shares, t.buy_value,
                                     t.sell_shares, t.sell_value))
    return out


def _text(el: ET.Element | None, path: str) -> str | None:
    if el is None:
        return None
    found = el.find(path)
    return found.text.strip() if found is not None and found.text else None


def parse_form4(xml: str, accession: str, filed_at: datetime) -> list[InsiderFiling]:
    """One Form 4 XML document: a row per reporting owner."""
    root = ET.fromstring(xml)
    if _text(root, "documentType") != "4":
        return []
    issuer = int(_text(root, "issuer/issuerCik") or 0)
    plan = _flag(_text(root, "aff10b5One"))
    t = _Trades()
    for tr in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        day = _text(tr, "transactionDate/value")
        t.add(date.fromisoformat(day[:10]) if day else None, _text(tr, "transactionCoding/transactionCode") or "",
              _text(tr, "transactionAmounts/transactionAcquiredDisposedCode/value") or "",
              _float(_text(tr, "transactionAmounts/transactionShares/value")),
              _float(_text(tr, "transactionAmounts/transactionPricePerShare/value")))
    out = []
    for owner in root.findall("reportingOwner"):
        rel = owner.find("reportingOwnerRelationship")
        out.append(InsiderFiling(
            accession, issuer, (_text(owner, "reportingOwnerId/rptOwnerCik") or "0").lstrip("0") or "0",
            _text(owner, "reportingOwnerId/rptOwnerName"), bool(_flag(_text(rel, "isDirector"))),
            bool(_flag(_text(rel, "isOfficer"))), bool(_flag(_text(rel, "isTenPercentOwner"))), plan, filed_at,
            t.first, t.last, t.buy_shares, t.buy_value, t.sell_shares, t.sell_value))
    return out


class SecInsiderProvider(Provider):
    name = "sec_insider"

    def auth_headers(self) -> dict[str, str]:
        agent = os.environ.get("SEC_USER_AGENT") or "Graadmeter private research tool admin@example.org"
        return {"User-Agent": agent}

    def dataset(self, quarter: str, issuer_ciks: set[int]) -> list[InsiderFiling] | None:
        """None when the quarter is not published yet."""
        try:
            res = self.get_bytes(DATASET_URL.format(q=quarter))
        except ProviderError as exc:
            if exc.status_code in (403, 404):
                return None
            raise
        try:
            rows = parse_dataset(res.data, issuer_ciks)
        except (zipfile.BadZipFile, KeyError) as exc:
            raise ProviderError(f"sec_insider {quarter}: unreadable data set ({exc})") from exc
        for r in rows:
            r.call_id = res.call_id
        return rows

    def form4(self, cik: int, accession: str, primary_document: str, filed_at: datetime) -> list[InsiderFiling]:
        # The primary document is the rendered page (xslF345X06/form4.xml); the raw XML has the same name
        # without the style-sheet folder.
        doc = re.sub(r"^xsl[^/]*/", "", primary_document)
        res = self.get_text(ARCHIVE_URL.format(cik=cik, acc=accession.replace("-", ""), doc=doc))
        try:
            rows = parse_form4(res.data, accession, filed_at)
        except ET.ParseError as exc:
            raise ProviderError(f"sec_insider {accession}: unreadable Form 4 ({exc})") from exc
        for r in rows:
            r.call_id = res.call_id
        return rows
