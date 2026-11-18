from dataclasses import FrozenInstanceError, asdict

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

from quant_engine.strategy import (
    MovingAverageParams,
    MovingAverageStrategy,
    Strategy,
    atr,
    ema,
    rsi,
    sma,
)

INDICATORS = [sma, ema, rsi, atr]


def indicator(function, bars, period):
    return function(bars if function is atr else bars.close, period)


class StubStrategy(Strategy):
    def __init__(self, output):
        self.output = output

    def _generate(self, bars):
        return self.output(bars)


@pytest.mark.parametrize(
    "function,expected",
    [
        (sma, [42556.63, 42508.38333333333, 42437.19333333333]),
        (ema, [42556.63, 42443.56, 42421.775]),
        (rsi, [32.82629330802088, 46.14857795110815, 26.98016360714266]),
        (atr, [258.43666666666667, 291.14444444444445, 257.6062962962963]),
    ],
)
def test_hand_calculated_prefix(bars, function, expected):
    # n=3: closes 42475.23, 42613.56, 42581.10, 42330.49, 42399.99, 42234.01.
    # RSI seed: gain=138.33/3, loss=(32.46+250.61)/3; next +69.50, -165.98.
    # TRs: 293.55, 343.35, 138.41, 356.56, 190.53; seed=775.31/3.
    result = indicator(function, bars.iloc[:6], 3)
    warmup = 3 if function is rsi else 2
    assert result.iloc[:warmup].isna().all()
    assert result.iloc[warmup : warmup + 3].tolist() == pytest.approx(
        expected, rel=1e-12, abs=1e-9
    )


@pytest.mark.parametrize("function", INDICATORS)
@pytest.mark.parametrize("period", [1, 3, 501])
def test_indicator_contract(bars, function, period):
    original = bars.copy(deep=True)
    for length in [0, 1, 2, 3, 4, len(bars)]:
        sample = bars.iloc[:length]
        result = indicator(function, sample, period)
        assert result.dtype == "float64" and result.index.equals(sample.index)
        warmup = period if function is rsi else period - 1
        assert result.iloc[:warmup].isna().all()
        assert result.iloc[warmup:].notna().all()
    assert_frame_equal(bars, original)


@pytest.mark.parametrize("function", INDICATORS)
@pytest.mark.parametrize("period", [0, -1, True, 2.5, "3", None])
def test_invalid_period(bars, function, period):
    with pytest.raises(ValueError, match="positive integer"):
        indicator(function, bars, period)


@pytest.mark.parametrize("direction,expected", [(1, 100), (-1, 0), (0, 50)])
def test_rsi_zero_denominators(bars, direction, expected):
    close = bars.close.iloc[:8].copy()
    close[:] = close.iloc[0] + direction * pd.RangeIndex(len(close))
    assert rsi(close, 3).iloc[3:].tolist() == [expected] * 5


def test_atr_includes_price_gaps(bars):
    sample = bars.iloc[:3].copy()
    sample.iloc[1, 1:5] += 1000.0
    # Upward gap then downward gap: high-prev_close, abs(low-prev_close).
    assert atr(sample, 1).tolist() == pytest.approx([293.55, 1299.77, 1113.56])


def test_moving_average_targets(bars):
    strategy = MovingAverageStrategy(MovingAverageParams(fast=2, slow=3))
    original = bars.copy(deep=True)
    assert strategy.generate(bars.iloc[:6]).tolist() == [0, 0, 1, 0, 0, 0]
    flat = bars.copy()
    flat.loc[:, ["open", "high", "low", "close"]] = bars.close.iloc[0]
    assert strategy.generate(flat).eq(0).all()  # Equality must not enter.
    assert strategy.generate(bars.iloc[:2]).eq(0).all()
    assert_frame_equal(bars, original)


@pytest.mark.parametrize("function", [*INDICATORS, None])
def test_every_prefix_is_causal_and_repeatable(bars, function):
    strategy = MovingAverageStrategy(MovingAverageParams(fast=2, slow=5))

    def compute(sample):
        return (
            strategy.generate(sample)
            if function is None
            else indicator(function, sample, 5)
        )

    full = compute(bars)
    for length in range(len(bars) + 1):
        assert_series_equal(
            compute(bars.iloc[:length]),
            full.iloc[:length],
            check_exact=True,
            check_names=False,
        )
    assert_series_equal(compute(bars), full, check_exact=True)
    if function is None:
        assert full.dtype == "float64" and full.between(0, 1).all()
        assert full.iloc[:8].tolist() == [0, 0, 0, 0, 0, 0, 0, 1]


@pytest.mark.parametrize("function", [*INDICATORS, None])
def test_time_gaps_use_observed_rows(bars, function):
    sample = bars.iloc[:8].copy()
    sample.iloc[4:, 0] += 3_600_000 * 10
    strategy = MovingAverageStrategy(MovingAverageParams(2, 3))
    expected = (
        strategy.generate(bars.iloc[:8])
        if function is None
        else indicator(function, bars.iloc[:8], 3)
    )
    actual = (
        strategy.generate(sample)
        if function is None
        else indicator(function, sample, 3)
    )
    assert_series_equal(actual, expected, check_exact=True)


@pytest.mark.parametrize(
    "fast,slow",
    [(0, 3), (2, -1), (True, 3), (1, False), (1.5, 3), (1, "3"), (3, 3), (4, 3)],
)
def test_invalid_strategy_parameters(fast, slow):
    with pytest.raises(ValueError):
        MovingAverageParams(fast, slow)


def test_parameters_are_required_and_frozen():
    with pytest.raises(TypeError):
        MovingAverageParams()
    params = MovingAverageParams(2, 3)
    assert asdict(params) == {"fast": 2, "slow": 3}
    with pytest.raises(FrozenInstanceError):
        params.fast = 1
    with pytest.raises(TypeError):
        Strategy()


@pytest.mark.parametrize(
    "transform",
    [
        lambda b: None,
        lambda b: b.drop(columns="close"),
        lambda b: b.astype({"ts": "float64"}),
        lambda b: b.assign(close=float("nan")),
        lambda b: b.assign(close=float("inf")),
        lambda b: b.assign(ts=-1),
        lambda b: b.iloc[::-1],
        lambda b: pd.concat([b, b.iloc[-1:]]),
    ],
)
@pytest.mark.parametrize("function", [atr, None])
def test_invalid_bars(bars, transform, function):
    strategy = MovingAverageStrategy(MovingAverageParams(2, 3))
    with pytest.raises(ValueError):
        if function is None:
            strategy.generate(transform(bars))
        else:
            atr(transform(bars), 3)


@pytest.mark.parametrize(
    "output",
    [
        lambda b: [0.0] * len(b),
        lambda b: pd.Series(0, index=b.index),
        lambda b: pd.Series(0.0, index=b.index, dtype="float32"),
        lambda b: pd.Series(0.0, index=b.index[::-1]),
        lambda b: pd.Series(0.0, index=b.index[:-1]),
        *[
            lambda b, value=v: pd.Series(value, index=b.index)
            for v in [float("nan"), float("inf"), -float("inf"), -0.1, 1.1]
        ],
    ],
)
def test_invalid_targets(bars, output):
    with pytest.raises(ValueError, match="Targets"):
        StubStrategy(output).generate(bars)


def test_generate_protects_input_and_accepts_fractional_targets(bars):
    def mutate(copy):
        copy.loc[:, "close"] = 0.5
        return copy.close

    original = bars.copy(deep=True)
    assert StubStrategy(mutate).generate(bars).eq(0.5).all()
    assert_frame_equal(bars, original)
