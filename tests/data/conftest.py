import json
import socket
from pathlib import Path

import pandas as pd
import pytest

from quant_engine.data import BAR_DTYPES


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("Tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)


@pytest.fixture
def rows():
    path = Path(__file__).parents[1] / "fixtures" / "binance_btcusdt_1h.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def bars(rows):
    return pd.DataFrame([row[:6] for row in rows], columns=BAR_DTYPES).astype(
        BAR_DTYPES
    )


@pytest.fixture
def klines(rows):
    """Reuse historical OHLCV with controlled timestamps for pagination/intervals."""

    def make(count, step=3_600_000):
        result = []
        for index in range(count):
            row = rows[index % len(rows)].copy()
            row[0] = rows[0][0] + index * step
            row[6] = row[0] + step - 1
            result.append(row)
        return result

    return make
