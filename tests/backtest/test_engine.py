from dataclasses import FrozenInstanceError

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

from quant_engine.backtest import BacktestConfig, run_backtest


def targets(bars, values):
    return pd.Series(values, index=bars.index, dtype="float64")


def test_hand_calculated_four_bars(bars):
    bars = bars.iloc[:4]
    result = run_backtest(
        bars, targets(bars, [0.5, 1, 0, 1]), BacktestConfig(1000, 10, 20)
    )
    # Independently evaluated with 50-digit Decimal arithmetic; no relative tolerance.
    assert result.equity.equity.tolist() == pytest.approx(
        [1000, 1000.127169929637, 997.872100609359, 994.880246408054], rel=0, abs=1e-10
    )
    assert result.positions.cash.tolist() == pytest.approx(
        [1000, 499.250624812157, 0, 994.880246408054], rel=0, abs=1e-10
    )
    assert result.positions.qty.tolist() == pytest.approx(
        [0, 0.011753923988455317, 0.02343462476566737, 0], rel=0, abs=1e-16
    )
    assert result.trades.ts.tolist() == bars.ts.iloc[1:].tolist()
    assert result.trades.side.tolist() == ["buy", "buy", "sell"]
    assert result.trades.price.tolist() == pytest.approx(
        [42560.18046, 42698.79714, 42495.92782], rel=0, abs=1e-10
    )
    assert result.trades.qty.tolist() == pytest.approx(
        [0.011753923988455317, 0.011680700777212052, 0.02343462476566737],
        rel=0,
        abs=1e-16,
    )
    assert result.trades.fee.tolist() == pytest.approx(
        [0.5002491260617813, 0.4987518729392177, 0.995876122530585], rel=0, abs=1e-12
    )
    assert result.equity.drawdown.tolist() == pytest.approx(
        [0, 0, -0.0022547825797361014, -0.005246256355530987], rel=0, abs=1e-12
    )


@pytest.mark.parametrize(
    "fee,slippage", [(0, 0), (10, 0), (0, 20), (10, 20), (9999, 9999)]
)
def test_costs_conservation_and_fractional_rebalancing(bars, fee, slippage):
    bars = bars.iloc[:10]
    weights = targets(bars, [0.5, 0.5, 0.25, 1, 1, 0, 1e-12, 1 - 1e-12, 0, 1])
    result = run_backtest(bars, weights, BacktestConfig(1000, fee, slippage))
    cash, qty, peak = 1000.0, 0.0, 1000.0
    for i, row in enumerate(bars.itertuples()):
        for trade in result.trades[result.trades.ts == row.ts].itertuples():
            direction = 1 if trade.side == "buy" else -1
            assert trade.price == row.open * (1 + direction * slippage / 10000)
            assert trade.fee == pytest.approx(trade.price * trade.qty * fee / 10000)
            assert trade.qty > 0
            cash -= direction * trade.price * trade.qty + trade.fee
            qty += direction * trade.qty
        position = result.positions.iloc[i]
        assert position.cash == pytest.approx(cash, rel=0, abs=1e-10)
        assert position.qty == pytest.approx(qty, rel=0, abs=1e-16)
        assert position.cash >= 0 and position.qty >= 0
        if i:
            proportion = (
                position.qty * row.open / (position.cash + position.qty * row.open)
            )
            assert proportion == pytest.approx(weights.iloc[i - 1], rel=0, abs=1e-12)
        equity = cash + qty * row.close
        peak = max(peak, equity)
        assert result.equity.equity.iloc[i] == pytest.approx(equity, rel=0, abs=1e-10)
        assert result.equity.drawdown.iloc[i] == pytest.approx(
            equity / peak - 1, rel=0, abs=1e-12
        )
    assert bars.ts.iloc[2] in result.trades.ts.values  # Unchanged 0.5 target drifts.


@pytest.mark.parametrize("weight", [0.0, 1.0])
@pytest.mark.parametrize("fee,slippage", [(0, 0), (10, 20)])
def test_zero_targets_and_buy_hold(bars, weight, fee, slippage):
    result = run_backtest(
        bars, targets(bars, weight), BacktestConfig(1000, fee, slippage)
    )
    if weight == 0:
        assert result.trades.empty
        assert (
            result.equity.equity.eq(1000).all() and result.equity.drawdown.eq(0).all()
        )
    else:
        assert result.trades.ts.tolist() == [bars.ts.iloc[1]]
        quantity = 1000 / (
            bars.open.iloc[1] * (1 + slippage / 10000) * (1 + fee / 10000)
        )
        assert result.positions.qty.iloc[1:].tolist() == pytest.approx(
            [quantity] * (len(bars) - 1)
        )
        assert result.positions.cash.iloc[1:].eq(0).all()
        assert result.equity.equity.iloc[1:].tolist() == pytest.approx(
            (quantity * bars.close.iloc[1:]).tolist(), rel=0, abs=1e-10
        )
        expected = (
            result.equity.equity / result.equity.equity.cummax().clip(lower=1000) - 1
        )
        assert_series_equal(result.equity.drawdown, expected, check_names=False)


@pytest.mark.parametrize("length", [0, 1])
def test_empty_single_and_output_schema(bars, length):
    bars = bars.iloc[:length]
    result = run_backtest(bars, targets(bars, 1), BacktestConfig(1000))
    for frame, columns in [
        (result.equity, ["ts", "equity", "drawdown"]),
        (result.positions, ["ts", "cash", "qty"]),
        (result.trades, ["ts", "side", "price", "qty", "fee"]),
    ]:
        assert list(frame.columns) == columns
        assert [str(dtype) for dtype in frame.dtypes] == [
            "int64" if c == "ts" else "object" if c == "side" else "float64"
            for c in columns
        ]
    assert result.equity.index.equals(bars.index) and result.positions.index.equals(
        bars.index
    )
    assert result.trades.empty and isinstance(result.trades.index, pd.RangeIndex)
    assert result.equity.ts.tolist() == bars.ts.tolist()
    assert result.positions.ts.tolist() == bars.ts.tolist()
    assert result.equity.equity.tolist() == [1000] * length


def test_causality_gaps_repeatability_and_input_preservation(bars):
    bars = bars.iloc[:10].copy()
    bars.loc[bars.index[3] :, "ts"] += 10 * 3_600_000
    weights = targets(bars, [0.5, 1, 0, 0.25, 0.25, 1, 0, 0.5, 1, 0])
    original_bars, original_targets = bars.copy(deep=True), weights.copy(deep=True)
    config = BacktestConfig(1000, 10, 20)
    full = run_backtest(bars, weights, config)
    for length in range(len(bars) + 1):
        part = run_backtest(bars.iloc[:length], weights.iloc[:length], config)
        assert_frame_equal(part.equity, full.equity.iloc[:length], check_exact=True)
        assert_frame_equal(
            part.positions, full.positions.iloc[:length], check_exact=True
        )
        assert_frame_equal(
            part.trades,
            full.trades[full.trades.ts.isin(bars.ts.iloc[:length])],
            check_exact=True,
        )
    weights.iloc[-1] = 1  # Last target has no execution bar, even with a gap.
    repeat = run_backtest(bars, weights, config)
    for name in ("equity", "positions", "trades"):
        assert_frame_equal(getattr(full, name), getattr(repeat, name), check_exact=True)
    assert_frame_equal(bars, original_bars)
    weights.iloc[-1] = original_targets.iloc[-1]
    assert_series_equal(weights, original_targets)


def test_equal_fractional_target_does_not_trade(bars):
    bars = bars.iloc[:5].assign(open=100.0, high=100.0, low=100.0, close=100.0)
    result = run_backtest(bars, targets(bars, 0.5), BacktestConfig(1000, 10, 20))
    assert len(result.trades) == 1
    assert result.equity.drawdown.iloc[1] < 0  # Initial cash is the first peak.


@pytest.mark.parametrize("field", ["initial_cash", "fee_bps", "slippage_bps"])
@pytest.mark.parametrize(
    "value", [True, False, None, "1", float("nan"), float("inf"), -float("inf"), -1]
)
def test_invalid_config(field, value):
    with pytest.raises(ValueError):
        BacktestConfig(**{"initial_cash": 1000, field: value})


def test_config_boundaries_and_freezing():
    for kwargs in [
        {"initial_cash": 0},
        {"initial_cash": 1000, "fee_bps": 10000},
        {"initial_cash": 1000, "slippage_bps": 10000},
    ]:
        with pytest.raises(ValueError):
            BacktestConfig(**kwargs)
    with pytest.raises(TypeError):
        BacktestConfig()
    with pytest.raises(FrozenInstanceError):
        BacktestConfig(1000).initial_cash = 2


@pytest.mark.parametrize(
    "transform",
    [
        lambda b: None,
        lambda b: b.drop(columns="close"),
        lambda b: b.astype({"ts": "float64"}),
        lambda b: b.assign(close=float("nan")),
        lambda b: b.assign(open=float("inf")),
        lambda b: b.assign(ts=-1),
        lambda b: b.iloc[::-1],
        lambda b: pd.concat([b, b.iloc[-1:]]),
        lambda b: b.assign(open=0.0),
        lambda b: b.assign(close=-1.0),
    ],
)
def test_invalid_bars(bars, transform):
    with pytest.raises(ValueError):
        run_backtest(transform(bars), targets(bars, 0), BacktestConfig(1000))


@pytest.mark.parametrize(
    "transform",
    [
        lambda s: s.tolist(),
        lambda s: s.astype("int64"),
        lambda s: s.astype("float32"),
        lambda s: s.astype("bool"),
        lambda s: s.iloc[::-1],
        lambda s: s.iloc[:-1],
        *[
            lambda s, v=v: s * 0 + v
            for v in [float("nan"), float("inf"), -float("inf"), -0.1, 1.1]
        ],
    ],
)
def test_invalid_targets(bars, transform):
    with pytest.raises(ValueError, match="Targets"):
        run_backtest(bars, transform(targets(bars, 0)), BacktestConfig(1000))


def test_invalid_config_type_and_arithmetic_overflow(bars):
    with pytest.raises(ValueError, match="config"):
        run_backtest(bars, targets(bars, 0), None)
    bars = bars.iloc[:3].assign(open=1.0, close=1e308)
    with pytest.raises(ValueError, match="arithmetic"):
        run_backtest(bars, targets(bars, 1), BacktestConfig(1000))
