# 策略层

```python
from quant_engine.strategy import MovingAverageParams, MovingAverageStrategy

strategy = MovingAverageStrategy(MovingAverageParams(fast=5, slow=20))
targets = strategy.generate(bars)
```

`Strategy` 子类实现 `_generate(bars) -> pd.Series`，参数用 dataclass 声明。
`generate` 校验六列 bars 契约和 `ts` 升序唯一，再将副本交给子类。
返回值必须是与输入等长同索引的 float64 Series，有限且在 `[0, 1]`；
非法输入/输出抛 `ValueError`，不静默排序、去重或裁剪。空 bars 返回空序列。
参数 `fast`、`slow` 必填，为排除 bool 的正整数，且 `fast < slow`。
快 SMA 严格大于慢 SMA 时仓位为 1，否则为 0；前 `slow - 1` 根为 0。

`sma/ema/rsi(close, period)` 接受有限数值 Series，`atr(bars, period)` 接受 bars。
四者均返回等长同索引 float64，空输入返回空序列，非法周期抛 `ValueError`。
窗口按实际行数计算，时间缺口不补数据；预热为 NaN：

| 指标 | 初始化与后续计算 | 预热行数 |
|---|---|---|
| SMA | 最近 n 个 close 的算术均值 | n−1 |
| EMA | 前 n 个 close 均值起步；E=α×close+(1−α)×E前值，α=2/(n+1) | n−1 |
| RSI | 前 n 个价格变化的涨/跌均值起步，随后 Wilder（α=1/n）；100×均涨/(均涨+均跌) | n |
| ATR | TR=max(high−low, abs(high−前收), abs(low−前收))，首根 TR=high−low；前 n 个 TR 均值起步，随后 Wilder | n−1 |

RSI 仅涨/仅跌/全平分别为 100/0/50。指标初始化可能与其他库默认值不同。
信号表示当根收盘后的目标仓位；下一根开盘成交由回测层处理。
自定义策略需自行保证只读取当前及过去数据；基类只验证输入/输出契约。
`tests/strategy/` 使用仓库样例、手算常量和所有截断前缀验证，且阻止网络访问。
