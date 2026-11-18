"""Replaceable data sources and Binance's public spot kline endpoint."""

import json
import time
from collections.abc import Callable
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

from .models import BAR_DTYPES, empty_bars, interval_ms, normalize_bars, validate_range
from .quality import QualityReport, check_quality


class DataSource(Protocol):
    """A source of closed bars with the six-column, sorted/unique contract."""

    exchange: str

    def fetch(
        self, symbol: str, interval: str, start_ms: int, end_ms: int
    ) -> pd.DataFrame:
        """Fetch closed bars by UTC opening time in [start_ms, end_ms)."""
        ...


class DownloadError(RuntimeError):
    """A public data request failed or returned malformed kline data."""


def _request_json(url: str, timeout: float) -> object:
    with urlopen(url, timeout=timeout) as response:
        return json.load(response)


class BinanceSource:
    """Fetch public spot klines; transport, clock and retry sleep are injectable."""

    exchange = "binance"
    endpoint = "https://data-api.binance.vision/api/v3/klines"
    symbols = ("BTCUSDT", "ETHUSDT")

    def __init__(
        self,
        *,
        request: Callable[[str, float], object] = _request_json,
        timeout: float = 10.0,
        retries: int = 2,
        now_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Use at most retries + 1 attempts per page with capped backoff."""
        if timeout <= 0 or retries < 0:
            raise ValueError("timeout must be positive and retries nonnegative")
        self.request, self.timeout, self.retries = request, timeout, retries
        self.now_ms, self.sleep = now_ms, sleep
        self.last_quality: QualityReport | None = None

    def _page(self, params: dict[str, str | int]) -> list:
        url = f"{self.endpoint}?{urlencode(params)}"
        for attempt in range(self.retries + 1):
            try:
                page = self.request(url, self.timeout)
            except (HTTPError, URLError, OSError) as exc:
                retryable = not isinstance(exc, HTTPError) or (
                    exc.code == 429 or 500 <= exc.code < 600
                )
                if not retryable or attempt == self.retries:
                    raise DownloadError(f"Binance request failed: {exc}") from exc
                self.sleep(min(2**attempt, 4))
                continue
            except (ValueError, UnicodeError) as exc:
                raise DownloadError("Binance returned invalid JSON") from exc
            if not isinstance(page, list) or len(page) > 1000:
                raise DownloadError(
                    "Binance response must be a list of at most 1000 klines"
                )
            return page
        raise AssertionError("Unreachable retry state")

    def fetch(
        self, symbol: str, interval: str, start_ms: int, end_ms: int
    ) -> pd.DataFrame:
        """Fetch all pages before returning; preserve raw anomalies in last_quality."""
        self.last_quality = None
        validate_range(start_ms, end_ms)
        step = interval_ms(interval)
        if symbol not in self.symbols:
            raise ValueError(f"Unsupported symbol: {symbol}; use BTCUSDT or ETHUSDT")
        closed_end = min(end_ms, self.now_ms() // step * step)
        cursor, records = start_ms, []
        while cursor < closed_end:
            page = self._page(
                {
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end_ms - 1,
                    "limit": 1000,
                }
            )
            if not page:
                break
            openings = []
            for row in page:
                if (
                    not isinstance(row, list)
                    or len(row) != 12
                    or type(row[0]) is not int
                    or type(row[6]) is not int
                    or row[0] < 0
                    or row[0] >= 2**63
                    or row[0] % step
                    or row[6] != row[0] + step - 1
                ):
                    raise DownloadError("Invalid Binance kline shape or timestamps")
                openings.append(row[0])
                try:
                    values = [float(value) for value in row[1:6]]
                except (TypeError, ValueError, OverflowError) as exc:
                    raise DownloadError("Invalid Binance OHLCV values") from exc
                if start_ms <= row[0] < closed_end:
                    records.append([row[0], *values])
            next_cursor = max(openings) + step
            if next_cursor <= cursor:
                raise DownloadError("Binance pagination cursor did not advance")
            cursor = next_cursor
            if len(page) < 1000:
                break
        try:
            bars = pd.DataFrame(records, columns=list(BAR_DTYPES)).astype(BAR_DTYPES)
            self.last_quality = (
                check_quality(bars, interval, start_ms, closed_end)
                if start_ms < closed_end
                else check_quality(empty_bars(), interval)
            )
            return normalize_bars(bars)
        except (ValueError, TypeError, OverflowError) as exc:
            raise DownloadError(f"Invalid Binance bars: {exc}") from exc
