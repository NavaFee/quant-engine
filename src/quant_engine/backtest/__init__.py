"""Historical long-only simulation, without an execution layer."""

from .engine import run_backtest
from .models import BacktestConfig, BacktestResult

__all__ = ["BacktestConfig", "BacktestResult", "run_backtest"]
