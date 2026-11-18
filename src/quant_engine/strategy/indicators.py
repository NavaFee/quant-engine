"""Causal indicators with explicit mean seeds and NaN warmup."""

from numbers import Integral

import pandas as pd
from pandas.api.types import is_float_dtype, is_integer_dtype

from .base import _validate_bars


def _validate_period(period: int) -> None:
    if isinstance(period, bool) or not isinstance(period, Integral) or period <= 0:
        raise ValueError("period must be a positive integer (excluding bool)")


def _close(close: pd.Series, period: int) -> pd.Series:
    _validate_period(period)
    if (
        not isinstance(close, pd.Series)
        or not (is_float_dtype(close.dtype) or is_integer_dtype(close.dtype))
        or close.isna().any()
        or close.isin([float("inf"), -float("inf")]).any()
    ):
        raise ValueError("close must be a finite numeric Series")
    return close.astype("float64")


def _smooth(values: pd.Series, period: int, alpha: float) -> pd.Series:
    result = [float("nan")] * len(values)
    if len(values) >= period:
        previous = values.iloc[:period].mean()
        result[period - 1] = previous
        for i, value in enumerate(values.iloc[period:], start=period):
            previous = alpha * value + (1 - alpha) * previous
            result[i] = previous
    return pd.Series(result, index=values.index, name=values.name, dtype="float64")


def sma(close: pd.Series, period: int) -> pd.Series:
    """Mean of the last period rows; the first period - 1 values are NaN."""
    return _close(close, period).rolling(period, min_periods=period).mean()


def ema(close: pd.Series, period: int) -> pd.Series:
    """Seed with period closes' mean, then smooth with alpha = 2 / (period + 1)."""
    return _smooth(_close(close, period), period, 2 / (period + 1))


def rsi(close: pd.Series, period: int) -> pd.Series:
    """Wilder RSI; warm up period rows; all-flat movement yields 50."""
    close = _close(close, period)
    if close.empty:
        return close
    delta = close.diff().iloc[1:]
    gain = _smooth(delta.clip(lower=0), period, 1 / period)
    loss = _smooth(-delta.clip(upper=0), period, 1 / period)
    total = gain + loss
    result = close * float("nan")
    result.iloc[1:] = (100 * (gain / total)).where(total != 0, 50).to_numpy()
    return result


def atr(bars: pd.DataFrame, period: int) -> pd.Series:
    """Wilder-smoothed true range; first TR is high - low, with a mean seed."""
    _validate_period(period)
    _validate_bars(bars)
    previous = bars.close.shift(1)
    ranges = pd.concat(
        [
            bars.high - bars.low,
            (bars.high - previous).abs(),
            (bars.low - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return _smooth(ranges, period, 1 / period)
