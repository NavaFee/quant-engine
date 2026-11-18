import json
import math
import runpy
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from quant_engine.backtest import BacktestConfig, export_result, run_backtest
from quant_engine.backtest import export as export_module
from quant_engine.backtest.__main__ import main
from quant_engine.strategy import MovingAverageParams, MovingAverageStrategy

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "tests" / "fixtures" / "binance_btcusdt_1h.json"
CONFIG = BacktestConfig(10000, 10, 20)
PARAMS = MovingAverageParams(5, 20)
METADATA = {
    "strategy": "MovingAverageStrategy",
    "params": asdict(PARAMS),
    "symbol": "BTCUSDT",
    "interval": "1h",
}
METRICS = {
    "total_return",
    "annual_return",
    "annual_volatility",
    "sharpe",
    "max_drawdown",
    "calmar",
    "win_rate",
    "profit_factor",
    "trade_count",
}


def read_report(path):
    def reject(value):
        raise AssertionError(f"Non-standard JSON constant: {value}")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)


def assert_contract(report):
    assert set(report) == {"meta", "metrics", "bars", "equity", "trades"}
    meta = report["meta"]
    assert set(meta) == {
        "strategy",
        "params",
        "symbol",
        "interval",
        "start",
        "end",
        "fee_bps",
        "slippage_bps",
        "initial_cash",
    }
    assert isinstance(meta["params"], dict)
    assert all(
        isinstance(meta[name], str) for name in ("strategy", "symbol", "interval")
    )
    assert type(meta["start"]) is type(meta["end"]) is int
    assert meta["start"] == report["bars"][0]["ts"]
    assert meta["end"] == report["bars"][-1]["ts"] + 3_600_000
    for name in ("fee_bps", "slippage_bps", "initial_cash"):
        assert type(meta[name]) in (int, float) and math.isfinite(meta[name])
    assert set(report["metrics"]) == METRICS
    assert type(report["metrics"]["trade_count"]) is int
    assert report["metrics"]["trade_count"] >= 0
    for name in METRICS - {"trade_count"}:
        value = report["metrics"][name]
        assert value is None or (type(value) in (int, float) and math.isfinite(value))
    assert report["metrics"]["max_drawdown"] <= 0
    for name, keys in (
        ("bars", {"ts", "open", "high", "low", "close", "volume"}),
        ("equity", {"ts", "equity", "drawdown"}),
        ("trades", {"ts", "side", "price", "qty", "fee"}),
    ):
        assert isinstance(report[name], list)
        for row in report[name]:
            assert set(row) == keys
            assert type(row["ts"]) is int and 0 <= row["ts"] < 2**63
            for key in keys - {"ts", "side"}:
                assert type(row[key]) in (int, float) and math.isfinite(row[key])
            if name == "trades":
                assert row["side"] in ("buy", "sell")
    times = [row["ts"] for row in report["bars"]]
    assert times == sorted(set(times))
    assert times == [row["ts"] for row in report["equity"]]
    assert all(row["ts"] in times for row in report["trades"])


@pytest.mark.parametrize("trading", [True, False])
def test_contract_all_rows_actual_metadata_and_immutable_inputs(
    tmp_path, bars, trading
):
    targets = (
        MovingAverageStrategy(PARAMS).generate(bars)
        if trading
        else pd.Series(0.0, index=bars.index)
    )
    result = run_backtest(bars, targets, CONFIG)
    originals = [
        frame.copy(deep=True)
        for frame in (bars, result.equity, result.positions, result.trades)
    ]
    path = tmp_path / "nested" / "result.json"
    export_result(path, bars, result, CONFIG, **METADATA)
    report = read_report(path)
    assert_contract(report)
    assert report["meta"] == {
        **METADATA,
        **asdict(CONFIG),
        "start": 1704067200000,
        "end": 1705867200000,
    }
    assert len(report["bars"]) == len(report["equity"]) == 500
    assert report["bars"] == bars.to_dict("records")
    assert report["trades"] == result.trades.to_dict("records")
    if trading:
        assert report["metrics"]["trade_count"] > 0
        assert len(report["trades"]) > report["metrics"]["trade_count"]
    else:
        assert report["trades"] == []
        assert report["metrics"]["sharpe"] is report["metrics"]["calmar"] is None
        assert (
            report["metrics"]["win_rate"] is report["metrics"]["profit_factor"] is None
        )
    for actual, before in zip(
        (bars, result.equity, result.positions, result.trades), originals
    ):
        assert_frame_equal(actual, before)


@pytest.mark.parametrize(
    "problem",
    [
        "empty",
        "alignment",
        "nan",
        "infinity",
        "bool",
        "params",
        "null",
        "symbol",
        "end_overflow",
    ],
)
def test_invalid_export_preserves_existing_file(tmp_path, bars, problem):
    path = tmp_path / "result.json"
    path.write_bytes(b"original report")
    bars = bars.iloc[: 0 if problem == "empty" else 3].copy()
    if problem == "end_overflow":
        bars["ts"] = pd.Series(
            [2**63 - 4, 2**63 - 3, 2**63 - 2], index=bars.index, dtype="int64"
        )
    result = run_backtest(bars, pd.Series(0.0, index=bars.index), CONFIG)
    metadata = dict(METADATA)
    if problem == "alignment":
        result.equity.loc[result.equity.index[1], "ts"] += 1
        result.positions.loc[result.positions.index[1], "ts"] += 1
    elif problem in ("nan", "infinity"):
        result.equity.loc[result.equity.index[1], "equity"] = float(
            "nan" if problem == "nan" else "inf"
        )
    elif problem == "bool":
        result.equity["equity"] = True
    elif problem in ("params", "null"):
        metadata["params"] = {"bad": float("inf") if problem == "params" else None}
    elif problem == "symbol":
        metadata["symbol"] = ""
    with pytest.raises(ValueError):
        export_result(path, bars, result, CONFIG, **metadata)
    assert path.read_bytes() == b"original report"
    assert list(tmp_path.iterdir()) == [path]


def test_replace_failure_preserves_report_and_cleans_temporary_file(
    tmp_path, bars, monkeypatch
):
    path = tmp_path / "result.json"
    path.write_bytes(b"original report")
    result = run_backtest(bars, pd.Series(0.0, index=bars.index), CONFIG)

    def fail(*args):
        raise OSError("replace failed")

    monkeypatch.setattr(export_module.os, "replace", fail)
    with pytest.raises(OSError, match="replace failed"):
        export_result(path, bars, result, CONFIG, **METADATA)
    assert path.read_bytes() == b"original report"
    assert list(tmp_path.iterdir()) == [path]


def arguments(output):
    return [
        "--input",
        str(INPUT),
        "--symbol",
        "BTCUSDT",
        "--interval",
        "1h",
        "--fast",
        "5",
        "--slow",
        "20",
        "--initial-cash",
        "10000",
        "--fee-bps",
        "10",
        "--slippage-bps",
        "20",
        "--output",
        str(output),
    ]


def test_module_cli_offline_and_checked_in_example_reproducible(
    tmp_path, monkeypatch, capsys
):
    path = tmp_path / "result.json"
    monkeypatch.delitem(sys.modules, "quant_engine.backtest.__main__", raising=False)
    monkeypatch.setattr(sys, "argv", ["quant_engine.backtest", *arguments(path)])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("quant_engine.backtest", run_name="__main__")
    assert exit_info.value.code == 0
    assert json.loads(capsys.readouterr().out) == {"output": str(path), "bars": 500}
    report = read_report(path)
    assert_contract(report)
    assert report == read_report(ROOT / "examples" / "result.json")
    assert main(arguments(path)) == 0
    assert read_report(path) == report


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--input", "missing.json"),
        ("--fast", "20"),
        ("--initial-cash", "nan"),
        ("--interval", "4h"),
    ],
)
def test_cli_invalid_options_preserve_output(tmp_path, capsys, flag, value):
    path = tmp_path / "result.json"
    path.write_bytes(b"original report")
    args = arguments(path)
    args[args.index(flag) + 1] = value
    assert main(args) == 1
    assert capsys.readouterr().err.startswith("Backtest failed:")
    assert path.read_bytes() == b"original report"


@pytest.mark.parametrize(
    "content", ["not json", "{}", "[]", "[[1]]", "[[true,1,1,1,1,1,3599999,0,0,0,0,0]]"]
)
def test_cli_invalid_local_data_does_not_create_report(tmp_path, capsys, content):
    path = tmp_path / "result.json"
    source = tmp_path / "input.json"
    source.write_text(content)
    args = arguments(path)
    args[args.index("--input") + 1] = str(source)
    assert main(args) == 1
    assert capsys.readouterr().err.startswith("Backtest failed:")
    assert not path.exists()
