"""Validated, close-of-bar target positions for long-only strategies."""

from abc import ABC, abstractmethod

import pandas as pd

from quant_engine.data.models import validate_bars


def _validate_bars(bars: pd.DataFrame) -> None:
    if not isinstance(bars, pd.DataFrame):
        raise ValueError("bars must be a DataFrame")
    validate_bars(bars)
    if not bars.ts.is_monotonic_increasing or not bars.ts.is_unique:
        raise ValueError("Bar timestamps must be ascending and unique")


class Strategy(ABC):
    """Implement _generate using only current and preceding bars."""

    def generate(self, bars: pd.DataFrame) -> pd.Series:
        """Return finite float64 targets in [0, 1], preserving bars and its index."""
        _validate_bars(bars)
        if bars.empty:
            return pd.Series(index=bars.index, dtype="float64")
        targets = self._generate(bars.copy(deep=True))
        if (
            not isinstance(targets, pd.Series)
            or str(targets.dtype) != "float64"
            or not targets.index.equals(bars.index)
            or not targets.between(0.0, 1.0).all()
        ):
            raise ValueError(
                "Targets must be float64, same-index, finite and in [0, 1]"
            )
        return targets

    @abstractmethod
    def _generate(self, bars: pd.DataFrame) -> pd.Series:
        """Compute targets from the validated copy; do not shift signals."""
