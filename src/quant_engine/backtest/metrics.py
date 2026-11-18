"""365-day performance metrics and fee-inclusive completed holding rounds."""

from math import fsum, isfinite, sqrt, ulp
from statistics import stdev

import pandas as pd

from quant_engine.data.models import interval_ms

from .models import BacktestConfig, BacktestResult

YEAR_MS = 365 * 86_400_000
METRIC_NAMES = (
    "total_return",
    "annual_return",
    "annual_volatility",
    "sharpe",
    "max_drawdown",
    "calmar",
    "win_rate",
    "profit_factor",
    "trade_count",
)


def _finite(value: float) -> float:
    if not isfinite(value):
        raise ValueError("Performance arithmetic produced a non-finite value")
    return value


def _validate_result(result: BacktestResult) -> None:
    if not isinstance(result, BacktestResult):
        raise ValueError("result must be a BacktestResult")
    for table, columns in (
        (result.equity, ["ts", "equity", "drawdown"]),
        (result.positions, ["ts", "cash", "qty"]),
        (result.trades, ["ts", "side", "price", "qty", "fee"]),
    ):
        if not isinstance(table, pd.DataFrame) or list(table.columns) != columns:
            raise ValueError(f"Expected result columns: {columns}")
        for name in columns:
            dtype = (
                "int64" if name == "ts" else "object" if name == "side" else "float64"
            )
            if str(table[name].dtype) != dtype:
                raise ValueError(f"Invalid result dtype for {name}: expected {dtype}")
        if (
            table.isna().any().any()
            or table.isin([float("inf"), -float("inf")]).any().any()
        ):
            raise ValueError("Result values must be finite and non-null")
        if (
            (table.ts < 0).any()
            or not table.ts.is_monotonic_increasing
            or not table.ts.is_unique
        ):
            raise ValueError(
                "Result timestamps must be nonnegative, ascending and unique"
            )
    equity, positions, trades = result.equity, result.positions, result.trades
    if not equity.ts.equals(positions.ts):
        raise ValueError(
            "Equity and positions must have matching timestamps and indices"
        )
    if (
        (equity.equity < 0).any()
        or not equity.drawdown.between(-1, 0).all()
        or (positions[["cash", "qty"]] < 0).any().any()
        or not trades.side.isin(["buy", "sell"]).all()
        or (trades[["price", "qty"]] <= 0).any().any()
        or (trades.fee < 0).any()
        or not trades.ts.isin(equity.ts).all()
    ):
        raise ValueError("Invalid equity, position or fill values")
    if len(equity) and (
        positions.qty.iloc[0] != 0 or equity.ts.iloc[0] in trades.ts.values
    ):
        raise ValueError("The first bar must be flat with no fill")


def _completed_pnl(result: BacktestResult) -> list[float]:
    fills = {row.ts: row for row in result.trades.itertuples(index=False)}
    completed, flows = [], []
    previous_qty = 0.0
    for row in result.positions.itertuples(index=False):
        fill = fills.get(row.ts)
        if fill is not None:
            if previous_qty == 0 and (fill.side != "buy" or row.qty == 0):
                raise ValueError("A holding round must start with a buy")
            expected_qty = _finite(
                previous_qty + (fill.qty if fill.side == "buy" else -fill.qty)
            )
            if abs(expected_qty - row.qty) > 8 * ulp(
                max(previous_qty, fill.qty, row.qty)
            ):
                raise ValueError("Fill quantities must match positions")
            notional = _finite(fill.price * fill.qty)
            flows.append(
                _finite((-notional if fill.side == "buy" else notional) - fill.fee)
            )
        elif row.qty != previous_qty:
            raise ValueError("Position changes require a fill")
        if previous_qty > 0 and row.qty == 0:
            if fill.side != "sell":
                raise ValueError("A holding round must finish with a sell")
            completed.append(_finite(fsum(flows)))
            flows = []
        previous_qty = row.qty
    return completed


def calculate_metrics(
    result: BacktestResult, initial_cash: float, interval: str
) -> dict[str, float | int | None]:
    """Return nine metrics; undefined ratios are None, invalid input raises ValueError.

    Annual return uses elapsed time between first and last close valuations.
    Volatility uses adjacent returns (sample deviation), only on regular bars.
    Trades count complete flat-to-flat rounds including fees; open rounds do
    not contribute to win rate or profit factor. Inputs are never changed.
    """
    BacktestConfig(initial_cash)
    step = interval_ms(interval)
    _validate_result(result)
    metrics = dict.fromkeys(METRIC_NAMES)
    metrics["trade_count"] = 0
    if result.equity.empty:
        return metrics
    values = result.equity.equity.tolist()
    times = result.equity.ts.tolist()
    try:
        growth = _finite(values[-1] / float(initial_cash))
        total = growth - 1
        annual = (
            _finite(growth ** (YEAR_MS / (times[-1] - times[0])) - 1)
            if len(times) > 1
            else None
        )
        volatility = None
        if (
            len(values) >= 3
            and all(value > 0 for value in values[:-1])
            and all(right - left == step for left, right in zip(times, times[1:]))
        ):
            returns = [
                _finite(right / left - 1) for left, right in zip(values, values[1:])
            ]
            volatility = _finite(stdev(returns) * sqrt(YEAR_MS / step))
        drawdown = float(result.equity.drawdown.min())
        pnl = _completed_pnl(result)
        profit = _finite(fsum(value for value in pnl if value > 0))
        loss = _finite(-fsum(value for value in pnl if value < 0))
        metrics.update(
            total_return=total,
            annual_return=annual,
            annual_volatility=volatility,
            sharpe=_finite(annual / volatility)
            if annual is not None and volatility
            else None,
            max_drawdown=drawdown,
            calmar=_finite(annual / abs(drawdown))
            if annual is not None and drawdown
            else None,
            win_rate=sum(value > 0 for value in pnl) / len(pnl) if pnl else None,
            profit_factor=_finite(profit / loss) if loss else None,
            trade_count=len(pnl),
        )
    except (OverflowError, ZeroDivisionError) as exc:
        raise ValueError("Performance arithmetic overflow") from exc
    return metrics
