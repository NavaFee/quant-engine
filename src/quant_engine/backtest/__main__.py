"""Run the moving-average research example entirely from local kline JSON."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from quant_engine.data import BAR_DTYPES
from quant_engine.data.models import INTERVAL_MS, interval_ms
from quant_engine.strategy import MovingAverageParams, MovingAverageStrategy

from .engine import run_backtest
from .export import export_result
from .models import BacktestConfig


def main(argv: list[str] | None = None) -> int:
    """Read Binance-format local rows, backtest and export; return 1 on failure."""
    parser = argparse.ArgumentParser(prog="python -m quant_engine.backtest")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--symbol", required=True, choices=("BTCUSDT", "ETHUSDT"))
    parser.add_argument("--interval", required=True, choices=INTERVAL_MS)
    parser.add_argument("--fast", type=int, default=5)
    parser.add_argument("--slow", type=int, default=20)
    parser.add_argument("--initial-cash", type=float, default=10000)
    parser.add_argument("--fee-bps", type=float, default=10)
    parser.add_argument("--slippage-bps", type=float, default=20)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        params = MovingAverageParams(args.fast, args.slow)
        config = BacktestConfig(args.initial_cash, args.fee_bps, args.slippage_bps)
        rows = json.loads(args.input.read_text(encoding="utf-8"))
        step = interval_ms(args.interval)
        if not isinstance(rows, list) or any(
            not isinstance(row, list)
            or len(row) != 12
            or type(row[0]) is not int
            or not 0 <= row[0] < 2**63
            or row[0] % step
            or type(row[6]) is not int
            or row[6] != row[0] + step - 1
            or any(isinstance(value, bool) for value in row[1:6])
            for row in rows
        ):
            raise ValueError(
                "Expected Binance kline rows matching the declared interval"
            )
        bars = pd.DataFrame([row[:6] for row in rows], columns=BAR_DTYPES).astype(
            BAR_DTYPES
        )
        strategy = MovingAverageStrategy(params)
        result = run_backtest(bars, strategy.generate(bars), config)
        export_result(
            args.output,
            bars,
            result,
            config,
            strategy="MovingAverageStrategy",
            params=asdict(params),
            symbol=args.symbol,
            interval=args.interval,
        )
        print(json.dumps({"output": str(args.output), "bars": len(bars)}))
        return 0
    except (ValueError, TypeError, OverflowError, OSError) as exc:
        print(f"Backtest failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
