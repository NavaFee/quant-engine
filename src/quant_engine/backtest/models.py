"""Configuration and tabular results for a long-only historical backtest."""

from dataclasses import dataclass
from math import isfinite
from numbers import Real

import pandas as pd


@dataclass(frozen=True)
class BacktestConfig:
    """Positive starting cash and transaction costs in basis points."""

    initial_cash: float
    fee_bps: float = 0.0
    slippage_bps: float = 0.0

    def __post_init__(self) -> None:
        for name in ("initial_cash", "fee_bps", "slippage_bps"):
            value = getattr(self, name)
            try:
                valid = isinstance(value, Real) and not isinstance(value, bool)
                valid = valid and isfinite(value)
                valid = valid and (
                    value > 0 if name == "initial_cash" else 0 <= value < 10000
                )
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError(
                    f"Invalid {name}: require finite cash > 0 or bps in [0, 10000)"
                )


@dataclass(frozen=True)
class BacktestResult:
    """Close equity/drawdown, cash/quantity per bar, and simulated fills."""

    equity: pd.DataFrame
    positions: pd.DataFrame
    trades: pd.DataFrame
