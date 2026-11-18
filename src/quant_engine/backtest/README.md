# 回测引擎

```python
from quant_engine.backtest import BacktestConfig, run_backtest

result = run_backtest(
    bars, targets, BacktestConfig(initial_cash=1000, fee_bps=10, slippage_bps=20)
)
```

`bars` 遵守数据层契约，ts 升序唯一，open/close 为正值；`targets` 是与 bars
同索引、有限、值在 `[0,1]` 的 float64 Series。输入不修改、不排序、不补缺口；
非法输入抛 `ValueError`。配置冻结，initial_cash 必填且大于 0，两项 bps 默认 0，
取值 `[0,10000)`；配置值须为有限实数，排除 bool。

首根持有全部现金。上一根目标只在下一条实际 bar 的开盘处理；最后一个目标
不成交，期末不强制平仓。分数目标不变时仍检查价格漂移并再平衡。

设开盘价 O、原现金 C、原数量 q、目标 w，f=fee_bps/10000，s=slippage_bps/10000。
买价为 O(1+s)，卖价为 O(1−s)，费用为成交价乘数量再乘 f，买卖均从现金扣。
以原始 O 估值，使成交后的 `q′O/(C′+q′O)=w`：

- 买入数量：`[wC−(1−w)qO] / [(1−w)O+wO(1+s)(1+f)]`。
- 卖出数量：`[(1−w)qO−wC] / [(1−w)O+wO(1−s)(1−f)]`；w=0 时卖出全部。

数量允许小数，无杠杆。仅在相关运算量级的 8 ULP 内消除调仓差值及余额的舍入残差；
实质负余额或非有限计算结果抛 `ValueError`，不靠裁剪掩盖超支。

`BacktestResult` 有三个 DataFrame，空输入也保持以下列顺序和类型：

| 属性 | 列 | 索引 |
|---|---|---|
| equity | ts, equity, drawdown | bars 原索引 |
| positions | ts, cash, qty | bars 原索引 |
| trades | ts, side, price, qty, fee | RangeIndex |

ts 为该 bar 的 UTC 开盘毫秒 int64；side 为 object 字符串 buy/sell；其余为 float64。
逐根收盘权益 `E=cash+qty×close`，回撤 `E/max(initial_cash,截至当根的权益)−1`。
绩效指标和 JSON 导出由后续任务实现。
