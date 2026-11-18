"""A long-only example comparing fast and slow close-price SMAs."""

from dataclasses import dataclass

import pandas as pd

from .base import Strategy
from .indicators import _validate_period, sma


@dataclass(frozen=True)
class MovingAverageParams:
    """Required positive integer windows, with fast strictly below slow."""

    fast: int
    slow: int

    def __post_init__(self) -> None:
        """Reject invalid windows before generating any targets."""
        _validate_period(self.fast)
        _validate_period(self.slow)
        if self.fast >= self.slow:
            raise ValueError("fast must be smaller than slow")


@dataclass(frozen=True)
class MovingAverageStrategy(Strategy):
    """Hold 1 when fast SMA > slow SMA, otherwise 0 (including warmup)."""

    params: MovingAverageParams

    def _generate(self, bars: pd.DataFrame) -> pd.Series:
        return (
            sma(bars.close, self.params.fast) > sma(bars.close, self.params.slow)
        ).astype("float64")
