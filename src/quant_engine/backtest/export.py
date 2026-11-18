"""Validate and atomically export a complete research report as strict JSON."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd

from quant_engine.data import validate_bars
from quant_engine.data.models import interval_ms, validate_range

from .metrics import calculate_metrics
from .models import BacktestConfig, BacktestResult


def _validate_params(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Strategy parameter keys must be strings")
            _validate_params(item)
    elif isinstance(value, list):
        for item in value:
            _validate_params(item)
    elif value is None or type(value) not in (str, int, float, bool):
        raise ValueError("Strategy parameters must be JSON values without null")


def export_result(
    path: str | Path,
    bars: pd.DataFrame,
    result: BacktestResult,
    config: BacktestConfig,
    *,
    strategy: str,
    params: dict[str, object],
    symbol: str,
    interval: str,
) -> None:
    """Write aligned bars, equity, all fills and metrics; preserve path on failure.

    meta covers actual bars as [first open, last open + interval). Empty bars,
    malformed results, non-finite values and invalid metadata raise ValueError.
    """
    if not isinstance(config, BacktestConfig) or not isinstance(bars, pd.DataFrame):
        raise ValueError("Expected BacktestConfig and bars DataFrame")
    validate_bars(bars)
    if bars.empty:
        raise ValueError("Cannot export empty bars")
    if any(
        not isinstance(value, str) or not value.strip() for value in (strategy, symbol)
    ):
        raise ValueError("Strategy and symbol must be nonempty strings")
    if not isinstance(params, dict):
        raise ValueError("Strategy params must be an object")
    _validate_params(params)
    metrics = calculate_metrics(result, config.initial_cash, interval)
    if not bars.ts.equals(result.equity.ts):
        raise ValueError("Bars and equity must have matching timestamps and indices")
    start, end = int(bars.ts.iloc[0]), int(bars.ts.iloc[-1]) + interval_ms(interval)
    validate_range(start, end)
    report = {
        "meta": {
            "strategy": strategy,
            "params": params,
            "symbol": symbol,
            "interval": interval,
            "start": start,
            "end": end,
            "fee_bps": float(config.fee_bps),
            "slippage_bps": float(config.slippage_bps),
            "initial_cash": float(config.initial_cash),
        },
        "metrics": metrics,
        "equity": result.equity.to_dict("records"),
        "trades": result.trades.to_dict("records"),
        "bars": bars.to_dict("records"),
    }
    try:
        content = (
            json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
        )
    except (TypeError, OverflowError) as exc:
        raise ValueError("Report must contain JSON-compatible values") from exc
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
