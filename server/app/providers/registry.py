"""Build provider adapters from configuration."""

import os
from collections.abc import Callable

import httpx

from app.providers.base import CallRecorder, Provider
from app.providers.binance import BinanceProvider
from app.providers.coinbase import CoinbaseProvider
from app.providers.coingecko import CoinGeckoProvider
from app.providers.coinmetrics import CoinMetricsProvider
from app.providers.config import ProvidersConfig
from app.providers.defillama import DefiLlamaProvider
from app.providers.frankfurter import FrankfurterProvider
from app.providers.fred import FredProvider

ADAPTERS: dict[str, type[Provider]] = {
    "binance": BinanceProvider,
    "coinbase": CoinbaseProvider,
    "coingecko": CoinGeckoProvider,
    "defillama": DefiLlamaProvider,
    "coinmetrics": CoinMetricsProvider,
    "frankfurter": FrankfurterProvider,
    "fred": FredProvider,
}


class Providers:
    """Lazily created adapters sharing one recorder (and optionally one HTTP client, for tests)."""

    def __init__(
        self,
        config: ProvidersConfig,
        recorder: CallRecorder,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.config = config
        self.recorder = recorder
        self.client = client
        self.sleep = sleep
        self.env = os.environ if env is None else env
        self._cache: dict[str, Provider] = {}

    def get(self, name: str) -> Provider:
        if name not in self._cache:
            settings = self.config.settings_for(name)
            key = self.env.get(settings.api_key_env) if settings.api_key_env else None
            kwargs = {"api_key": key, "client": self.client}
            if self.sleep is not None:
                kwargs["sleep"] = self.sleep
            self._cache[name] = ADAPTERS[name](settings, self.recorder, **kwargs)
        return self._cache[name]

    @property
    def binance(self) -> BinanceProvider:
        return self.get("binance")  # type: ignore[return-value]

    @property
    def coinbase(self) -> CoinbaseProvider:
        return self.get("coinbase")  # type: ignore[return-value]

    @property
    def coingecko(self) -> CoinGeckoProvider:
        return self.get("coingecko")  # type: ignore[return-value]

    @property
    def defillama(self) -> DefiLlamaProvider:
        return self.get("defillama")  # type: ignore[return-value]

    @property
    def coinmetrics(self) -> CoinMetricsProvider:
        return self.get("coinmetrics")  # type: ignore[return-value]

    @property
    def frankfurter(self) -> FrankfurterProvider:
        return self.get("frankfurter")  # type: ignore[return-value]

    @property
    def fred(self) -> FredProvider:
        return self.get("fred")  # type: ignore[return-value]
