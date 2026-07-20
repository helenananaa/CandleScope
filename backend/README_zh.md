# CandleScope 后端

[English](README.md)

> CandleScope 的 FastAPI 后端。提供 K 线数据、实时 WebSocket、交易所元数据、指标计算、自定义 Pyne 脚本、proxy/settings 管理、订阅和 storage 修复工具。

## 运行栈

- Python FastAPI app：`app/main.py`
- 核心异步基础设施：`app/core/executors.py`、`app/core/runtime_metrics.py`
- 行情数据 runtime：`app/data_engine/runtime.py`
- 交易所 registry/plugins：`app/exchanges`
- 指标引擎和 Pyne runtime：`app/indicator`
- SQLite K 线存储：`app/data_engine/storage`

## 快速启动

```powershell
.\dev-server.ps1
```

Linux/WSL：

```bash
sh ./dev-server.sh
```

启动脚本会先运行幂等的 `setup.ps1` / `setup.sh`：创建 `backend/.venv`，仅在
requirements 哈希变化时安装依赖，再根据注册表准备所有自动安装的受管插件，完成
锁定 manifest、SHA-256 与宿主探针校验，并用同一个 Python 启动后端。至少成功
setup 一次、依赖和 Release 均已缓存后可传 `-Offline` / `--offline`；
`-SkipManagedPlugins` / `--skip-managed-plugins` 会跳过全部受管插件，保留的
`-SkipPineRuntime` / `--skip-pine-runtime` 只排除 Pine。

默认 API base：

```text
http://127.0.0.1:18080
```

交互式文档：

```text
http://127.0.0.1:18080/docs
```

健康检查：

```bash
curl http://127.0.0.1:18080/health
curl http://127.0.0.1:18080/debug/snapshot
```

## 启动流程

`app/main.py` 会：

1. 启动 event-loop lag 监控。
2. 初始化 SQLite K 线 storage。
3. best-effort 刷新交易所 symbol metadata。
4. 通过 `start_data_engine()` 启动 Data Engine。
5. 将稳定 runtime 句柄挂到 `app.state`。
6. 将 IndicatorEngine 桥接到 DataManager events。

关闭时先停止 lag monitor，再停止 IndicatorEngine，最后关闭 Data Engine runtime。

## API 总览

所有应用 API 挂载在 `/api/v1`。

| 领域 | Endpoints |
|---|---|
| K 线 | `GET /klines/`, `/latest`, `/history`, `/range`, `/history/before`, `/resolve`, `/storage/meta`, `/continuity`, `DELETE /klines/storage` |
| 高级行情 | `GET /market/snapshot`, `GET /market/history` |
| Streams | `WS /stream/klines`, `WS /stream/klines_multi`, `WS /stream/indicators`, `WS /stream/prices`, `WS /stream/market` |
| Indicators | `GET /indicators/registry`, presets, custom CRUD, Pyne security, diagnostics, `POST /indicators/compute` |
| Exchanges | `GET /exchanges/`, `GET /exchanges/diagnostics`, `GET /exchanges/{exchange}/capabilities` |
| Symbols | `GET /symbols/exchange-info`, `POST /symbols/exchange-info/refresh` |
| Settings | proxy get/update/test、storage repair、gap scan、storage health、cache limits |
| Subscriptions | list、sync、prices snapshot、get/set/delete symbol tier |

K 线 HTTP/WS 的增强成交量、Delta 与 CVD contribution 契约见 [`docs/KLINE_ORDER_FLOW_CONTRACT_zh.md`](../docs/KLINE_ORDER_FLOW_CONTRACT_zh.md)。

Mark Price、Index Price、Funding Rate、Open Interest 与 Basis 的独立主链、背压和 API 契约见 [`docs/ADVANCED_MARKET_DATA_P1_BACKEND_zh.md`](../docs/ADVANCED_MARKET_DATA_P1_BACKEND_zh.md)。

`/api/v1` 外的系统 endpoints：

- `GET /`
- `GET /health`
- `GET /debug/snapshot`

## Data Engine

后端数据路径：

```text
Exchange WS/REST
        ▼
ingestion
        ▼
bar_aggregator
        ▼
data_manager
        ▼
API / WS / Indicator
```

历史修复路径：

```text
Query/Settings/GapMarker
        ▼
BackfillCoordinator
        ▼
BackfillEngine
        ▼
storage
        ▼
DataManager cache + events
```

详细文档：

- [app/data_engine](app/data_engine/)
- [app/data_engine/ingestion](app/data_engine/ingestion/)
- [app/data_engine/bar_aggregator](app/data_engine/bar_aggregator/)
- [app/data_engine/backfill](app/data_engine/backfill/)
- [app/data_engine/data_manager](app/data_engine/data_manager/)
- [app/data_engine/DATA_FLOW_PATHS_zh.md](app/data_engine/DATA_FLOW_PATHS_zh.md)
- [app/data_engine/ARCHITECTURE_POLISH_ROADMAP_zh.md](app/data_engine/ARCHITECTURE_POLISH_ROADMAP_zh.md)

## 并发模型

后端把 FastAPI event loop 作为编排层。阻塞或重计算任务不会直接跑在 event loop 上，而是进入有边界的基础设施。

```text
FastAPI event loop
  -> 请求 / WebSocket 编排
  -> 不直接跑阻塞 storage query
  -> 不直接跑重指标计算
  -> 不直接等待 Pyne 子进程

Core executors
  -> indicator executor：内置指标 HTTP/range compute
  -> pyne-wait executor：Pyne process wait 和 Pyne snapshot
  -> storage executor：SQLite/DataManager 同步 storage 路径

DataEventBus
  -> emit() 只做过滤和入队
  -> 每个 callback subscriber 一个 bounded queue + worker
  -> iterator subscriber 也使用 bounded queue

BackfillScheduler
  -> priority queue
  -> 单 series single flight
  -> 全局并发上限
  -> token bucket 限流
  -> rate-limit skip 后 delayed drain 自唤醒
```

新增核心模块：

- `app/core/executors.py`：负责专用线程池，以及 executor queue/run 统计。
- `app/core/runtime_metrics.py`：负责 event-loop lag 采样，以及 WebSocket send/heartbeat 聚合指标。

职责边界保持清晰：API 层做编排，DataEventBus 做事件投递，BackfillScheduler 做修复调度，core 模块提供共享运行时基础设施。

## 交易所插件

内置交易所通过 `app.exchanges.registry` 注册：

- Binance
- OKX

插件模板：

- [app/exchanges/plugins/_template](app/exchanges/plugins/_template/)

架构说明：

- [app/exchanges](app/exchanges/)

Exchange plugin 暴露 capabilities、symbol normalization、REST/WS protocol specs、subscription specs、realtime policy、rate limits、pagination policy 和 payload normalization。adapter 仅保留为旧调用兼容门面。

长期稳定边界：

- Capability schema v2 新增按市场展开的权威 `channels` 矩阵，描述 realtime/history transport、delivery class、snapshot/delta 与重同步语义、标准化字段可用性、参数、更新间隔、限额、连接模型和已知限制。schema v1 插件仍可加载，其空 channel 矩阵表示“未知”，而不是“不支持”。
- `ExchangeRegistry.register()` 会拒绝当前后端不支持的 plugin API major version 或 capability schema version。
- `GET /api/v1/exchanges/diagnostics` 会返回每个插件的加载状态、protocol class、adapter facade、policy classes 和 capability 覆盖计数。
- `app.exchanges.contracts` 提供可复用契约测试 harness，用于验证 capability 声明、REST specs、WS 连接模型、payload extraction、历史分页、fixture 覆盖和 normalizer 输出 schema。
- 内置 contract fixtures 放在 `tests/fixtures/exchanges/`；新增交易所应先补 fixture，再接入 runtime。
- 外部插件可通过 `CANDLESCOPE_EXCHANGE_PLUGINS=module.path,module.path:factory` 显式加载。内置插件仍先加载，外部插件加载失败会进入 diagnostics，而不是静默污染 runtime。
- 前端通过 `/api/v1/exchanges/` 消费 interval list、market availability、WS mode 和用户可见 limitations。新增交易所 UI 行为应放在 capabilities 中，而不是写新的前端硬编码分支。

## 指标与脚本解释器

指标文档：

- [app/indicator](app/indicator/)
- [app/indicator/pyne](app/indicator/pyne/)
- [packages/pine-compat-runtime](../packages/pine-compat-runtime/)

内置指标包括 `MA`、`EMA`、`MACD`、`RSI`、`BOLL`、`ATR` 和 `VOL`。

Pyne 脚本通过 `execute_pyne_script()` 执行，默认使用 process executor。Security modes 为 `safe`、`research`、`unsafe`。

后端仍通过 `app.indicator.pyne` 导入 Pyne，但实际实现由本仓库内置的
`packages/pyne-runtime` 包提供。后端会自动加载这个源码目录，所以正常安装
后端依赖即可：

```powershell
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 18080
```

诊断接口会在 `/api/v1/indicators/diagnostics -> pyne.runtimeBackend` 返回
当前实际使用的 runtime 包。

如果临时要联调外部新版 Pyne，可以只在当前 shell 里覆盖源码路径：

```powershell
$env:CANDLESCOPE_PYNE_RUNTIME_SRC = "<path-to-pyne-runtime>\src"
```

受管插件 setup 现在由注册表驱动：`CANDLESCOPE_PLUGINS.json` 选择需要自动准备的
插件锁；通用安装层统一负责 HTTPS 下载、manifest/产物摘要校验、平台选择、原子
缓存、安装 stamp 和独立进程探针。Pine 是第一个接入者，仍与 Pyne 显式并列；其
上游源码固定在 `packages/pine-compat-runtime`，普通用户安装经过锁定和校验的二进制
Release wheel，不需要本地安装 Rust。

可以检查整个受管集合，也保留 Pine-only 兼容命令：

```powershell
.\setup.ps1
.\.venv\Scripts\python.exe scripts\ensure_managed_plugins.py --list
.\.venv\Scripts\python.exe scripts\ensure_managed_plugins.py --check
.\.venv\Scripts\python.exe scripts\ensure_pine_runtime.py --check
```

为保持向后兼容，Pine 继续使用原有
`packages/pine-compat-runtime/CANDLESCOPE_RUNTIME.json` 路径和 schema；通用加载器
会把它适配成受管插件契约，并派生锁定的 wheel 契约与 Pine 探针。它锁定 Release
tag、commit 和 manifest 摘要，受信 manifest 再锁定各平台 wheel 的文件名、大小和
摘要。当前 `python-wheel` 驱动支持已发布的 Windows x86-64 与 manylinux
x86-64 wheel，只写入选定的后端虚拟环境和用户缓存；不支持的平台或 free-threaded
CPython 会明确失败，不安装未锁定的传递依赖，也不会静默退回源码编译。

升级回滚只在旧 canonical/legacy stamp 的插件身份一致、且旧缓存 wheel 仍与 stamp
中的 SHA-256 匹配时可用。新安装或语义探针失败后，setup 会重装这一确定的旧 wheel，
在独立进程复验并恢复 canonical stamp。若回滚材料缺失或不可信，则明确报告并 fail
closed。

以后新增普通 wheel 插件只需增加一份插件锁和一条注册项；通用 `python-import`
探针会校验版本和导入，需要更强语义时再加命名探针，不必复制下载/安装逻辑。完整
扩展说明见 [MANAGED_PLUGINS_zh.md](MANAGED_PLUGINS_zh.md)。

如果手工管理的 Python 环境缺少 wheel，只有 `runtime="pine-compat"` 的请求会以
`PINE_RUNTIME_UNAVAILABLE` 失败，Pyne 不受影响。`GET /api/v1/indicators/runtimes`
和 diagnostics 会返回当前可用性。旧记录和未指定 runtime 的请求继续默认使用
`pyne`。

Pine 的 HTTP/range 批计算仍只接受已闭合 K 线。若已安装的 wheel 提供
`REALTIME_SESSION_SCHEMA_VERSION=1`，指标 WebSocket 会为每个订阅创建受上限保护的
持久子进程会话：历史只播种一次，`BAR_UPDATED` 替换 forming bar，`BAR_CLOSED`
提交闭合状态，backfill/amendment 会销毁旧会话并从权威历史重新播种。该路径保留
Pine 的 `var` 回滚和 `varip` 盘中持久语义；超时、崩溃、协议错位和退订均 fail
closed 并回收子进程。旧 wheel 没有该 ABI 时会自动保持 closed-snapshot 模式。

当前 host 支持 `plot`、受支持样式的 `plotshape`、`hline`、`fill`、`bgcolor`、
`barcolor` 和 alerts，并精确绑定可表示的 `syminfo.*` / `timeframe.*` 图表身份。
`request.*`、strategy、imports、原生 drawing objects、`plotchar`、`plotarrow`、
`plotbar` 和 `plotcandle` 会明确拒绝，不会静默降级。

注意：仓库中的受管安装锁仍固定公开 v0.2.0。只有本地重建或后续发布、且带上述
ABI 的 wheel 会开启 realtime；更新公开 release 与摘要锁之前，一键安装仍按
closed-snapshot 能力运行。

当后续 Release 同时提供完整 Windows/manylinux wheel 矩阵及精确 `manifest.json`
后，维护者可用 `scripts/prepare_pine_runtime_release.py` 渲染下一份锁。该工具既不
构建也不上传；它会校验稳定版本递增、release/source 身份、wheel tags、wheel
metadata、字节数和 SHA-256，再输出启用 `pine-runtime-v2` 安装后探针的候选锁。
只有显式审阅后的 `--write` 才会改动仓库锁文件。

HTTP 指标计算通过专用 executor 隔离：

- 内置指标 HTTP compute 使用 one-shot engine，不会修改全局实时 `IndicatorEngine`。
- Pyne 和 Pine HTTP/range 路径分别通过独立 wait executor 包装 process runtime。
- Pine WebSocket session 命令使用独立 `pine_realtime` executor 和持久 process actor。
- 两条路径都受 `INDICATOR_HTTP_TIMEOUT_SECONDS` 保护。

## 可观测性和压测

诊断信息挂在现有 endpoints 上：

```bash
curl http://127.0.0.1:18080/health
curl http://127.0.0.1:18080/debug/snapshot
curl http://127.0.0.1:18080/api/v1/indicators/diagnostics
curl http://127.0.0.1:18080/api/v1/settings/storage/health
```

重要字段：

| 字段 | 含义 |
|---|---|
| `event_loop_lag` | `/health` 中的 event-loop 调度延迟摘要 |
| `runtime.event_loop_lag` | `/debug/snapshot` 中完整 event-loop lag 快照 |
| `runtime.websocket.heartbeat_delay` | WebSocket heartbeat 调度延迟 |
| `runtime.websocket.send_timeouts` | 按 payload 类型统计的 WS send timeout |
| `executors.*` | 每类 executor 的 submitted/active/pending 和 queue/run timing |
| `event_bus.callback_lag` | callback subscriber queue lag 和 drops |
| `event_bus.queue_lag` | async-iterator subscriber queue lag 和 drops |
| `pineCompat.realtime` | Pine actor active/capacity/timeout/crash/protocol 统计 |
| `ready_chunks` / `running_chunks` / `next_drain_in_ms` | backfill scheduler 状态 |

对运行中的后端执行并发压测：

```bash
cd backend
python scripts/bench_concurrency.py --base-url http://127.0.0.1:18080
```

压测会覆盖 K 线 latest 查询、内置指标 compute、Pyne compute、可见区间 repair 和主要 WebSocket 流，并输出延迟分位数以及压测前后的 diagnostics。

## 配置

环境变量通过 `python-dotenv` 加载。

常用变量：

| 变量 | 用途 |
|---|---|
| `CANDLE_HOST` | 后端 host，默认 `0.0.0.0` |
| `CANDLE_PORT` | 后端端口，默认 `8000` |
| `CANDLE_DATA_DIR` | 数据目录，默认 `backend/data` |
| `KLINES_DB_PATH` | SQLite DB 路径 |
| `CORS_ORIGINS` | 逗号分隔的前端 origins |
| `INGESTION_*` | 实时接入 endpoints、timeout、proxy、WS/fallback 参数 |
| `BACKFILL_*` | 历史修复 intervals、fetch limits、dedup、publish mode |
| `BAR_AGG_*` | 聚合 source mode、alignment、finalization、event throttling |
| `PYNE_*` | Pyne security、executor mode、timeouts、output limits |
| `PINE_*` | Pine executor mode、timeouts、bar/output limits |
| `INDICATOR_HTTP_TIMEOUT_SECONDS` | HTTP 指标计算等待上限 |
| `INDICATOR_THREAD_WORKERS` | 内置指标 executor 大小 |
| `PYNE_HTTP_THREAD_WORKERS` | Pyne wait executor 大小 |
| `PINE_HTTP_THREAD_WORKERS` | Pine wait executor 大小 |
| `PINE_REALTIME_ENABLED` | 是否允许托管原生 Pine realtime session |
| `PINE_REALTIME_COMMAND_TIMEOUT_SECONDS` | 单次 seed/forming/confirmed 命令超时 |
| `PINE_REALTIME_MAX_SESSIONS` | 后端进程允许的 Pine realtime 子进程上限 |
| `PINE_REALTIME_THREAD_WORKERS` | Pine realtime wait executor 大小 |
| `STORAGE_THREAD_WORKERS` | storage executor 大小 |
| `WS_SEND_TIMEOUT_SECONDS` | WebSocket send timeout |
| `EVENT_LOOP_LAG_INTERVAL_SECONDS` | event-loop lag 采样周期 |

proxy settings 也可以通过 API 更新，并持久化到：

```text
DATA_DIR/proxy_settings.json
```

## Storage

K 线 storage 基于 SQLite。内部时间戳使用毫秒。API 图表 bars 的 `BarData.time` 使用秒，以兼容 `lightweight-charts`。

维护 endpoints 可以：

- 从 base intervals 重建自定义周期；
- 扫描并修复缺口；
- 查看 gap ledger health；
- 更新 retention limits。

## 测试

运行所有后端测试：

```bash
cd backend
python -m pytest -q
```

编译检查：

```bash
cd backend
python -m compileall app tests -q
```

聚焦 smoke set：

```bash
cd backend
python -m pytest -q \
  tests/test_klines_api.py \
  tests/test_stream_api.py \
  tests/test_indicator_api.py \
  tests/test_exchanges_api.py \
  tests/test_exchange_plugin_contracts.py \
  tests/test_exchange_registry_plugins.py \
  tests/test_data_engine_phase1_boundaries.py
```

并发压测脚本编译检查：

```bash
cd backend
python -m py_compile scripts/bench_concurrency.py app/core/executors.py app/core/runtime_metrics.py
```
