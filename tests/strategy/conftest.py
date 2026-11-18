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
def bars():
    path = Path(__file__).parents[1] / "fixtures" / "binance_btcusdt_1h.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    return pd.DataFrame(
        [row[:6] for row in rows],
        columns=BAR_DTYPES,
        index=pd.Index([f"bar-{i}" for i in range(len(rows))], name="row"),
    ).astype(BAR_DTYPES)
