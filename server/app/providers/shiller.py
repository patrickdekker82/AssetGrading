"""Robert Shiller's monthly S&P 500 data (shillerdata.com): the CAPE ratio and the excess CAPE yield.
Free, no key; published for research with a disclaimer (no guarantee of accuracy).

The spreadsheet's address changes when it is updated, so the adapter reads it from the data page.
"""

import re
from datetime import date, timedelta

import xlrd

from app.providers.base import Provider, ProviderError

# The data page links the file without a scheme ("//img1.wsimg.com/.../ie_data.xls?ver=...").
LINK = re.compile(r"""(?:https?:)?//[^"'\s<>]+?/ie_data\.xls[^"'\s<>]*""")


def month_end(year: int, month: int) -> date:
    first_next = date(year + (month == 12), month % 12 + 1, 1)
    return first_next - timedelta(days=1)


def parse_ie_data(content: bytes) -> list[tuple[date, float | None, float | None]]:
    """[(month end, CAPE, excess CAPE yield)] from ie_data.xls."""
    sheet = xlrd.open_workbook(file_contents=content).sheet_by_name("Data")
    return parse_rows([sheet.row_values(r) for r in range(sheet.nrows)])


def parse_rows(rows: list[list]) -> list[tuple[date, float | None, float | None]]:
    """The sheet's rows. Columns are found by their header text (first eight rows), so a new column in a
    later edition does not shift the values."""
    width = max((len(r) for r in rows), default=0)
    labels = [" ".join(" ".join(str(r[c]).strip() for r in rows[:8] if c < len(r)).split()).lower()
              for c in range(width)]
    cape_col = next((c for c, h in enumerate(labels) if "p/e10" in h and "tr p/e10" not in h), None)
    ecy_col = next((c for c, h in enumerate(labels) if "excess cape yield" in h), None)
    if cape_col is None:
        raise ValueError("CAPE column not found in ie_data.xls")
    out = []
    for row in rows:
        stamp = row[0] if row else None
        if not isinstance(stamp, float) or stamp < 1871:
            continue
        year = int(stamp)
        month = round((stamp - year) * 100)       # 2024.1 is October, 2024.01 January
        if 1 <= month <= 12:
            out.append((month_end(year, month), _num(row, cape_col), _num(row, ecy_col)))
    return out


def _num(row: list, col: int | None) -> float | None:
    if col is None or col >= len(row):
        return None
    return float(row[col]) if isinstance(row[col], float) else None


class ShillerProvider(Provider):
    name = "shiller"

    def data_link(self) -> str:
        page = self.get_text("/")
        found = LINK.search(page.data)
        if not found:
            raise ProviderError("shiller: no link to ie_data.xls on the data page")
        link = found.group(0).replace("&amp;", "&")
        return "https:" + link if link.startswith("//") else link

    def monthly(self) -> tuple[list[tuple[date, float | None, float | None]], int | None]:
        res = self.get_bytes(self.data_link())
        try:
            return parse_ie_data(res.data), res.call_id
        except (xlrd.XLRDError, ValueError, KeyError) as exc:
            raise ProviderError(f"shiller: unreadable spreadsheet ({exc})") from exc
