import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from quant_engine.backtest import (
    BacktestConfig,
    BacktestResult,
    calculate_metrics,
    run_backtest,
)

DAY = 86_400_000


def sample(values, *, quantities=None, fills=(), times=None):
    times = list(range(0, len(values) * DAY, DAY)) if times is None else times
    equity = pd.DataFrame(
        {
            "ts": pd.Series(times, dtype="int64"),
            "equity": pd.Series(values, dtype="float64"),
        }
    )
    equity["drawdown"] = equity.equity / equity.equity.cummax().clip(lower=100) - 1
    positions = pd.DataFrame(
        {
            "ts": equity.ts,
            "cash": equity.equity,
            "qty": pd.Series(quantities or [0] * len(values), dtype="float64"),
        }
    )
    trades = pd.DataFrame(
        [(times[i], *fill) for i, *fill in fills],
        columns=["ts", "side", "price", "qty", "fee"],
    ).astype(
        {
            "ts": "int64",
            "side": "object",
            "price": "float64",
            "qty": "float64",
            "fee": "float64",
        }
    )
    return BacktestResult(equity, positions, trades)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("total_return", -0.01),
        ("annual_return", -0.840256566794465),
        ("annual_volatility", 2.701851217221259),
        ("sharpe", -0.310992907913943),
        ("max_drawdown", -0.1),
        ("calmar", -8.402565667944650),
    ],
)
def test_independent_hand_calculated_equity_metrics(name, expected):
    # Reference constants independently calculated at 50-digit Decimal precision.
    metrics = calculate_metrics(sample([100, 110, 99]), 100, "1d")
    assert metrics[name] == pytest.approx(expected, rel=0, abs=1e-9)


@pytest.mark.parametrize(
    "name,expected", [("win_rate", 1 / 3), ("profit_factor", 2), ("trade_count", 3)]
)
def test_complete_rounds_include_both_fees_partial_sales_and_break_even(name, expected):
    # First round: (14-1)+(19-1)-(2*10+1)=10; next rounds: -5, 0.
    # The last round is still open despite a profitable partial sale.
    result = sample(
        [100] * 10,
        quantities=[0, 2, 1, 0, 1, 0, 1, 0, 2, 1],
        fills=[
            (1, "buy", 10, 2, 1),
            (2, "sell", 14, 1, 1),
            (3, "sell", 19, 1, 1),
            (4, "buy", 10, 1, 1),
            (5, "sell", 7, 1, 1),
            (6, "buy", 10, 1, 1),
            (7, "sell", 12, 1, 1),
            (8, "buy", 4, 2, 1),
            (9, "sell", 7, 1, 1),
        ],
    )
    assert calculate_metrics(result, 100, "1d")[name] == pytest.approx(
        expected, rel=0, abs=1e-9
    )


@pytest.mark.parametrize("sell,win,pf", [(13, 1, None), (11, 0, 0), (12, 0, None)])
def test_only_wins_only_losses_or_break_even(sell, win, pf):
    result = sample(
        [100] * 3,
        quantities=[0, 1, 0],
        fills=[(1, "buy", 10, 1, 1), (2, "sell", sell, 1, 1)],
    )
    metrics = calculate_metrics(result, 100, "1d")
    assert metrics["win_rate"] == win
    assert metrics["profit_factor"] == pf
    assert metrics["trade_count"] == 1


def test_multiple_buys_belong_to_one_round():
    result = sample(
        [100] * 4,
        quantities=[0, 1, 3, 0],
        fills=[
            (1, "buy", 10, 1, 1),
            (2, "buy", 20, 2, 1),
            (3, "sell", 18, 3, 1),
        ],
    )
    metrics = calculate_metrics(result, 100, "1d")
    assert metrics["trade_count"] == 1
    assert metrics["win_rate"] == 1  # 54 - 1 - 11 - 41 = 1


@pytest.mark.parametrize("length", [0, 1, 2, 3])
def test_empty_single_short_and_constant(length):
    metrics = calculate_metrics(sample([100] * length), 100, "1d")
    assert metrics == {
        "total_return": 0 if length else None,
        "annual_return": 0 if length > 1 else None,
        "annual_volatility": 0 if length >= 3 else None,
        "sharpe": None,
        "max_drawdown": 0 if length else None,
        "calmar": None,
        "win_rate": None,
        "profit_factor": None,
        "trade_count": 0,
    }


@pytest.mark.parametrize(
    "interval,step,expected",
    [
        ("1h", 3_600_000, 13.23631368621944),
        ("4h", 14_400_000, 6.61815684310972),
        ("1d", DAY, 2.701851217221259),
    ],
)
def test_365_day_volatility_scaling(interval, step, expected):
    result = sample([100, 110, 99], times=[0, step, 2 * step])
    assert calculate_metrics(result, 100, interval)[
        "annual_volatility"
    ] == pytest.approx(expected, rel=0, abs=1e-9)


def test_gap_keeps_elapsed_annualization_but_invalidates_volatility():
    metrics = calculate_metrics(
        sample([100, 110, 99], times=[0, DAY, 365 * DAY]), 100, "1d"
    )
    assert metrics["annual_return"] == pytest.approx(-0.01, rel=0, abs=1e-9)
    assert metrics["calmar"] == pytest.approx(-0.1, rel=0, abs=1e-9)
    assert metrics["annual_volatility"] is metrics["sharpe"] is None


@pytest.mark.parametrize(
    "values,volatility", [([100, 0, 0], None), ([100, 100, 0], 13.509256086106296)]
)
def test_zero_prior_equity_and_terminal_loss(values, volatility):
    metrics = calculate_metrics(sample(values), 100, "1d")
    assert (
        metrics["total_return"]
        == metrics["annual_return"]
        == metrics["max_drawdown"]
        == -1
    )
    assert metrics["calmar"] == -1
    assert (
        metrics["annual_volatility"] == pytest.approx(volatility, rel=0, abs=1e-9)
        if volatility is not None
        else metrics["annual_volatility"] is None
    )


def test_open_position_affects_equity_but_not_trade_statistics(bars):
    bars = bars.iloc[:3]
    result = run_backtest(
        bars, pd.Series(1.0, index=bars.index), BacktestConfig(100, 10, 20)
    )
    before = [
        frame.copy(deep=True)
        for frame in (result.equity, result.positions, result.trades)
    ]
    metrics = calculate_metrics(result, 100, "1h")
    assert metrics["total_return"] != 0
    assert metrics["trade_count"] == 0
    assert metrics["win_rate"] is metrics["profit_factor"] is None
    for actual, original in zip(
        (result.equity, result.positions, result.trades), before
    ):
        assert_frame_equal(actual, original)


@pytest.mark.parametrize("cash", [0, -1, True, float("inf"), float("nan")])
def test_invalid_cash(cash):
    with pytest.raises(ValueError):
        calculate_metrics(sample([100] * 3), cash, "1d")


@pytest.mark.parametrize(
    "table,column,value",
    [
        ("equity", "equity", float("nan")),
        ("equity", "drawdown", float("inf")),
        ("equity", "equity", -1),
        ("equity", "drawdown", 1),
        ("positions", "cash", float("inf")),
        ("positions", "qty", -1),
        ("positions", "ts", 1),
        ("equity", "ts", -1),
    ],
)
def test_invalid_results(table, column, value):
    result = sample([100] * 3)
    getattr(result, table).loc[1, column] = value
    with pytest.raises(ValueError):
        calculate_metrics(result, 100, "1d")


@pytest.mark.parametrize(
    "values,times",
    [
        ([100, 1e308], None),
        ([100, 200], [0, 1]),
        ([100, 1e-300, 1e100], None),
    ],
)
def test_arithmetic_overflow_is_an_error_not_null(values, times):
    with pytest.raises(ValueError, match="arithmetic"):
        calculate_metrics(sample(values, times=times), 100, "1d")


def test_invalid_interval():
    with pytest.raises(ValueError, match="interval"):
        calculate_metrics(sample([]), 100, "5m")


def test_annualization_preserves_small_positive_terminal_equity():
    # E/C=1e-20 over five years: fifth root = 1e-4, even if R rounds to -1.
    result = sample([100, 1e-18], times=[0, 5 * 365 * DAY])
    assert calculate_metrics(result, 100, "1d")["annual_return"] == pytest.approx(
        -0.9999, rel=0, abs=1e-12
    )


@pytest.mark.parametrize(
    "column,value",
    [
        ("side", "hold"),
        ("price", float("inf")),
        ("qty", 0),
        ("fee", -1),
        ("ts", 1),
    ],
)
def test_invalid_fill_values(column, value):
    result = sample(
        [100] * 3,
        quantities=[0, 1, 0],
        fills=[(1, "buy", 10, 1, 1), (2, "sell", 12, 1, 1)],
    )
    result.trades.loc[0, column] = value
    with pytest.raises(ValueError):
        calculate_metrics(result, 100, "1d")


def test_fill_quantities_must_match_round_boundaries():
    result = sample(
        [100] * 3,
        quantities=[0, 2, 0],
        fills=[(1, "buy", 10, 1, 1), (2, "sell", 12, 1, 1)],
    )
    with pytest.raises(ValueError, match="quantities"):
        calculate_metrics(result, 100, "1d")


def test_missing_fills_are_invalid():
    with pytest.raises(ValueError, match="require a fill"):
        calculate_metrics(sample([100] * 3, quantities=[0, 1, 0]), 100, "1d")


def test_trade_arithmetic_overflow():
    result = sample(
        [100] * 3,
        quantities=[0, 2, 0],
        fills=[(1, "buy", 1e308, 2, 1), (2, "sell", 12, 2, 1)],
    )
    with pytest.raises(ValueError, match="arithmetic"):
        calculate_metrics(result, 100, "1d")
