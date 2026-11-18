import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

FORBIDDEN_IMPORTS = {
    "data": {"strategy", "backtest"},
    "strategy": {"backtest"},
}
PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "quant_engine"


def _imported_modules(node: ast.Import | ast.ImportFrom, package: str) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]

    module = node.module or ""
    if node.level:
        module = resolve_name("." * node.level + module, package)
    return [module, *(f"{module}.{alias.name}" for alias in node.names)]


def _dependency_violations(package_root: Path) -> list[str]:
    violations = []
    for path in sorted(package_root.rglob("*.py")):
        relative_path = path.relative_to(package_root.parent)
        layer = relative_path.parts[1]
        if layer not in FORBIDDEN_IMPORTS:
            continue

        package = ".".join(relative_path.parent.parts)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            targets = set()
            for module in _imported_modules(node, package):
                parts = module.split(".")
                if (
                    len(parts) >= 2
                    and parts[0] == "quant_engine"
                    and parts[1] in FORBIDDEN_IMPORTS[layer]
                ):
                    targets.add(parts[1])
            for target in sorted(targets):
                violations.append(
                    f"{relative_path.as_posix()}:{node.lineno}: "
                    f"{layer} -> quant_engine.{target}"
                )
    return violations


def test_layer_dependencies() -> None:
    """Source imports must follow the documented layer dependency direction."""
    violations = _dependency_violations(PACKAGE_ROOT)
    assert not violations, "Forbidden layer imports:\n" + "\n".join(violations)


@pytest.mark.parametrize(
    ("source_layer", "target_layer"),
    [("data", "strategy"), ("data", "backtest"), ("strategy", "backtest")],
)
@pytest.mark.parametrize(
    ("filename", "statement"),
    [
        ("module.py", "import quant_engine.{target}"),
        ("module.py", "import os, quant_engine.{target}.module as dependency"),
        ("module.py", "from quant_engine.{target} import module"),
        ("module.py", "from quant_engine import {target} as dependency"),
        ("module.py", "from .. import {target}"),
        ("__init__.py", "from ..{target} import module"),
        ("nested/module.py", "from ... import {target}"),
        ("nested/__init__.py", "from ...{target}.module import value"),
        ("module.py", "if False:\n    import quant_engine.{target}"),
        ("module.py", "def load():\n    from .. import {target}"),
    ],
)
def test_forbidden_imports_are_reported(
    tmp_path: Path,
    source_layer: str,
    target_layer: str,
    filename: str,
    statement: str,
) -> None:
    """Detect every reverse dependency, including nested and relative imports."""
    package_root = tmp_path / "quant_engine"
    source_path = package_root / source_layer / filename
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "# Example source\n" + statement.format(target=target_layer) + "\n",
        encoding="utf-8",
    )
    line = 2 + statement.count("\n")
    assert _dependency_violations(package_root) == [
        f"quant_engine/{source_layer}/{filename}:{line}: "
        f"{source_layer} -> quant_engine.{target_layer}"
    ]


@pytest.mark.parametrize(
    ("filename", "statement"),
    [
        ("strategy/module.py", "import quant_engine.data"),
        ("strategy/module.py", "from quant_engine import data"),
        ("strategy/__init__.py", "from .. import data"),
        ("strategy/nested/module.py", "from ...data import module"),
        ("backtest/module.py", "from .. import strategy, data"),
        ("data/module.py", "from . import local_module"),
        ("data/nested/__init__.py", "from .. import local_module"),
        ("data/module.py", "import strategy, backtest, quant_engine_external.backtest"),
        ("data/module.py", "from quant_engine import strategy_helpers"),
        (
            "data/module.py",
            "# import quant_engine.backtest\ntext = 'from .. import strategy'",
        ),
    ],
)
def test_allowed_imports_are_accepted(
    tmp_path: Path, filename: str, statement: str
) -> None:
    """Allow forward, same-layer, and unrelated imports without false positives."""
    package_root = tmp_path / "quant_engine"
    source_path = package_root / filename
    source_path.parent.mkdir(parents=True)
    source_path.write_text(statement + "\n", encoding="utf-8")
    assert _dependency_violations(package_root) == []
