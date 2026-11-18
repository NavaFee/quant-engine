import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from quant_engine.data import ParquetStore, empty_bars
from quant_engine.data import store as store_module

START, END = 1704067200000, 1705867200000
HOUR = 3_600_000


def test_roundtrip_overlap_and_idempotence(tmp_path, bars):
    store = ParquetStore(tmp_path)
    store.write("binance", "BTCUSDT", "1h", bars.iloc[:300])
    update = bars.iloc[250:].copy()
    update["close"] += 1.0
    assert store.write("binance", "BTCUSDT", "1h", update).ok
    store.write("binance", "BTCUSDT", "1h", update)
    expected = bars.copy()
    expected.loc[250:, "close"] += 1.0
    assert_frame_equal(store.read("binance", "BTCUSDT", "1h", START, END), expected)
    assert (
        store.path("binance", "BTCUSDT", "1h")
        == tmp_path / "binance/BTCUSDT/1h/bars.parquet"
    )
    actual_file = pd.read_parquet(store.path("binance", "BTCUSDT", "1h"))
    assert_frame_equal(actual_file, expected)
    assert_frame_equal(
        store.read("binance", "BTCUSDT", "1h", START + HOUR, START + 3 * HOUR),
        expected.iloc[1:3].reset_index(drop=True),
    )


def test_write_reports_raw_anomalies(tmp_path, bars):
    store = ParquetStore(tmp_path)
    report = store.write("binance", "BTCUSDT", "1h", bars.iloc[[2, 0, 2]])
    assert report.duplicates == {START + 2 * HOUR: 2}
    assert report.out_of_order == (1,)
    assert report.gaps[0].missing_bars == 1
    assert_frame_equal(
        store.read("binance", "BTCUSDT", "1h", START, END),
        bars.iloc[[0, 2]].reset_index(drop=True),
    )


def test_partition_isolation_and_typed_empty(tmp_path, bars):
    store = ParquetStore(tmp_path)
    partitions = [
        ("binance", "BTCUSDT", "1h"),
        ("other", "BTCUSDT", "1h"),
        ("binance", "ETHUSDT", "1h"),
        ("binance", "BTCUSDT", "4h"),
    ]
    for i, key in enumerate(partitions):
        sample = bars.iloc[[0]].copy()
        sample["close"] += float(i)
        store.write(*key, sample)
    for i, key in enumerate(partitions):
        assert store.read(*key, START, END).close.iloc[0] == bars.close.iloc[0] + i
    assert_frame_equal(store.read("missing", "BTCUSDT", "1d", START, END), empty_bars())
    assert_frame_equal(store.read(*partitions[0], END, END + HOUR), empty_bars())


@pytest.mark.parametrize("phase", ["serialize", "replace"])
def test_atomic_failure_preserves_previous_file(tmp_path, bars, monkeypatch, phase):
    store = ParquetStore(tmp_path)
    key = ("binance", "BTCUSDT", "1h")
    store.write(*key, bars.iloc[:2])
    path = store.path(*key)
    before = path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("simulated disk failure")

    if phase == "serialize":
        monkeypatch.setattr(pd.DataFrame, "to_parquet", fail)
    else:
        monkeypatch.setattr(store_module.os, "replace", fail)
    with pytest.raises(OSError, match="disk failure"):
        store.write(*key, bars)
    assert path.read_bytes() == before
    assert list(path.parent.iterdir()) == [path]


def test_empty_write_and_invalid_input_leave_file_untouched(tmp_path, bars):
    store = ParquetStore(tmp_path)
    key = ("binance", "BTCUSDT", "1h")
    store.write(*key, empty_bars())
    assert not store.path(*key).exists()
    store.write(*key, bars)
    before = store.path(*key).read_bytes()
    store.write(*key, empty_bars())
    with pytest.raises(ValueError):
        store.write(*key, bars.astype({"ts": "float64"}))
    assert store.path(*key).read_bytes() == before


@pytest.mark.parametrize(
    "key",
    [
        ("../binance", "BTCUSDT", "1h"),
        ("binance", "../BTC", "1h"),
        ("binance", "BTCUSDT", "../1h"),
    ],
)
def test_partition_path_rejects_traversal(tmp_path, key):
    with pytest.raises(ValueError):
        ParquetStore(tmp_path).path(*key)
