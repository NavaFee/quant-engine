import io
import json
import runpy
import sys

import pytest
from pandas.testing import assert_frame_equal

from quant_engine.data import BinanceSource, ParquetStore
from quant_engine.data import sources as source_module
from quant_engine.data.__main__ import main, parse_utc

START, HOUR = 1704067200000, 3_600_000


def arguments(root, start="2024-01-01", end="2024-02-01"):
    return [
        "download",
        "--symbol",
        "BTCUSDT",
        "--interval",
        "1h",
        "--start",
        start,
        "--end",
        end,
        "--root",
        str(root),
    ]


def test_module_download_to_parquet_offline(tmp_path, rows, bars, monkeypatch, capsys):
    monkeypatch.delitem(sys.modules, "quant_engine.data.__main__", raising=False)
    monkeypatch.setattr(
        source_module, "urlopen", lambda *a, **kw: io.BytesIO(json.dumps(rows).encode())
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["quant_engine.data", *arguments(tmp_path, end="2024-01-21T20:00:00Z")],
    )
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("quant_engine.data", run_name="__main__")
    assert exit_info.value.code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["saved"] == 500
    assert result["quality"] == {"gaps": [], "duplicates": {}, "out_of_order": []}
    store = ParquetStore(tmp_path)
    assert result["path"] == str(store.path("binance", "BTCUSDT", "1h"))
    assert_frame_equal(
        store.read("binance", "BTCUSDT", "1h", START, START + 500 * HOUR), bars
    )


@pytest.mark.parametrize("phase", ["download", "empty"])
def test_failed_later_page_or_empty_download_preserves_file(
    tmp_path, bars, klines, capsys, phase
):
    store = ParquetStore(tmp_path)
    key = ("binance", "BTCUSDT", "1h")
    store.write(*key, bars.iloc[:2])
    path = store.path(*key)
    before = path.read_bytes()
    pages = iter(
        [klines(1000), TimeoutError("later page")] if phase == "download" else [[]]
    )

    def request(*args):
        page = next(pages)
        if isinstance(page, Exception):
            raise page
        return page

    adapter = BinanceSource(
        request=request, retries=0, now_ms=lambda: START + 2000 * HOUR
    )
    code = main(arguments(tmp_path, end="2024-03-01"), source=adapter)
    output = capsys.readouterr()
    if phase == "download":
        assert code == 1
        assert "later page" in output.err
        assert not output.out
    else:
        assert code == 0
        assert json.loads(output.out)["saved"] == 0
    assert path.read_bytes() == before
    assert list(path.parent.iterdir()) == [path]


def test_cli_retains_quality_before_sorting(tmp_path, rows, capsys):
    adapter = BinanceSource(request=lambda *args: [rows[2], rows[0], rows[2]])
    assert main(arguments(tmp_path, end="2024-01-01T04:00:00"), source=adapter) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["saved"] == 2
    assert result["quality"]["duplicates"] == {str(START + 2 * HOUR): 2}
    assert result["quality"]["out_of_order"] == [1]


@pytest.mark.parametrize(
    "start,end",
    [
        ("bad", "2024-02-01"),
        ("2024-02-01", "2024-01-01"),
        ("1969-01-01", "2024-01-01"),
        ("2024-01-01", "2024-01-01"),
    ],
)
def test_invalid_cli_range_returns_nonzero(tmp_path, start, end, capsys):
    try:
        code = main(arguments(tmp_path, start, end))
    except SystemExit as exc:
        code = exc.code
    assert code != 0
    assert capsys.readouterr().err
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "value", ["2024-01-01", "2024-01-01T00:00:00Z", "2024-01-01T08:00:00+08:00"]
)
def test_dates_mean_utc(value):
    assert parse_utc(value) == START
