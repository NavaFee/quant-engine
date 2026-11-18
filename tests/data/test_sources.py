import io
import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest
from pandas.testing import assert_frame_equal

from quant_engine.data import BinanceSource, DownloadError, empty_bars
from quant_engine.data import sources as source_module

START, HOUR = 1704067200000, 3_600_000


class Transport:
    def __init__(self, *pages):
        self.pages, self.calls = iter(pages), []

    def __call__(self, url, timeout):
        self.calls.append((urlsplit(url), parse_qs(urlsplit(url).query), timeout))
        page = next(self.pages)
        if isinstance(page, Exception):
            raise page
        return page


def source(transport, **kwargs):
    return BinanceSource(
        request=transport, now_ms=lambda: START + 3000 * 24 * HOUR, **kwargs
    )


@pytest.mark.parametrize("count", [1000, 1001, 2501])
@pytest.mark.parametrize("symbol", ["BTCUSDT", "ETHUSDT"])
@pytest.mark.parametrize(
    "interval,step", [("1h", HOUR), ("4h", 4 * HOUR), ("1d", 24 * HOUR)]
)
def test_pagination_and_public_parameters(klines, count, symbol, interval, step):
    rows = klines(count, step)
    transport = Transport(*(rows[i : i + 1000] for i in range(0, count, 1000)))
    adapter = source(transport, timeout=7)
    bars = adapter.fetch(symbol, interval, START, START + count * step)
    assert bars.ts.tolist() == [START + i * step for i in range(count)]
    assert adapter.last_quality.ok
    assert len(transport.calls) == (count + 999) // 1000
    for i, (url, params, timeout) in enumerate(transport.calls):
        assert url.scheme == "https"
        assert url.hostname == "data-api.binance.vision"
        assert url.path == "/api/v3/klines"
        assert timeout == 7
        assert params == {
            "symbol": [symbol],
            "interval": [interval],
            "limit": ["1000"],
            "startTime": [str(START + i * 1000 * step)],
            "endTime": [str(START + count * step - 1)],
        }


def test_exclusive_bounds_and_unclosed_filter(rows):
    transport = Transport(rows[:5])
    adapter = BinanceSource(request=transport, now_ms=lambda: START + 3 * HOUR + 1)
    bars = adapter.fetch("BTCUSDT", "1h", START + 1, START + 4 * HOUR)
    assert bars.ts.tolist() == [START + HOUR, START + 2 * HOUR]
    assert adapter.last_quality.ok
    adapter = source(Transport(rows[:5]))
    assert adapter.fetch("BTCUSDT", "1h", START, START + 2 * HOUR).ts.tolist() == [
        START,
        START + HOUR,
    ]


def test_close_instant_and_future_range(rows):
    adapter = BinanceSource(request=Transport(rows[:2]), now_ms=lambda: START + HOUR)
    assert len(adapter.fetch("BTCUSDT", "1h", START, START + 2 * HOUR)) == 1
    adapter = BinanceSource(request=Transport(), now_ms=lambda: START + HOUR - 1)
    assert_frame_equal(
        adapter.fetch("BTCUSDT", "1h", START, START + HOUR), empty_bars()
    )
    assert adapter.last_quality.ok


def test_raw_quality_survives_normalization(rows):
    adapter = source(Transport([rows[2], rows[0], rows[2]]))
    bars = adapter.fetch("BTCUSDT", "1h", START, START + 4 * HOUR)
    assert bars.ts.tolist() == [START, START + 2 * HOUR]
    assert adapter.last_quality.duplicates == {START + 2 * HOUR: 2}
    assert adapter.last_quality.out_of_order == (1,)
    assert sum(gap.missing_bars for gap in adapter.last_quality.gaps) == 2


def test_empty_page_and_stale_cursor(klines):
    adapter = source(Transport([]))
    assert_frame_equal(
        adapter.fetch("BTCUSDT", "1h", START, START + HOUR), empty_bars()
    )
    assert adapter.last_quality.gaps[0].missing_bars == 1
    rows = klines(1000)
    adapter = source(Transport(rows, []))
    assert len(adapter.fetch("BTCUSDT", "1h", START, START + 1001 * HOUR)) == 1000
    assert adapter.last_quality.gaps[0].missing_bars == 1
    adapter = source(Transport(rows, rows))
    with pytest.raises(DownloadError, match="did not advance"):
        adapter.fetch("BTCUSDT", "1h", START, START + 1001 * HOUR)
    assert adapter.last_quality is None


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("timeout"),
        URLError("connection failed"),
        HTTPError("url", 429, "limited", {}, None),
        HTTPError("url", 503, "unavailable", {}, None),
    ],
)
def test_transient_retries_and_exhaustion(rows, error):
    waits = []
    transport = Transport(error, error, rows[:1])
    adapter = source(transport, sleep=waits.append)
    assert len(adapter.fetch("BTCUSDT", "1h", START, START + HOUR)) == 1
    assert waits == [1, 2]
    transport = Transport(error, error, error)
    adapter = source(transport, sleep=lambda _: None)
    with pytest.raises(DownloadError, match="request failed"):
        adapter.fetch("BTCUSDT", "1h", START, START + HOUR)
    assert len(transport.calls) == 3
    assert adapter.last_quality is None


@pytest.mark.parametrize(
    "response",
    [
        {"code": -1121},
        None,
        [None],
        [[0]],
        HTTPError("url", 400, "bad request", {}, None),
        json.JSONDecodeError("bad", "?", 0),
    ],
)
def test_invalid_response_fails_without_retry(response):
    transport = Transport(response)
    with pytest.raises(DownloadError):
        source(transport).fetch("BTCUSDT", "1h", START, START + HOUR)
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "column,value",
    [
        (0, 1704067200000.5),
        (0, True),
        (0, 1704067200001),
        (6, 0),
        (1, "bad"),
        (1, "NaN"),
        (1, "Infinity"),
    ],
)
def test_invalid_kline_values(rows, column, value):
    row = rows[0].copy()
    row[column] = value
    with pytest.raises(DownloadError):
        source(Transport([row])).fetch("BTCUSDT", "1h", START, START + HOUR)


@pytest.mark.parametrize(
    "args",
    [
        ("BAD", "1h", START, START + HOUR),
        ("BTCUSDT", "1m", START, START + HOUR),
        ("BTCUSDT", "1h", START, START),
    ],
)
def test_bad_arguments_never_request(args):
    transport = Transport()
    with pytest.raises(ValueError):
        source(transport).fetch(*args)
    assert not transport.calls


def test_default_http_transport_decodes_json_offline(rows, monkeypatch):
    calls = []

    def open_fake(url, timeout):
        calls.append((url, timeout))
        return io.BytesIO(json.dumps(rows[:1]).encode())

    monkeypatch.setattr(source_module, "urlopen", open_fake)
    adapter = BinanceSource(now_ms=lambda: START + HOUR)
    assert len(adapter.fetch("BTCUSDT", "1h", START, START + HOUR)) == 1
    assert calls[0][1] == 10.0
