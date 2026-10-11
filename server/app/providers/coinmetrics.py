"""Coin Metrics Community API: on-chain metrics (non-commercial licence)."""

from datetime import UTC, date, datetime

from app.providers.base import Fact, Provider, to_decimal

UNITS = {"USD": "usd", "Ntv": "native", "Cnt": "count", "MVRV": "ratio", "HashRate": "th_s"}


def unit_for(metric: str) -> str:
    for marker, unit in UNITS.items():
        if marker in metric:
            return unit
    return "number"


class CoinMetricsProvider(Provider):
    name = "coinmetrics"

    def catalog(self, metrics: list[str]) -> dict[str, set[str]]:
        """Community assets and which of `metrics` they offer daily: {asset: {metric}}."""
        res = self.get_json("/catalog-v2/asset-metrics", {"metrics": ",".join(metrics), "page_size": 10000})
        out: dict[str, set[str]] = {}
        for item in res.data.get("data", []):
            for m in item.get("metrics", []):
                if any(f.get("frequency") == "1d" for f in m.get("frequencies", [])):
                    out.setdefault(item["asset"], set()).add(m["metric"])
        return out

    def asset_names(self, assets: list[str]) -> dict[str, str]:
        res = self.get_json("/reference-data/assets", {"assets": ",".join(assets), "page_size": 10000})
        return {a["asset"]: a.get("full_name", "") for a in res.data.get("data", [])}

    def timeseries(self, assets: list[str], metrics: list[str], start: date) -> dict[str, list[Fact]]:
        """Daily values per asset since `start`; metrics an asset lacks are skipped by the API."""
        params = {
            "assets": ",".join(assets), "metrics": ",".join(metrics), "frequency": "1d",
            "start_time": start.isoformat(), "page_size": 10000,
            "ignore_forbidden_errors": "true", "ignore_unsupported_errors": "true",
        }
        out: dict[str, list[Fact]] = {}
        today = datetime.now(UTC).date()
        res = self.get_json("/timeseries/asset-metrics", params)
        while True:
            for row in res.data.get("data", []):
                day = date.fromisoformat(row["time"][:10])
                if day >= today:
                    continue
                for metric in metrics:
                    v = to_decimal(row.get(metric))
                    if v is not None:
                        out.setdefault(row["asset"], []).append(
                            Fact(field=f"cm_{metric}", as_of=day, value=v, unit=unit_for(metric), call_id=res.call_id)
                        )
            next_url = res.data.get("next_page_url")
            if not next_url:
                return out
            res = self.get_json(next_url)
