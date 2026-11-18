# 离线双均线回测报告

从仓库根目录运行，先按根目录 README 安装开发依赖并激活虚拟环境：

```sh
python -m quant_engine.backtest \
  --input tests/fixtures/binance_btcusdt_1h.json \
  --symbol BTCUSDT --interval 1h --fast 5 --slow 20 \
  --initial-cash 10000 --fee-bps 10 --slippage-bps 20 \
  --output examples/result.json
```

命令全程离线，读取现有 Binance 格式样例，运行 MovingAverageStrategy 和既有回测引擎，
输出严格 JSON，成功退出码 0；输入或导出失败时非零退出，并向 stderr 说明原因。
输入需为 12 列 Binance K 线 JSON 数组，时间匹配声明周期；不排序或填补缺口。
输入文件自身不含交易对标识，`--symbol` 应与文件来源一致。

`result.json` 含 500 根 BTCUSDT 1h bars 与 500 个权益点，可由 quant-web 读取；
时间范围是 UTC `2024-01-01T00:00:00Z` 至 `2024-01-21T20:00:00Z`（右端不含）。
重复运行后解析内容一致，无随机数或生成时间字段。CLI 集成测试会核对已提交样例。

交易次数统计完整平仓轮数；未平仓部分仍出现在资金曲线与成交列表。
八项数值指标允许 null，表示不可计算，界面显示“—”；详见
`src/quant_engine/backtest/README.md` 的公式与边界表；共享契约见 quant-context 的 product.md。
