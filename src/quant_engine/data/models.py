"""The six-column UTC millisecond bars contract."""

from numbers import Integral

import pandas as pd

BAR_DTYPES = {
    "ts": "int64",
    "open": "float64",
    "high": "float64",
    "low": "float64",
    "close": "float64",
    "volume": "float64",
}
INTERVAL_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def empty_bars() -> pd.DataFrame:
    """Return an empty table with the contract's column order and dtypes."""
    return pd.DataFrame(
        {name: pd.Series(dtype=dtype) for name, dtype in BAR_DTYPES.items()}
    )


def interval_ms(interval: str) -> int:
    """Return the duration of a supported, UTC-aligned interval."""
    if interval not in INTERVAL_MS:
        raise ValueError(f"Unsupported interval: {interval}; use 1h, 4h or 1d")
    return INTERVAL_MS[interval]


def validate_timestamp(value: int) -> None:
    """Require a nonnegative UTC millisecond integer representable as int64."""
    if (
        isinstance(value, bool)
        or not isinstance(value, Integral)
        or not 0 <= value < 2**63
    ):
        raise ValueError("Timestamps must be nonnegative int64 UTC milliseconds")


def validate_range(start_ms: int, end_ms: int) -> None:
    """Require a nonempty half-open time range."""
    validate_timestamp(start_ms)
    validate_timestamp(end_ms)
    if start_ms >= end_ms:
        raise ValueError("start must be earlier than end")


def validate_bars(bars: pd.DataFrame) -> None:
    """Validate columns, types and finite values without sorting or deduplicating."""
    if list(bars.columns) != list(BAR_DTYPES):
        raise ValueError(f"Expected columns in order: {', '.join(BAR_DTYPES)}")
    if any(str(bars[name].dtype) != dtype for name, dtype in BAR_DTYPES.items()):
        raise ValueError(f"Expected dtypes: {BAR_DTYPES}")
    if bars.isna().any().any() or bars.isin([float("inf"), -float("inf")]).any().any():
        raise ValueError("Bars must contain finite, non-null values")
    if (bars.ts < 0).any():
        raise ValueError("Bar timestamps must be nonnegative")


def normalize_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Return sorted, unique bars; the last occurrence of each timestamp wins."""
    validate_bars(bars)
    return (
        bars.drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True)
    )
