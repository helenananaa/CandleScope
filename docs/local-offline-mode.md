# CandleScope 本地离线模式

本地离线模式是独立的启动 profile，不是直播页面上的临时开关。进程启动后只加载本地数据 API；不会创建交易所适配器、DataEngine、Backfill、Replay、行情 WebSocket、价格轮询、插件 host 或在线目录刷新。

## 启动

先准备项目依赖：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

cd ..\frontend
npm install
```

然后从仓库根目录启动：

```powershell
.\start-local-offline.ps1
```

默认页面为 `http://127.0.0.1:15173/local.html`，本地资料库存放在 `backend/data/local-data`。也可以指定独立目录：

```powershell
.\start-local-offline.ps1 -DataDir "D:\CandleScopeData\local-data"
```

手动启动时，必须在启动后端前选定 profile：

```powershell
$env:CANDLESCOPE_RUNTIME_MODE = "LOCAL_OFFLINE"
$env:CANDLESCOPE_LOCAL_DATA_DIR = "D:\CandleScopeData\local-data"
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 18080
```

受支持的启动脚本和默认配置固定监听 loopback；不要用 Uvicorn CLI 参数把本地 profile 覆盖为 `0.0.0.0`。若要切回直播模式，需要停止进程后以 `LIVE` profile 重新启动，不能在页面中热切换。

## CSV 合同

第一阶段支持一份 CSV 对应一个商品和一个周期。默认列名：

```csv
time,open,high,low,close,volume
1704067200000,42000,42140,41880,42080,125.4
1704067260000,42080,42210,42020,42190,98.2
```

导入页需要用户确认：

- 商品标识，例如 `BTC-USDT`；
- 周期，例如 `1m`、`5m`、`1h`、`1d`、`1w` 或 `1M`；
- 时间格式：Unix 秒、Unix 毫秒或 ISO 时间；
- 无时区 ISO 时间使用的 IANA 时区，例如 `UTC`、`Asia/Shanghai`。

导入器会拒绝重复或乱序时间、非有限数值、负成交量、未对齐周期的时间戳，以及不满足 OHLC 关系的行。源数据中的缺口会写入 `excluded_ranges`，视为数据集的终止事实；本地模式不会尝试联网修复或静默填充。

后端也支持可选字段映射：`quote_volume`、`trades`、`taker_buy_base`、`taker_buy_quote`。当前页面只暴露标准 OHLCV 列；自定义列映射可直接使用 `/api/v1/local/imports/csv` API。

## 存储与可复现性

每次成功导入发布为不可变修订：

```text
local-data/
  local-<dataset-id>/
    current.json
    <sha256-data-epoch>/
      manifest.json
      bars.sqlite
      quality-report.json
      import-receipt.json
```

`data_epoch` 由规范化后的商品、周期、K 线和排除区间计算。导入先写入 staging，完成 SQLite `quick_check`、质量报告和 SHA-256 后再原子发布，因此失败导入不会成为可见数据集。

## 离线边界

- 本地 profile 只注册 `/api/v1/local/*`、健康检查和 API 文档；直播、回放和插件 API 不加载，并由 profile middleware 拒绝。
- Python 进程安装 loopback-only 网络 guard，在 DNS、TCP connect 和 UDP send 边界阻断非 loopback 目标。
- `local.html` 使用 `LocalKlineApi` 和静态 `SeriesWindowStore`，没有 WebSocket URL，也没有定时轮询。
- 该 guard 是应用内的 fail-closed 防线，不等同于操作系统防火墙或容器网络隔离。需要更高保证时，应同时使用 Windows 防火墙规则或断网环境。

## 第一阶段范围

已支持 CSV 导入、严格校验、不可变版本、数据集列表、静态 K 线、左侧历史分页、缺口披露和本地绘图存储基础。当前暂不支持 Excel/Parquet、一个数据集内多商品或多周期、重采样、直播功能、本地指标管理 UI、插件和回放。后续功能必须继续走本地 profile 的显式能力白名单，不能复用直播 fallback。
