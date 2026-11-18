# Binance 历史样例

`binance_btcusdt_1h.json` 是 Binance 现货 BTCUSDT 1h 的 500 根连续、已收盘 K 线，保留公开接口返回的 12 字段原始数组，未修改价格或成交量。测试取前六项构造 bars。

- 开盘时间 UTC 范围：`[2024-01-01T00:00:00Z, 2024-01-21T20:00:00Z)`。
- 首根 `ts=1704067200000`，末根 `ts=1705863600000`。
- 采集日期：2026-11-18；公开源：[Binance market-data-only API](https://github.com/binance/binance-spot-api-docs/blob/master/market_data_only.md)。
- 请求：`GET https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1h&startTime=1704067200000&endTime=1705867199999&limit=500`。
- 采集方式：开发时用标准库 `urllib.request.urlopen(url, timeout=20)` 读取 JSON；断言 500 个开盘时间连续，每根间隔 3,600,000 毫秒；以 UTF-8 JSON 写入，每行一条原始记录。
- 文件 SHA-256：`2764b984c5797f4730cb1bfca7674d23e7ae92dafe2f8a9df6006259061389c3`。

测试不重新采集，也不访问网络。分页和其他周期的边界测试复用本文件的 OHLCV，通过替身调整开盘/收盘时间；这些构造记录不作为真实历史数据交付。所有存储测试写入 pytest 临时目录。
