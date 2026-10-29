# Issue #124：归档下载、保留与验证记录

日期：2026-10-29。分支：`codex/issue-124-archive-import-cleanup`。对照基线：`b84b5e3d514e43fca556613fe107e29d12f7a329`（本次重新 fetch 后的 `origin/main`）。范围为历史归档，不改变交易执行、实时聚合或已退役 Pyne 的契约。

状态：代码及受控集成回归已完成；原生回放资格和真实多公网出口资格尚未取得。此记录不关闭 #124 的全部验收项。

## 已实现的数据流

1. 默认 CCXT 注册入口保留 Binance/OKX 归档工厂。全局开关、OKX 默认关闭和兼容性探测仍有效。
2. 校验文件、HEAD、目录、探测和 ZIP 都使用请求级归档路由租约。pool 模式不会在失败时暗中直连；失败由历史管线按缺口回退 REST。已有新鲜 ZIP 在目录解析和探测前复用，空代理池不阻止有效本地输入。
3. 回放 `OfficialChartArchive` 读取持久代理设置并使用同一下载入口。HTTP 准入在进程内跨事件循环共享，避免回放临时 worker loop 绕过后台下载预算；WS 会话仍由原事件循环管理。
4. 下载后校验、解析完整有效对象，SQLite 同一事务提交行与 `history_archive_import_commits`。清理匹配对象 key、SHA-256、导入版本及 cache generation；进程内 acknowledge 不是删除授权。
5. 清理与 LRU 保护活动对象、物理 blob 租约和 pin；共享哈希仍有引用时保留物理文件。unlink 失败保存重试状态，不回滚已提交的数据。新下载 generation 不使用旧回执，旧缓存没有持久证明不会由导入清理器直接删除。

回放固定的规范化历史对象由回放自身管理，不归普通历史 ZIP GC 所有。ZIP 删除不代表请求没有缺口，也不删除 K 线数据库或历史 QA 材料；缺口仍需后续修复。

## 并发与前台保护

| 资源 | 当前上限或行为 |
| --- | --- |
| 进程归档请求 | 总计 4；后台最多 3，为交互回放留 1 |
| 归档主机 / 共享出口组 | 各最多 2 |
| 代理路线 | ZIP 最多 `max_concurrency - 1`，给 REST 留 1；配置为 1 的路线只承载 REST |
| 请求等待队列 | 64；同主机按前台优先、同优先级 FIFO；冷却的主机不阻塞其他主机 |
| 每个 router 的对象任务 / 延后预取 | 各最多 64，满载走受控失败/REST 或延后 |
| 文件写入、校验、解析 | 独立 2 线程、128 pending 的 archive executor；取消等待已开始的物理操作收尾，再释放文件/路线租约 |

大包不会被拆成多出口拼接；中断换路重新截断临时文件并完整校验。418/429 按主机与共享出口冷却，跨 venue 也不能绕过同一 CDN 的限制；REST 权重和 WS 健康不受归档 CDN 冷却污染。均衡策略用成功大响应的 bytes/s EWMA 比较同等工作量，诊断保留请求数、字节、失败、取消及活动占用。

这些上限限制并发，不是网络带宽整形。正在运行的下载不被抢占；不能据此承诺公网首屏 P95 或 N 倍提速。TUN 也不会因为配置多个代理地址而自动提供多个独立公网出口。

## 策略、配置与回滚

| 配置 | 默认 | 行为 |
| --- | --- | --- |
| `HISTORY_ARCHIVE_ENABLED` | true | 普通历史来源规划总开关；关闭后走既有 REST |
| `OKX_HISTORY_ARCHIVE_ENABLED` | false | OKX 显式启用并探测后才可处理冷包 |
| `INGESTION_ARCHIVE_DOWNLOADS_ENABLED` | true | 单独关闭归档网络；排队任务重新检查开关，已有响应流正常收尾，本地有效 ZIP 可继续复用 |
| `HISTORY_ARCHIVE_CLEANUP_POLICY` | `delete_after_import` | 持久证明匹配且没有使用者/保护时清理 |
| 同上：`retain_for_duration` | 显式选择 | 按持久导入时间计算保留截止点，不因访问或重启延长 |
| `HISTORY_ARCHIVE_RETAIN_SECONDS` | 86400 | 非负整数；只对 duration 策略生效 |
| 同上：`bounded_cache` | 显式选择 | 停止新增导入后清理，仍执行容量 LRU 与已失去引用的 blob 回收 |
| `HISTORY_ARCHIVE_CACHE_MAX_BYTES` | 10 GiB | 未受保护缓存的预算；活动租约/pin/已登记保留期可暂时超过预算 |

保留期保护在清理器识别匹配持久回执后登记到缓存索引。导入前的普通缓存仍受容量预算约束；保留策略不会复原先前已淘汰的输入，也不保证断网重试。必须跨导入阶段保留的输入应使用 pin。默认删除符合本任务接受“重下载换空间”的选择。

新增表/列为增量迁移；关闭新功能不删除回执。已经清理的 ZIP 只能受控重下载，关闭开关不会恢复原文件。对外部修订文件的可再现性不作保证；本地 SHA-256 仅证明本地内容身份，不能冒充来源认证。

## 来源清单与接入计划

能力声明包含 source/provider 与 venue、产品/周期、打包粒度、BarBasis/时区/日历、单位、格式、最终性、缺口、增强字段、验证等级和稳定性。对象 ref 另带覆盖、来源 URL、允许主机及版本信息。`ArchiveSourceRegistry` 允许独立供应商按 venue 显式注册 factory，默认不启用；新增解析器无需修改 SourceRouter 主干。当前每个 venue 选择一个注册来源，不支持自动竞争多个供应商。

| 来源 | 当前支持/资格 | 证据与后续计划 |
| --- | --- | --- |
| Binance public data | 生产 factory 已接通；spot、USD-M、COIN-M 的既有能力和来源 checksum 保留。本次已有真实 USD-M BTCUSDT 月包导入证据 | [官方仓库](https://github.com/binance/binance-public-data)。继续取得相同输入的归档/REST 对照、公网多出口及原生首屏资格；不能把一个月包的成功推广到全部产品 |
| OKX 历史 K 线 | 实现存在；默认关闭，冷包须兼容性探测。受控目录/HEAD/ZIP 与本地复用测试通过，当前线上合同尚未复验 | [官方历史数据页](https://www.okx.com/historical-data)。在隔离资料库完成实际目录、样本解析、REST 对照及恢复，再决定启用；网页合同漂移仍明确禁用 |
| Kraken OHLCVT | 已确认有可行公开数据；尚无生产 adapter。独立七列 seconds/OHLCVT 稀疏 fixture 已通过公共路由、缓存、解析与持久导入 | [官方说明](https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data)。2026-10-29 查阅版本描述分卷全量包；下一步处理分卷拼接、交易对映射、修订与允许主机、单位校验、按需覆盖和重启，再做真实来源资格；fixture 不代表已支持 Kraken |
| Bybit | 继续使用 REST；本次未取得可生产接入的 K 线归档合同 | [官方 Kline API](https://bybit-exchange.github.io/docs/v5/market/kline)。先核验官方批量 K 线目录、格式与历史范围；不能用成交文件或 CCXT 支持代替 K 线归档能力，也不据搜索缺失声称“没有归档” |

未盘点的 venue 保持既有 REST，不自动猜 URL 上线。第三来源 fixture 刻意保留无成交时间空洞和 trades 字段，无服务端 checksum 时标记本地校验等级。

## 验证结果

以下本地原始材料保留在工作树 `output/issue-124/`，没有提交真实用户资料或代理设置。

| 验证 | 结果 | 材料 |
| --- | --- | --- |
| 归档、backfill、CCXT 入口、proxy/WS、replay、行情 runtime 与 executor 相关回归 | 426 passed，6 项既有 FastAPI 弃用警告，86.57 s | `completion/final-regression.log` |
| 最后共享 CDN 跨 venue 限流、排队关闭开关及相关准入/下载回归 | 22 passed，7.05 s；与上行有重叠，不相加为独立用例数 | `completion/final-admission.log` |
| 代理设置前端测试 / lint / build | 3 passed；lint 与 build 通过。build 仍有大 chunk 提示 | `completion/frontend-{tests,lint,build}.log` |
| 真实 aiohttp TLS 源 + 本机 CONNECT 代理 | 物理请求与选定路线一致；坏路线切换、长流中断、共享出口冷却、取消/超时、无直连、热 ZIP 均有覆盖 | `test_history_archive_proxy_pool.py`、`test_history_archive_admission.py` |
| 下载期间前台 REST 与 WS | 受控单次 REST 3.084 ms，下载未结束时收到 10 条 WS 消息；不是公网或原生 P95 | `completion/mixed-traffic.json` |
| 回放工作线程 | 当前持久 pool 设置经坏/好 CONNECT 路线下载；单线程 storage executor 内执行无嵌套死锁；规范化历史重新打开可读 | `test_history_archive_admission.py` |
| 清理恢复 | 持久事务、不同进程 SQLite 检查、共享引用、pin、删除失败重试、新 generation 和保留截止点均有测试 | `test_history_archive_import_cleanup.py` |
| 既有真实 Binance 下载 | 2024-01 USD-M BTCUSDT 1m，44,640 行；1 checksum、1 ZIP、0 REST；1,898,532 字节 ZIP 已清理；新进程 SQLite quick_check 为 ok | `live-binance-c8b44467/result.json` 等。该证据来自本分支较早修复阶段，不是最终补丁的公网双出口复测 |

macOS CI 的 bundled Python 回归已加入全部 `test_history_archive_*.py`、official chart archive 和 executor 用例。CI 状态以 PR 当前 head 的检查为准，本地 build 不能代替打包与启动资格。

## 原生观察与仍未取得的资格

在当前工作树构建的 Vite 产物上运行 Electron 开发壳，使用独立 profile、600 根合成 BTCUSDT 1m 数据和测试专用不可达代理；未修改本机 TUN 或真实 profile。它不是发行包验收。

- 成功启动到主页面，打开回放大厅与创建表单，历史源显示 1 个候选商品。手动 UTC 起点为 2023-11-15 02:00。
- 创建训练返回 `INSTRUMENT_METADATA_UNAVAILABLE`。只有 K 线和本地 catalog 记录仍不足以建立当前准备流程要求的商品身份；本次未绕过该检查。截图：`completion/native/preparation-seeded-metadata-unavailable.png`；sidecar 日志：`completion/native/profile/logs/backend-sidecar.log`。
- 没有进入训练，因此渲染 K 线、播放/步进、保存和原生重启恢复均未通过。前一次隔离启动退出还记录了未关闭 aiohttp session 和 sidecar 退出期限日志，未在此归档改动中将其归因或宣告修复。
- 仍需具备完整商品元数据的隔离原生环境完成训练与重启；完成同文件/同机器的首屏、事件循环、CPU/内存/磁盘及导入耗时比较；用可证明的两条独立公网出口做吞吐/故障切换资格；复验 OKX 在线合同，并按来源逐一取得真实数据资格。

本机 CONNECT 测试无需关闭 TUN，证明的是应用选路和资源管理。真实联网成功不能证明 TUN 后具有独立出口。本 PR 应保持 draft，直到上述与发布有关的边界经过明确评估。
