"""Quality checks on raw bars, before order and duplicate information is lost."""

from dataclasses import dataclass

import pandas as pd

from .models import interval_ms, validate_bars, validate_range, validate_timestamp


@dataclass(frozen=True)
class Gap:
    """A missing UTC opening-time range [start_ms, end_ms)."""

    start_ms: int
    end_ms: int
    missing_bars: int


@dataclass(frozen=True)
class QualityReport:
    """Duplicate counts include all occurrences; positions are zero-based."""

    gaps: tuple[Gap, ...]
    duplicates: dict[int, int]
    out_of_order: tuple[int, ...]

    @property
    def ok(self) -> bool:
        """Whether no gaps, duplicate timestamps or descending pairs were found."""
        return not (self.gaps or self.duplicates or self.out_of_order)


def check_quality(
    bars: pd.DataFrame,
    interval: str,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> QualityReport:
    """Inspect raw order/duplicates and gaps; optional bounds include edge gaps.

    Bounds restrict gap detection only. Opening times must be on the interval's
    UTC grid. No missing rows are synthesized, and the input is never modified.
    """
    validate_bars(bars)
    step = interval_ms(interval)
    for bound in (start_ms, end_ms):
        if bound is not None:
            validate_timestamp(bound)
    if start_ms is not None and end_ms is not None:
        validate_range(start_ms, end_ms)
    times = bars.ts.tolist()
    if any(ts % step for ts in times):
        raise ValueError("Bar opening times must align to the interval's UTC grid")
    counts = bars.ts.value_counts()
    duplicates = {int(ts): int(count) for ts, count in counts.items() if count > 1}
    descending = tuple(i for i in range(1, len(times)) if times[i] < times[i - 1])
    unique = sorted(
        ts
        for ts in set(times)
        if (start_ms is None or ts >= start_ms) and (end_ms is None or ts < end_ms)
    )
    edges = unique.copy()
    if start_ms is not None:
        edges.insert(0, ((start_ms + step - 1) // step - 1) * step)
    if end_ms is not None:
        edges.append(((end_ms + step - 1) // step) * step)
    gaps = tuple(
        Gap(left + step, right, (right - left) // step - 1)
        for left, right in zip(edges, edges[1:])
        if right - left > step
    )
    return QualityReport(gaps, duplicates, descending)
