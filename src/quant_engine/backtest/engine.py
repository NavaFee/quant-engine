"""Causal next-open rebalancing with fractional quantities and cash costs."""

from math import isfinite, ulp

import pandas as pd

from quant_engine.data import validate_bars

from .models import BacktestConfig, BacktestResult


def _nonnegative(value: float, scale: float) -> float:
    if not isfinite(value) or value < -8 * ulp(scale):
        raise ValueError(
            "Backtest arithmetic produced a non-finite or negative balance"
        )
    return max(value, 0.0)


def _rebalance(cash, qty, opening, weight, fee_rate, slippage):
    wanted_cash = weight * cash
    retained_value = (1 - weight) * qty * opening
    delta = wanted_cash - retained_value
    if not isfinite(delta):
        raise ValueError("Backtest arithmetic overflow")
    if abs(delta) <= 8 * ulp(max(wanted_cash, retained_value)):
        return cash, qty, None
    direction = 1 if delta > 0 else -1
    price = opening * (1 + direction * slippage)
    unit_cash = price * (1 + direction * fee_rate)
    # Solve q' * open / (cash' + q' * open) = weight, including costs.
    amount = (
        qty
        if weight == 0
        else abs(delta) / ((1 - weight) * opening + weight * unit_cash)
    )
    notional = amount * price
    fee = notional * fee_rate
    cash_scale = max(cash, notional, fee)
    cash = _nonnegative(cash - direction * notional - fee, cash_scale)
    qty = _nonnegative(qty + direction * amount, max(qty, amount))
    if weight == 1 and cash <= 8 * ulp(cash_scale):
        cash = 0.0  # Only remove the all-in subtraction's rounding residue.
    return cash, qty, ("buy" if direction > 0 else "sell", price, amount, fee)


def _table(rows: list[tuple], columns: list[str], index=None) -> pd.DataFrame:
    dtypes = {
        name: "int64" if name == "ts" else "object" if name == "side" else "float64"
        for name in columns
    }
    return pd.DataFrame(rows, columns=columns, index=index).astype(dtypes)


def run_backtest(
    bars: pd.DataFrame, targets: pd.Series, config: BacktestConfig
) -> BacktestResult:
    """Apply previous-row targets at each open; mark equity at each close.

    Inputs are validated without mutation. Invalid data or unrepresentable
    arithmetic raises ValueError. No initial fill or final liquidation occurs.
    """
    if not isinstance(config, BacktestConfig):
        raise ValueError("config must be a BacktestConfig")
    if not isinstance(bars, pd.DataFrame):
        raise ValueError("bars must be a DataFrame")
    validate_bars(bars)
    if not bars.ts.is_monotonic_increasing or not bars.ts.is_unique:
        raise ValueError("Bar timestamps must be ascending and unique")
    if (bars[["open", "close"]] <= 0).any().any():
        raise ValueError("Bar open and close must be positive")
    if (
        not isinstance(targets, pd.Series)
        or str(targets.dtype) != "float64"
        or not targets.index.equals(bars.index)
        or not targets.between(0.0, 1.0).all()
    ):
        raise ValueError("Targets must be float64, same-index, finite and in [0, 1]")
    cash, qty, peak = float(config.initial_cash), 0.0, float(config.initial_cash)
    fee_rate, slippage = (
        float(config.fee_bps) / 10000,
        float(config.slippage_bps) / 10000,
    )
    equities, positions, trades = [], [], []
    for i, (ts, opening, close) in enumerate(
        bars[["ts", "open", "close"]].itertuples(index=False, name=None)
    ):
        if i:
            cash, qty, trade = _rebalance(
                cash, qty, opening, float(targets.iloc[i - 1]), fee_rate, slippage
            )
            if trade is not None:
                trades.append((ts, *trade))
        equity = _nonnegative(cash + qty * close, cash)
        peak = max(peak, equity)
        equities.append((ts, equity, equity / peak - 1))
        positions.append((ts, cash, qty))
    return BacktestResult(
        _table(equities, ["ts", "equity", "drawdown"], bars.index),
        _table(positions, ["ts", "cash", "qty"], bars.index),
        _table(trades, ["ts", "side", "price", "qty", "fee"]),
    )
