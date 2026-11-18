from importlib import import_module


def test_layer_packages_import() -> None:
    """The installed distribution exposes all three layer packages."""
    for name in ("quant_engine.data", "quant_engine.strategy", "quant_engine.backtest"):
        assert import_module(name).__name__ == name
