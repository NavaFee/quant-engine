# 行情数据层

安装项目后运行：

```sh
python -m quant_engine.data download --symbol BTCUSDT --interval 1h \
  --start 2024-01-01 --end 2024-02-01 --root ./market-data
```

支持 BTCUSDT、ETHUSDT，以及 1h、4h、1d；仅请求 Binance 行情专用公开域名 `https://data-api.binance.vision/api/v3/klines`。每页最多 1000 根，游标按本页最大开盘时间加周期推进。单次请求超时 10 秒，连接错误、超时、HTTP 429/5xx 最多重试两次，分别等待 1 秒、2 秒；其他 HTTP 错误和无效响应直接失败。

日期/无时区 ISO 时间按 UTC 解释，带时区偏移的时间转换为 UTC，精度最多到毫秒。范围始终按**开盘时间**取 `[start, end)`，不要求边界对齐周期；只返回下载开始时已收盘的 K 线。未来时间不作为质量缺口。失败返回非零退出码，完整下载成功后才写入。缺口等质量问题会报告，但不补造 K 线，也不阻止保存其余有效数据。

stdout 为 JSON：`saved` 是本次写入的唯一时间戳数量（包含更新，并非新增行数或整个文件行数），`path` 是目标文件，`quality` 是清洗前的质量报告。空下载的 `saved=0`；不会新建文件，也不会覆盖旧文件。

```python
from quant_engine.data import BinanceSource, ParquetStore, check_quality

source = BinanceSource()
bars = source.fetch("BTCUSDT", "1h", 1704067200000, 1706745600000)
report = source.last_quality  # 原始输入检查结果，排序/去重前生成
store = ParquetStore("./market-data")
store.write("binance", "BTCUSDT", "1h", bars)
bars = store.read("binance", "BTCUSDT", "1h", 1704067200000, 1704153600000)
assert check_quality(bars, "1h").ok
```

`DataSource` 协议包含 `exchange` 和 `fetch(symbol, interval, start_ms, end_ms)`，可用其他实现替换。`BinanceSource` 可注入 `request(url, timeout)`、`now_ms()`、`sleep(seconds)`，用于离线测试。`last_quality` 每次下载前重置；失败时为 `None`。

返回 bars 严格为六列：`ts:int64`，`open/high/low/close/volume:float64`，升序、无重复，无数据时返回同类型空表。`validate_bars` 仅检查列、类型和有限数值；`normalize_bars` 对重复时间戳保留最后一行，再升序排列。输入不被修改。

`check_quality(bars, interval, start_ms=None, end_ms=None)` 检查原始顺序：

- `gaps`：缺失开盘时间范围 `[start_ms, end_ms)` 及 `missing_bars`；给出边界时含首尾缺口。空表有双边界时报告整个缺失范围。
- `duplicates`：时间戳到总出现次数（包含第一次）的映射。
- `out_of_order`：当前时间戳小于前一行的位置，按从零开始的行位置记录，与 DataFrame 索引无关。
- `ok`：上述三项均为空。范围参数仅限制缺口检查；重复与乱序仍检查全部输入。开盘时间必须对齐周期的 UTC 网格；不对齐时抛出 `ValueError`。

文件路径为 `<root>/<exchange>/<symbol>/<interval>/bars.parquet`。`write` 先检查本次原始输入并返回报告，再合并旧文件；同时间戳以本次最后一行更新。同目录临时文件写完后用原子替换发布，序列化/替换失败保留旧文件并清理临时文件。

当前按**单进程写入**设计，不支持同一分区并发写入。读写都会载入整个分区，历史量增大后内存和耗时会增长；原子替换不等同于断电持久性保证。测试使用固定历史样例、网络替身和临时目录；运行 `ruff check .`、`ruff format --check .`、`pytest -q`。
