# quant-engine

面向加密货币的研究用量化引擎，三层结构：

- **数据层** `quant_engine.data`：K 线数据模型、数据源、本地存储、质量检查
- **策略层** `quant_engine.strategy`：策略接口、指标、示例策略
- **回测与评估层** `quant_engine.backtest`：回测引擎、绩效指标、结果导出

没有执行层：不下单，不连接交易账户。

产品说明和层间契约见 [quant-context/product.md](https://github.com/NavaFee/quant-context/blob/main/product.md)，界面见 [quant-web](https://github.com/NavaFee/quant-web)。开发规则见 [AGENTS.md](AGENTS.md)。
