# Issue #124：原生回放失败恢复复核

日期：2026-10-29。同一工作树与分支，基于 PR #139 的 `66d9f52c` 继续修复。数据和 Electron profile 位于本地 `output/issue-124/completion/native/profile`，600 根 BTCUSDT 1m 数据与商品身份均为有限合成测试输入，不是交易所在线资格证据。

## 根因

上轮的 `INSTRUMENT_METADATA_UNAVAILABLE` 涉及两个阶段，不能统一归因为目录仍然缺失：

1. 首次准备时，测试仅导入了 K 线，没有准备商品身份。回放正确拒绝创建，任务 `2d89b55587e14cbb84afffd79755a047` 在 3 次尝试后进入 `FAILED`。不能从 `BTCUSDT` 字符串或 OHLCV 猜测结算身份，也不应跳过该校验。
2. 之后补充目录并重启，生产 `initialize_exchange_metadata_cache()` 可加载快照，`get_cached_symbol_metadata("binance", "spot", "BTCUSDT")` 正常返回 BTC/USDT 现货身份。但是创建表单从持久草稿恢复了原幂等键，再次 POST 只读回同一个失败任务；它没有调用任务的 retry 接口。数据库的 attempts、revision、updated_ms 均未因那次点击改变，所以旧错误被误认为补齐目录后仍然解析失败。

目录加载不是这次剩余阻塞的原因。缺口位于前端 `prepareReplay()`：保留幂等键是正确的，重新提交已失败任务时还需要明确请求恢复。后端幂等 create 不能变成隐式重试，否则普通查询/重连可能意外重启作业。

## 修复

用户再次提交创建表单时，如果返回的是可重试且未请求取消的 `FAILED` 任务，调用该任务的 `/retry` 一次，再观察其进度。继续沿用原任务 ID 和幂等键，不生成第二条训练。普通轮询不重试；不可重试、已取消和存储阻塞任务保留原处理流程；一次提交也不会在再次失败时无限循环。

前端回归先验证旧实现失败，再验证恢复成功、任务身份不变、不可重试/取消状态不被重新启动，以及重试次数有界。原有重载草稿与已删除训练的测试保留。

同时修复本 PR CI 检出的 ZIP 容量提示没有通过 i18n 的问题：使用统一消息键，30 个语言目录保留技术符号与参数；日语使用“ZIP 同時実行数 ≤ {count}”，满足现有翻译检查，不豁免检查器。

## 验证材料

本地证据目录：`output/issue-124/native-recovery/`。`initial-state.json` 保存原失败任务、目录条目和目录哈希；`before-retry.log` 保存旧实现失败结果。

## 原生播放、保存和整应用重启

运行 macOS Electron 原生开发壳、生产 Vite bundle 和本工作树 Python sidecar。构建对应 `adf2b0de`；随后 `7ba96e94` 只修正日语提示，不改变本次中文回放流程。`build-identity.json` 保存构建身份及资源哈希。没有构建或冒充发行包。

隔离 profile 继续使用相同数据、目录和测试专用不可达代理；没有修改 TUN、系统代理或真实用户 profile。重启没有重新导入 K 线、重写商品身份或修改回放数据库；所有回放操作均通过原生 UI，数据库只读检查由独立 Python 进程执行。

| 步骤 | 直接观察 | 证据 |
| --- | --- | --- |
| 原失败任务重试 | 原任务调用 `/retry` 后变为 READY；创建 run `prepared-2d89b55587e14cbb84afffd79755a047`，没有重复创建同一训练。02:00:00，2 根 K 线，PAUSED，Controller 本页 | `01-entered-replay.png`、sidecar 请求日志 |
| 原任务播放到终点并重新打开 | 最初 10 分钟窗口播放至 source sequence 10；中途验收进程被中断，后续重新启动应用，通过大厅打开同一 run，02:09:59，12 根 K 线，ENDED；该段不冒充主动暂停验证 | `after-interruption-db.json`、`02-ended-restored.{png,ax.txt}` |
| 新建主动保存恢复用例 | 同一 600 根输入，UTC 起点 2023-11-15 02:00，预热 2 根，前向窗口 3,600,000 ms。run `prepared-60ba22ac348a4e64aa02238fcdd1ade6`，session `4325e449e08047d1b5dd4de53429a041` | 下列连续 UI 与数据库证据 |
| 播放 | PLAYING；虚拟时间推进到 02:13:59，显示 16 根 K 线 | `03-playing.{png,ax.txt}` |
| 暂停 | PAUSED；02:17:59，20 根 K 线；最后一根 O 30006.75 / H 30018.75 / L 29994.75 / C 30003.75 / V 15 | `04-paused.{png,ax.txt}` |
| 主动保存 | 点击“存档大厅”成功返回；该训练显示已暂停、进度 #18、1 个活动轨道、权益 10,000 USDT | `05-saved-hall.png`、`before-clean-restart.json` |
| 退出整个应用并重新启动 | 原 Electron launcher 退出码 0，旧 sidecar 结束；用同一 profile 启动新进程。在大厅继续同一训练，恢复 PAUSED、02:17:59、20 根、同一 OHLCV 与 Controller 本页 | `06-restored-paused.{png,ax.txt}`、`after-clean-restart.json` |
| 恢复后继续推进 | 点击“下一根 1m”后为 02:18:59、21 根；再次保存后大厅进度 #19，数据库 source sequence 19 | `07-resumed-step.{png,ax.txt}`、`final-db.json` |

独立 SQLite `quick_check` 为 `ok`。前后 run/session ID、暂停状态、source sequence、虚拟时间、revision、权益、轨道及 session 内容相同；checkpoint 的 state hash 和 payload SHA-256 相同。退出时额外写入 checkpoint、刷新保存时间，准备任务 revision 也有变化，因此没有要求所有管理字段逐字相同。对照结果见 `restart-verification.json` 和 `restart-diff.json`。

本轮没有下单，不能据此宣称订单或持仓恢复验收。本次要求的播放、暂停、保存、整应用重启恢复及恢复后步进均已取得直接证据。

## 自动化检查与边界

- 前端 API、回放大厅及代理面板相关回归：57 passed；旧代码先失败，修复后通过。材料 `frontend-targeted.log`。
- 日语修正后完整 i18n 用例：40 passed；静态 i18n 检查通过，30 locales / 5,144 keys / 909 source files。材料 `i18n-tests-final.log`、`i18n-final.log`。
- 针对改动文件的 ESLint 与 Vite build 通过，保留既有大 chunk 提示。材料 `lint-targeted.log`、`build.log`。
- 本地应用 tsconfig 检查完成；完整 typecheck 的工具配置阶段和全量 lint 因长时间主机争用被主动停止，不能写成本地全量通过。CI `adf2b0de` 的 x64 日志已实际通过 typecheck、lint，再进入 4,434 项前端测试；唯一失败为已由 `7ba96e94` 修复的日语提示断言（4,433 passed）。这不是最终 head 的完整 CI 通过声明。
- 本轮后端集成首轮 82 passed / 2 failed：一个 5 秒用例超时，一个测试在 `LOCAL_OFFLINE` 导入后才切换 LIVE 导致目标符号不存在。隔离 LIVE 环境单独重跑这两项均通过（2 passed）；保留首轮失败而不改写为全套一次通过。材料 `backend-regression.log`、`backend-recheck.log`。上一阶段 426 项与最后 22 项结果见原归档报告，不能与这些有重叠的计数相加。
- 本次冷启动等待上限仅在验收 launcher 中扩到 300 秒，生产默认值未改；此前 90 秒启动超时截图仍保留。本轮不能据此声称默认冷启动性能合格。
- 原生退出仍记录 `desktop shutdown deadline exceeded; forcing sidecar exit`。日志显示回放较早历史请求在退出时等待准备数据，并被 shutdown timeout 取消；应用随后完成退出，保存进度成功恢复。这是保留的退出生命周期问题，本次修复没有解决它，也不将这轮称为完全优雅退出。恢复页还显示“正在加载更早的回放数据…”，有限离线 fixture 不覆盖这项历史扩展资格；它没有阻止已恢复窗口的播放/步进。
- 发行包、真实多公网出口、OKX 在线合同、其他来源及公网性能资格仍独立待验。PR #139 保持 draft。
