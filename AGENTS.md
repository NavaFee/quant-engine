# AGENTS.md — quant-engine

面向加密货币的研究用量化引擎：数据层、策略层、回测与评估层。没有执行层。

## 结构

```
src/quant_engine/data/      数据层：K 线模型、数据源、本地存储、质量检查
src/quant_engine/strategy/  策略层：策略接口、指标、示例策略
src/quant_engine/backtest/  回测与评估层：回测引擎、绩效指标、结果导出
tests/                      测试，目录与 src 对应
tests/fixtures/             样例数据，测试只读这里
```

依赖方向只能是 backtest → strategy → data，不允许反向依赖。

## 命令

```
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest -q
```

工程骨架任务完成之前，这些命令可能还不可用。

## 规则

- Python 3.11+，公共函数写类型标注和 docstring。
- 测试必须离线可跑：不访问网络，只用 `tests/fixtures/` 里的数据。
- 时间一律用 UTC 毫秒时间戳（int64）。年化按 365 天计算。
- 回测不能用未来数据：第 t 根 K 线收盘产生的信号，最早在第 t+1 根 K 线开盘成交。
- 层间契约以 quant-context 仓库的 `product.md` 为准。要改契约，先改那份文档。

## 禁区

- 不实现下单、撤单、账户、API key 相关的任何代码。
- 不把密钥或 token 写进代码、配置或测试。
- 不直接提交到 main。一个任务一个分支一个 PR。
