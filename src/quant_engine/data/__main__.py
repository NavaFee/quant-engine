"""Download closed public klines into local Parquet partitions."""

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone

from .models import INTERVAL_MS, validate_range
from .sources import BinanceSource, DataSource, DownloadError
from .store import ParquetStore


def parse_utc(value: str) -> int:
    """Parse an ISO date/datetime; naive values mean UTC, offsets convert to UTC."""
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        date = date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date
        delta = date.astimezone(timezone.utc) - datetime(
            1970, 1, 1, tzinfo=timezone.utc
        )
        if delta.microseconds % 1000:
            raise ValueError("Use millisecond precision or coarser")
        return (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid UTC date: {value}: {exc}") from exc


def main(argv: list[str] | None = None, *, source: DataSource | None = None) -> int:
    """Download completely before writing; print a JSON count, path and quality report."""
    parser = argparse.ArgumentParser(prog="python -m quant_engine.data")
    commands = parser.add_subparsers(dest="command", required=True)
    download = commands.add_parser(
        "download", help="Download closed Binance spot klines"
    )
    download.add_argument("--symbol", required=True, choices=BinanceSource.symbols)
    download.add_argument("--interval", required=True, choices=INTERVAL_MS)
    download.add_argument("--start", required=True, type=parse_utc)
    download.add_argument("--end", required=True, type=parse_utc)
    download.add_argument("--root", default="data", help="Storage root (default: data)")
    args = parser.parse_args(argv)
    try:
        validate_range(args.start, args.end)
        source = source if source is not None else BinanceSource()
        bars = source.fetch(args.symbol, args.interval, args.start, args.end)
        store = ParquetStore(args.root)
        report = store.write(source.exchange, args.symbol, args.interval, bars)
        report = getattr(source, "last_quality", None) or report
        print(
            json.dumps(
                {
                    "saved": len(bars),
                    "path": str(
                        store.path(source.exchange, args.symbol, args.interval)
                    ),
                    "quality": asdict(report),
                }
            )
        )
        return 0
    except (DownloadError, ValueError, OSError) as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
