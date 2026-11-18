import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from quant_engine.data import (
    BAR_DTYPES,
    Gap,
    check_quality,
    empty_bars,
    normalize_bars,
    validate_bars,
)

HOUR = 3_600_000


def test_historical_fixture_contract(bars):
    validate_bars(bars)
    assert len(bars) == 500
    assert bars.dtypes.astype(str).to_dict() == BAR_DTYPES
    assert bars.ts.iloc[0] == 1704067200000
    assert bars.ts.iloc[-1] == 1705863600000
    assert check_quality(bars, "1h", 1704067200000, 1705867200000).ok


@pytest.mark.parametrize(
    "case", ["column", "extra", "order", "dtype", "nan", "inf", "negative"]
)
def test_invalid_schema_or_values_rejected(bars, case):
    if case == "column":
        bars = bars.drop(columns="volume")
    elif case == "extra":
        bars["extra"] = 1
    elif case == "order":
        bars = bars[list(reversed(bars.columns))]
    elif case == "dtype":
        bars = bars.astype({"ts": "float64"})
    elif case == "negative":
        bars.loc[0, "ts"] = -1
    else:
        bars.loc[0, "open"] = float(case)
    with pytest.raises(ValueError):
        validate_bars(bars)


@pytest.mark.parametrize(
    "indices,missing,duplicates,positions",
    [
        ([0, 1, 2, 3], 0, {}, ()),
        ([0, 3], 2, {}, ()),
        ([0, 1, 1, 2], 0, {1: 2}, ()),
        ([0, 2, 1], 0, {}, (2,)),
        ([3, 0, 3], 2, {3: 2}, (1,)),
    ],
)
def test_raw_quality(bars, indices, missing, duplicates, positions):
    sample = bars.iloc[indices].copy()
    before = sample.copy()
    start = int(bars.ts.iloc[0])
    report = check_quality(sample, "1h")
    assert sum(gap.missing_bars for gap in report.gaps) == missing
    assert report.duplicates == {start + i * HOUR: n for i, n in duplicates.items()}
    assert report.out_of_order == positions
    assert report.ok == (not missing and not duplicates and not positions)
    assert_frame_equal(sample, before)


@pytest.mark.parametrize(
    "interval,step", [("1h", HOUR), ("4h", 4 * HOUR), ("1d", 24 * HOUR)]
)
def test_gap_ranges_and_edges(bars, interval, step):
    sample = bars.iloc[:2].copy()
    start = int(sample.ts.iloc[0])
    sample["ts"] = pd.Series([start + step, start + 4 * step], dtype="int64")
    report = check_quality(sample, interval, start, start + 6 * step)
    assert report.gaps == (
        Gap(start, start + step, 1),
        Gap(start + 2 * step, start + 4 * step, 2),
        Gap(start + 5 * step, start + 6 * step, 1),
    )


def test_empty_and_unaligned_range_edges(bars):
    assert check_quality(empty_bars(), "1h").ok
    assert check_quality(empty_bars(), "1h", 1, 3 * HOUR).gaps == (
        Gap(HOUR, 3 * HOUR, 2),
    )
    start = int(bars.ts.iloc[0])
    assert check_quality(bars.iloc[:3], "1h", start + 1, start + 2 * HOUR + 1).ok
    assert check_quality(bars.iloc[1:3], "1h", start_ms=start).gaps == (
        Gap(start, start + HOUR, 1),
    )
    assert check_quality(bars.iloc[:2], "1h", end_ms=start + 3 * HOUR).gaps == (
        Gap(start + 2 * HOUR, start + 3 * HOUR, 1),
    )


@pytest.mark.parametrize(
    "start,end", [(2, 1), (1, 1), (-1, 1), (0.5, 1), (True, 2), (0, 2**63)]
)
def test_bad_quality_range(start, end):
    with pytest.raises(ValueError):
        check_quality(empty_bars(), "1h", start, end)


def test_bad_interval_or_open_time(bars):
    with pytest.raises(ValueError, match="interval"):
        check_quality(bars, "1m")
    bars.loc[0, "ts"] += 1
    with pytest.raises(ValueError, match="UTC grid"):
        check_quality(bars, "1h")


def test_normalization_uses_last_value_without_mutation(bars):
    changed = bars.iloc[[0]].copy()
    changed["close"] += 1.0
    raw = pd.concat([bars.iloc[:3][::-1], changed], ignore_index=True)
    before = raw.copy()
    expected = bars.iloc[:3].copy()
    expected.loc[0, "close"] += 1.0
    assert_frame_equal(normalize_bars(raw), expected)
    assert_frame_equal(raw, before)
    assert_frame_equal(normalize_bars(empty_bars()), empty_bars())
