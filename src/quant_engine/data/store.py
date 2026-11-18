"""Single-writer Parquet storage partitioned by exchange, symbol and interval."""

import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd

from .models import empty_bars, interval_ms, normalize_bars, validate_range
from .quality import QualityReport, check_quality


class ParquetStore:
    """Merge whole partitions and atomically replace files on the same filesystem."""

    def __init__(self, root: str | Path) -> None:
        """Store partitions below root."""
        self.root = Path(root)

    def path(self, exchange: str, symbol: str, interval: str) -> Path:
        """Return a partition path, rejecting separators and traversal components."""
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", exchange):
            raise ValueError("exchange must be a lowercase identifier")
        if not re.fullmatch(r"[A-Z][A-Z0-9]*", symbol):
            raise ValueError("symbol must be an uppercase alphanumeric identifier")
        interval_ms(interval)
        return self.root / exchange / symbol / interval / "bars.parquet"

    def write(
        self, exchange: str, symbol: str, interval: str, bars: pd.DataFrame
    ) -> QualityReport:
        """Report raw quality then upsert; incoming values win at the same ts.

        Empty input leaves existing data untouched. Any write/replace failure
        preserves the previous partition and removes the temporary file.
        """
        path = self.path(exchange, symbol, interval)
        report = check_quality(bars, interval)
        if bars.empty:
            return report
        existing = (
            pd.read_parquet(path, engine="pyarrow") if path.exists() else empty_bars()
        )
        existing = normalize_bars(existing)
        merged = normalize_bars(pd.concat([existing, bars], ignore_index=True))
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            dir=path.parent, suffix=".parquet", delete=False
        ) as file:
            temporary = Path(file.name)
        try:
            merged.to_parquet(temporary, engine="pyarrow", index=False)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return report

    def read(
        self, exchange: str, symbol: str, interval: str, start_ms: int, end_ms: int
    ) -> pd.DataFrame:
        """Read sorted, unique bars in [start_ms, end_ms), or a typed empty table."""
        validate_range(start_ms, end_ms)
        path = self.path(exchange, symbol, interval)
        if not path.exists():
            return empty_bars()
        bars = normalize_bars(pd.read_parquet(path, engine="pyarrow"))
        return bars.loc[(bars.ts >= start_ms) & (bars.ts < end_ms)].reset_index(
            drop=True
        )
