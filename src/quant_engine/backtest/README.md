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
成交价、含费单位成本、调仓分母、成交数量和成交额在使用前须为有限正值；
溢出或下溢至零均抛 `ValueError`，不会记录零数量成交。

`BacktestResult` 有三个 DataFrame，空输入也保持以下列顺序和类型：

| 属性 | 列 | 索引 |
|---|---|---|
| equity | ts, equity, drawdown | bars 原索引 |
| positions | ts, cash, qty | bars 原索引 |
| trades | ts, side, price, qty, fee | RangeIndex |

ts 为该 bar 的 UTC 开盘毫秒 int64；side 为 object 字符串 buy/sell；其余为 float64。
逐根收盘权益 `E=cash+qty×close`，回撤 `E/max(initial_cash,截至当根的权益)−1`。

## 绩效指标

`calculate_metrics(result, initial_cash, interval)` 返回九项指标的 dict；不修改输入。
初始资金须为有限正数（非 bool），周期仅支持 1h/4h/1d。非法表结构、类型、
非有限值、不一致的持仓/成交及数值溢出抛 `ValueError`，不会伪装成 null。
下列 `null` 在 Python 中为 `None`；界面显示“—”。

设初始资金 C、逐根收盘权益 E、总收益 R、年化收益 A、波动 V、回撤 D：

| 指标 | 公式与口径 |
|---|---|
| total_return | R = E末/C − 1 |
| annual_return | A = (E末/C)^(365×86400000/(ts末−ts首)) − 1 |
| annual_volatility | V = std(相邻 E当前/E前期−1, ddof=1) × √P；不添加首根零收益 |
| sharpe | A/V，无风险利率为 0 |
| max_drawdown | D = min(drawdown)，非正数，包含初始资金作为历史峰值 |
| calmar | A/abs(D) |
| win_rate | 完整轮次中净盈利轮数/完整轮数；持平轮次计入分母 |
| profit_factor | 盈利轮次净盈利之和/亏损轮次净亏损绝对值之和 |
| trade_count | 完整平仓轮数，非负整数，区别于成交记录条数 |

P 在 1h/4h/1d 下分别为 8760/2190/365。年化收益历时取首末**收盘估值**时点，
相同周期的开盘标签相减等于估值时点相减；不使用 meta.end − meta.start。
即使有行情缺口，年化收益仍按实际历时计算。

按 positions.qty 从 0 变正开启一轮，再回到 0 才完成；分批买卖都属于同一轮。
净盈亏 = 全部卖出额 − 卖出费 − 全部买入额 − 买入费，滑点已在成交价中。
期末未完成轮次不计入三个交易统计指标，但仍影响权益，trades 仍保留全部成交。

| 情况 | 返回值 |
|---|---|
| 空输入 | 八项数值指标均为 null，trade_count=0 |
| 单根 | 总收益/回撤可计算；年化收益、波动、Sharpe、Calmar 为 null |
| 相邻收益不足两项、任一前期权益为 0、或时间间隔不等于声明周期 | 波动/Sharpe 为 null；不补造行情，其余指标按各自规则计算 |
| V=0 | Sharpe=null |
| D=0 或 A=null | Calmar=null |
| 无完整轮次 | win_rate=null、profit_factor=null、trade_count=0 |
| 无亏损轮次（含全部持平） | profit_factor=null |
| 只有亏损轮次 | win_rate=0、profit_factor=0 |
| 至少三根连续、无成交且权益等于初始资金 | R/A/V/D=0，其余四项比率为 null，trade_count=0 |

## JSON 导出

```python
from quant_engine.backtest import calculate_metrics, export_result

metrics = calculate_metrics(result, config.initial_cash, "1h")
export_result(
    "result.json",
    bars,
    result,
    config,
    strategy="MovingAverageStrategy",
    params={"fast": 5, "slow": 20},
    symbol="BTCUSDT",
    interval="1h",
)
```

结构为 meta、metrics、equity、trades、bars。meta 使用传入的实际策略/配置，
start 是首根开盘 UTC 毫秒，end 是末根开盘加一个周期，覆盖 `[start,end)`。
bars/equity/positions 的时间戳及索引须逐项一致，时间戳升序唯一；不输出 positions。
仅 metrics 可出现 null；params 需为无 null 的 JSON 对象，键为字符串。
禁止 NaN/Infinity。导出前校验和序列化，再在目标目录写临时文件，最后原子替换；
失败时保留已有文件并清理临时文件。空 bars 无法确定范围，拒绝导出。

离线命令和 500 根样例报告见仓库 `examples/README.md`。
