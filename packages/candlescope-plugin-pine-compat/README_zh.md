# CandleScope Pine Compatibility 插件

本包把独立发布的
[`pine-compat-runtime`](https://github.com/helenananaa/pine-compat-runtime) wheel
桥接到公开的 `candlescope.script-runtime/1` SDK。包内只有适配代码，不包含 Pine
引擎源码快照，也不导入 CandleScope 后端私有模块。

适配器 `0.4.0` 使用本地验收过的 `pine-compat-runtime==0.3.3` Windows wheel；
`release/release-lock.json` 锁定引擎、SDK 和 bridge 的内容哈希，旧发布锁
保存在 `release-lock.0.2.0.json`、`release-lock.0.3.0.json`、`release-lock.0.3.1.json` 和 `release-lock.0.3.2*.json`。
当前锁文件对应未发布的 0.4.0 候选包；Linux/macOS 的离线安装验收由 PR CI 执行。
分析/输出/增量协议为 6/9/4。此次验收不代表公开发布或与 TradingView 完全等价。
原生线段、标签、框、多段线、线间填充、表格、字符/箭头、蜡烛及渐变通过图表
primitive 显示，支持坐标投影、缩放和清空。字体、标签外形及表格自动排版仍有
近似处理，不承诺像素一致。资源超限以明确诊断返回。

支持历史批计算，以及已确认历史末尾的一根 forming bar。WebSocket 订阅通过
`options.pineSessionId` 保留原生会话，支持替换、收盘确认和追加；传输仍返回完整
Render IR 快照。HTTP 计算保持独立。分析结果的 `meta.hostRequirements` 暴露
引擎的宿主需求清单。宿主依据编译后的 HIR 发现请求上下文，包括库依赖及嵌套
请求；动态符号/周期要求显式数据，无法可靠推导预热长度时要求 `requestWarmupBars`。
缺失或有缺口的数据不会静默执行，辅助订阅在依赖改变或取消订阅时释放。

每个 sidecar 保留 8 个热会话，并在
`%LOCALAPPDATA%/CandleScope/pine/observations-v1.sqlite3` 保存观察日志。
可用 `CANDLESCOPE_PINE_JOURNAL` 覆盖路径。淘汰、进程重启和重叠滑动窗口会从
已记录的观察恢复 `varip`，重连不会把同一观察重复执行。源码、参数、已确认历史、
时钟或重置标识改变时重启状态，并在界面提示；渲染失败不提交观察。
上限为 512 个日志、合计 256 MiB、每会话 100000 根根图历史，超限明确失败。
日志可在插件停止后手动清理；断线期间未观察到的 tick 无法补回。

指标支持请求数据、imports、OHLCV/衍生价格字段的 `input.source` 选择、显式时钟
及市场元数据。策略通过独立原生或宿主撮合入口执行，使用单独注册表。
宿主撮合采用显式执行计划和持久观察会话 `pine-external/6`，账户和成交仍由
CandleScope 决定。固定计算窗口的输出会对齐到冻结的图表时间线；需要账户反馈
探索及重新确定窗口的动态情况仍明确拒绝。

指标编辑器中的“Pine 市场输入”接受 JSON，保存到 `params.__pineHost`；
IPC 使用 `options.pineHost`，策略使用冻结的 `host_inputs`。交易所提供的价格步长、
数量步长、最小量、乘数及计价币自动填充。逆向合约明确拒绝；缺失元数据时仍有
引擎的合成默认值，结果以 `symbolMetadataSource` 标注，依赖这些字段时应显式提供。
例如：

```json
{"chartMetadata":{"minMove":1,"priceScale":100,"pointValue":1,"quantityStep":"0.001","minContract":"0.001","currency":"USDT"},"requestWarmupBars":{"BINANCE:ETHUSDT:60":100}}
```

指标还可提供 `libraries`（导入路径到源码）和 `contexts`（symbol、Pine timeframe、
bars、可选 forming）。OHLCV 时间为秒，`executionTimes` 为毫秒且每根主图 bar 一个。
历史 `timenow` 默认使用宿主收盘评估时钟，实时使用当前观察时钟；这些不是历史 tick
记录。`symbolMetadata`、`currencyRates`、`barCalendars`、`sessionWindows` 遵循
Pine 0.3.3 公开协议。汇率、交易日历和会话窗口需要显式提供，尚无自动下载服务。
宿主撮合自行拥有时钟和账户窗口，拒绝额外的 `executionTimes`/`sessionWindows`。

编辑器可勾选“确认后发送 Pine 提醒到通知中心”。自动生成的 Pine 规则可在提醒页
设置渠道、暂停、冷却及次数；历史、预览、HTTP 计算和历史重放不发送通知。
事件持久化去重，需要图表持续订阅。改变规则目标或表达式会断开原 Pine 提醒来源。

本地运行：

```powershell
python -m pip install --no-index --find-links <候选wheel目录> candlescope-plugin-pine-compat==0.4.0
python -m candlescope_plugin_pine_compat
```

构建器接受三个 wheel：本 bridge、SDK `0.2.0` 和锁定的 Pine 引擎 wheel。
构建候选包时传入 `--lock release/release-lock.candidate.json`，以及三次 `--wheel`
和一个 `--output`。候选包须通过安装器和真实 sidecar 验证后再启用。

## 回测安装边界

冻结 bridge、SDK 和引擎 wheel 并验收后，通过
`install_native_strategy_plugins.py --runtime pine --activate` 仅升级 Pine 回测，
保留 Pyne 注册项。安装指标 CSPKG 不会自动注册原生策略回测。

本地验收版可在指标注册表旁的 `first-party-local-overrides.json` 中锁定版本和
外层 bundle SHA-256。启动时重新验证已安装包，避免被公开目录中的旧版本覆盖；
不匹配时明确失败，不会尝试下载未发布版本。回退时恢复安装器的前次激活并移除
对应 Pine 锁；策略安装收据另存 `previous-native-registry.json`。完整字段见
[英文说明](README.md)。
