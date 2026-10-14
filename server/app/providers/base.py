"""Shared plumbing for every data provider adapter.

Each adapter talks to one provider through `Provider.get_json`, which enforces the provider's rate
limit and monthly budget, retries transient failures, and records every call (with its raw response)
through a `CallRecorder`. Adapters return normalised `Bar` and `Fact` objects that carry the id of
the call that produced them.
"""

import gzip
import json
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Protocol

import httpx

log = logging.getLogger(__name__)

SECRET_PARAMS = {"api_key", "x_cg_demo_api_key", "token", "api_token"}
RETRY_STATUS = {429, 500, 502, 503, 504}


class ProviderError(Exception):
    """A provider call failed for good (after retries) or returned unusable data."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code

    @property
    def not_found(self) -> bool:
        """The provider answered but has no data for this item (an expected outcome when probing)."""
        return self.status_code in (400, 404)


class BudgetExceeded(ProviderError):
    """The provider's monthly budget is used up; no call was made."""


class NotSupported(ProviderError):
    """The adapter does not offer this kind of data."""


@dataclass(frozen=True)
class RateLimit:
    calls: int
    per_seconds: float


@dataclass(frozen=True)
class ProviderSettings:
    name: str
    base_url: str
    rate_limit: RateLimit
    monthly_budget: int | None = None
    raw_retention_days: int = 400
    api_key_env: str | None = None
    attribution: str | None = None


@dataclass(frozen=True)
class Bar:
    """A completed daily bar. `ts` is the UTC day the bar covers; `close` is the price at its end."""

    ts: date
    close: Decimal
    quote: str
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    volume: Decimal | None = None
    call_id: int | None = None


@dataclass(frozen=True)
class Fact:
    field: str
    as_of: date
    value: Decimal
    unit: str
    call_id: int | None = None
    # When the provider states when the value became public (an SEC filing date), it is stored as is.
    available_at: datetime | None = None


@dataclass
class Response:
    data: Any
    call_id: int | None
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)


class CallRecorder(Protocol):
    def record(
        self,
        *,
        provider: str,
        endpoint: str,
        params: dict[str, Any] | None,
        status_code: int | None,
        ok: bool,
        error: str | None,
        cost: int,
        body: bytes | None,
        content_type: str | None,
        duration_ms: int,
        started_at: datetime,
    ) -> int | None: ...

    def month_usage(self, provider: str) -> int: ...


class MemoryRecorder:
    """Recorder that keeps calls in memory; used in tests and dry runs."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> int:
        self.calls.append(kwargs)
        return len(self.calls)

    def month_usage(self, provider: str) -> int:
        month = datetime.now(UTC).strftime("%Y-%m")
        return sum(
            c["cost"] for c in self.calls
            if c["provider"] == provider and c["started_at"].strftime("%Y-%m") == month
        )


class RateLimiter:
    """Sliding-window limiter: at most `calls` calls in any `per_seconds` window."""

    def __init__(
        self,
        limit: RateLimit,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.limit = limit
        self.clock = clock
        self.sleep = sleep
        self._stamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            while True:
                now = self.clock()
                while self._stamps and now - self._stamps[0] >= self.limit.per_seconds:
                    self._stamps.popleft()
                if len(self._stamps) < self.limit.calls:
                    self._stamps.append(now)
                    return
                self.sleep(self.limit.per_seconds - (now - self._stamps[0]) + 0.01)


def to_decimal(value: Any) -> Decimal | None:
    """Convert a JSON number or numeric string to Decimal; empty, '.' and null become None."""
    if value is None or value == "" or value == ".":
        return None
    return Decimal(str(value))


def utc_now() -> datetime:
    return datetime.now(UTC)


class Provider:
    """Base class for adapters. Subclasses set `name` and implement what the provider offers."""

    name: str = "provider"
    max_attempts = 3

    def __init__(
        self,
        settings: ProviderSettings,
        recorder: CallRecorder,
        *,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        limiter: RateLimiter | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.recorder = recorder
        self.api_key = api_key or None
        self.client = client or httpx.Client(timeout=60, headers={"User-Agent": "Graadmeter/0.1 (private research)"})
        self.limiter = limiter or RateLimiter(settings.rate_limit, sleep=sleep)
        self._sleep = sleep

    # Uniform adapter interface (chapter 3, design rule 2). Adapters override what they support.
    def get_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        raise NotSupported(f"{self.name} has no price bars")

    def get_fundamentals(self, symbol: str, start: date | None = None) -> list[Fact]:
        raise NotSupported(f"{self.name} has no fundamentals")

    def get_meta(self) -> Any:
        raise NotSupported(f"{self.name} has no metadata listing")

    # Hooks for authentication.
    def auth_headers(self) -> dict[str, str]:
        return {}

    def auth_params(self) -> dict[str, str]:
        return {}

    def check_budget(self, cost: int) -> None:
        budget = self.settings.monthly_budget
        if budget is None:
            return
        used = self.recorder.month_usage(self.name)
        if used + cost > budget:
            raise BudgetExceeded(f"{self.name}: monthly budget {budget} reached ({used} used)")

    def get_json(self, path: str, params: dict[str, Any] | None = None, *, cost: int = 1) -> Response:
        return self._request("GET", path, params, cost=cost)

    def get_text(self, path: str, params: dict[str, Any] | None = None, *, cost: int = 1) -> Response:
        """Like get_json, for providers that answer in CSV or another text format."""
        return self._request("GET", path, params, cost=cost, text_body=True)

    def post_json(self, path: str, payload: Any, *, cost: int = 1) -> Response:
        return self._request("POST", path, None, cost=cost, payload=payload)

    def _request(self, method: str, path: str, params: dict[str, Any] | None, *, cost: int,
                 payload: Any = None, text_body: bool = False) -> Response:
        url = path if path.startswith("http") else f"{self.settings.base_url}{path}"
        logged_params = {k: v for k, v in (params or {}).items() if k not in SECRET_PARAMS} or None
        endpoint = path.split("?")[0] if not path.startswith("http") else httpx.URL(path).path
        last_error, last_status = "no attempt", None
        for attempt in range(1, self.max_attempts + 1):
            self.check_budget(cost)
            self.limiter.acquire()
            started = utc_now()
            t0 = time.monotonic()
            status: int | None = None
            body: bytes | None = None
            content_type: str | None = None
            error: str | None = None
            retry_after: float | None = None
            try:
                # An empty params dict would make httpx drop a query string already in the URL
                # (pagination links), so pass None when there is nothing to add.
                query = {**(params or {}), **self.auth_params()} or None
                if method == "POST":
                    res = self.client.post(url, params=query, json=payload, headers=self.auth_headers())
                else:
                    res = self.client.get(url, params=query, headers=self.auth_headers())
                status, body = res.status_code, res.content
                content_type = res.headers.get("content-type")
                if status in RETRY_STATUS:
                    error = f"HTTP {status}"
                    retry_after = _retry_after(res.headers.get("retry-after"))
                elif status >= 400:
                    error = f"HTTP {status}: {res.text[:300]}"
            except httpx.HTTPError as exc:
                error = f"{type(exc).__name__}: {exc}"
            duration_ms = int((time.monotonic() - t0) * 1000)
            call_id = self.recorder.record(
                provider=self.name, endpoint=endpoint, params=logged_params, status_code=status,
                ok=error is None, error=error, cost=cost, body=body, content_type=content_type,
                duration_ms=duration_ms, started_at=started,
            )
            if error is None:
                if text_body:
                    return Response(data=(body or b"").decode("utf-8", "replace"), call_id=call_id,
                                    status_code=status or 0, headers=dict(res.headers))
                try:
                    data = json.loads(body or b"null")
                except ValueError as exc:
                    raise ProviderError(f"{self.name} {endpoint}: invalid JSON") from exc
                return Response(data=data, call_id=call_id, status_code=status or 0, headers=dict(res.headers))
            last_error, last_status = error, status
            transient = status is None or status in RETRY_STATUS
            if not transient or attempt == self.max_attempts:
                break
            self._sleep(retry_after if retry_after is not None else 2 ** attempt)
        raise ProviderError(f"{self.name} {endpoint}: {last_error}", last_status)


def _retry_after(value: str | None) -> float | None:
    try:
        return min(float(value), 120.0) if value else None
    except ValueError:
        return None


def gzip_body(body: bytes) -> bytes:
    return gzip.compress(body, compresslevel=6)
