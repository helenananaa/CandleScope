# #463 同候选原生联合验收：未通过（2026-11-17）

**#463 和 #447 保持开放。** 首屏必需范围的可运行内部队列等待达到 300–417 秒；验收合同明确这类等待计入本地时间，所以冷库每图净就绪 ≤3 秒未通过。精确净耗时尚未完成全部物理请求关键路径归因，不以累计网络耗时相减。A–E 按各自范围已经完成，不因本轮整体失败自动重开。

## 候选和冷库条件

- 产品提交：`88cfeb9e826ac3040bf68952da192d76dd2694fd`，叠加 #469 的 `ae6097aaca24d60cc041257b0a246a5eb31bf8ab`。后续 QA 提交只归档脚本、报告和证据，不能将其冒称为运行时产品提交。
- macOS 26.6.2 / arm64，MacBookAir10,1，Apple M1，16 GiB。保留此前验证过的 Python runtime/plugins；重新构建当前前端、desktop ASAR，覆盖完整当前后端。**不是全新 release/runtime 构建。**
- 验证全部 **1,010 个后端文件**、ASAR 中 **226 个新构建文件**的哈希与严格签名。ASAR SHA256：`8e0738b8302a7a5da34fd77b2d2ec424836b6d09636203b0ca185cacb97c4982`。完整清单见 evidence/candidate。
- 独立新 profile，首次有效需求时 canonical 行情行数 **0**；基础/目标行情与交易所归档缓存无种子。插件 runtime 文件不属于行情种子。仅预置四图 UI 偏好、EMA20/60 与 frontend-JS close 定义，未注入行情、计算结果、替代响应或来源。
- 应用及 sidecar 服务先启动；首次主窗口文档进入四图需求时开始计时，进程启动另记 **25,363ms**。真实 Binance USD-M BTCUSDT，89m / 97m / 101m / 10007m，同时加载，保留原历史和至少128/127要求。
- 仅该进程使用既有 `http://127.0.0.1:7897` 代理，HTTP timeout 8s、预览节流250ms，无全局网络修改，无额外来源订阅。诊断 bootstrap、preview/retention witness 均未开启。

## 首次就绪与本地队列

需求原始时间 `1794902388882ms`（2026-11-17 07:59:48.882 UTC）。表中“候选就绪”仅表示应用 ready 状态、足够历史与图表/EMA/JS 数值观察，不等于所有来源、视口和首次绘制资格完整通过。

| 周期 | 应用/数值候选首次就绪总耗时 | 首屏必需范围的本地队列保守下界 | 净≤3秒 |
| --- | ---: | ---: | --- |
| 89m | 421,323ms | 315,008ms | 未通过 |
| 97m | 421,356ms | 300,403ms | 未通过 |
| 101m | 454,904ms | 327,517ms | 未通过 |
| 10007m | 454,937ms | 416,675ms | 未通过 |

`queue-lower-bound.json` 关联初始 generation=1 的图表 HTTP request_scope、同 owner 的已完成 scheduler 块、首屏最后127根闭合柱内的目标 open 和派发后首次观察到的闭合采用。所选块 `not_eligible_wait_ms=0`；取 `min(eligible ready_queue_ms, started_at_ms-queued_at_ms)`，保守处理墙钟与单调时钟偏差。这是**按明确内部排队不豁免规则认定的失败下界**，不是四图完整精确 `T_net`。

10007m 的例子：sequence95，request_id `15a00d99b7ba4819bf97a8e694e283da`，范围 `1717801620000..1726807920000`，同初始 cell-4 owner，覆盖必需闭合目标 open `1718402040s`。需求后4,252ms入队、420,927ms开始、432,183ms结束，eligible queue 417,033.749ms、quota/ineligible wait 0ms。即使其他网络工作同时进行，内部槽等待也不能整体扣作交易所通信。

冷库观察300秒只是采集检查点，未改成新的总耗时门槛，也未停掉后续修复。该检查点尚未全部就绪，继续记录后才观测到上表状态。实际冷库主流程到重启后最终观察为 **961,068ms**；最后完整退出另有时间戳（08:15:53.220 UTC）。这个数包含十分钟、操作及重启，不是“首次就绪耗时”。精确每图外部阻塞归因、完整阶段/字节/写入量账本仍未核销；不将 cumulative fetch 数值相减取得通过。

## 数值、持续更新和生命周期

| 检查 | 实际结果和边界 |
| --- | --- |
| 闭合目标来源数值 | 独立 Python 对实际 canonical 原生1m，或 UTC 1d/1h/15m/1m 覆盖归约；89m **221**、97m **203**、101m **195**、10007m **128**，共 **747根**，OHLCV及增强九字段/缺失性通过，未覆盖0、差异0。不是形成柱或当前时效证明。 |
| EMA20/60、JS close | 对图表窗口独立重算；EMA绝对误差≤1e-7，JS逐点一致，未放宽标准。冷库早期根数不足和补充轮瞬时异步不一致仍保留为失败。 |
| 冷库十分钟固定采样 | 起始于300秒检查点，初段历史还在补齐；原始 `ten-minute-values=false`。属于未满足完整观察条件，不能称已证明行情冻结或数值算法错误。 |
| 就绪后补充十分钟 | 同产品、**原始冷库运行实际保存的 profile**，没有再次注入UI或数据。逐分钟11点中 **9点四图同时数值一致**；第2、3分钟采到最新柱与异步指标未对齐，原始 `qualified-ten-minute-values=false`。 |
| 连续采集的补充分析 | 每分钟后15秒内取**第一个**严格数值正确且屏幕 C 一致的真实捕获状态；每图11个不同状态，跨度600,003ms。第2、3分钟需等到后续5.35/10.58秒的捕获，其余在固定点。它们是观测对齐间隔，不是测得的单tick传播延迟，不改判原始轮通过。 |
| 输入→WS→图表→屏幕 | 补充11点中89/97/101m WS匹配各10，10007m 11；1m输入匹配各7。只读1m observer 比minute0晚48,012ms启动，有限采样也漏掉部分同值输入。**完整11点链路证据仍不齐全。** |
| 原生隐藏/显示 | 首轮最小化后 `document.visibilityState=visible` 导致脚本过严断言失败，未证明产品隐藏失败。补充轮实际 `BrowserWindow.hide()`，`isVisible=false`持续5秒，show后四图行情/EMA/JS实际改变，**通过这一专项**。产品关闭 backgroundThrottling，文档可见性与原生窗口可见性分别记录。 |
| 周期切换/重建 | 真实原生控制执行1m/5m/15m/1h，重新建立四个质数周期，相关阶段原始检查通过。 |
| 历史锚点/保存退出重启 | 配置、EMA/JS定义、锚点保存及完整退出/重启恢复已观察。原始 `saved-restart=true` 的“fresh” helper只检查末柱变化，**不足以证明当前柱恢复**：最终10007m只有128根闭合柱，没有当前形成柱；不能整体核销此项。补充运行之后确有形成柱更新，但不倒改原始重启资格。 |
| 视口采用 | 冷库未手动平移的10007m出现“回到实时”，屏幕末价/历史视口与当前C明显不同；重启后10007m C=67,251.60，其他图约64,580.10。截图保留，关联 #446/#449 继续归因，未证明具体根因。 |
| 修订/恢复日志 | 继续存在来源修订、mixed/native acquisition、recovery binding、indicator generation拒绝；保留日志，不能用同类堆栈数代替独立根因或将全部异常归为E未完成。更宽D/E恢复矩阵未全部核销。 |

来源核对使用 `math.fsum`；OHLC/trades精确比较，加法字段允许 `max(1e-8,4*epsilon*scale)` 的浮点误差。读的是进程退出后的真实输入；独立闭合核对不冒充实时逐tick来源修订证明。表中10007m128根全为闭合，明确不算当前柱恢复成功。

## 资源、网络与测试

| 运行 | 所属进程RSS峰值（含共享页） | 累计观察CPU | physical footprint |
| --- | ---: | ---: | ---: |
| 冷库+操作+重启 | 1.788 GiB / 最多12进程 | 728.92s | 冷观察1,577,597,568B；十分钟后1,808,843,136B |
| 同profile就绪后补充 | 1.915 GiB / 最多12进程 | 513.51s | 结束1,712,504,832B |

所有 footprint 工具回执无errors；所属应用/sidecar进程完整退出，再检查未发现该候选残留。没有相同条件前后对照，不声明资源收益。事件循环延迟与精确逐tick延迟仍未完成全矩阵资格。

浏览器本地API响应分别2,797/713个，记录均为HTTP200；另有14/4个ERR_ABORTED请求，保留原始记录，不能等同于交易所请求全成功。sidecar日志另有真实网络断连、超时、归档枚举失败、传输不完整以及 `uvloop.loop.Handle.when` 异常。日志覆盖共享profile各次启动；堆栈出现次数不是独立缺陷数，回放能力探测也不是本次K线依赖的同义词。只读1m observer末尾4个连接错误在完整退出期间，完整原始时间戳保留。

验收准备发现 desktop 原生策略存储 API 未允许当前workspace-v9 key。本候选补齐allowlist，并增加真实文件保存/重新加载回归。修复前新用例重现 `Unsupported strategy storage key`；修复后通过。普通workspace目前走IndexedDB，**没有证据将此API缺陷认定为此前所有指标丢失的根因**。

- Desktop **138 tests passed**，frontend typecheck通过，当前Vite build通过（29.71s）。该产品改动仅desktop allowlist与回归；继承 #462 的后端专项记录，未把旧439项重新命名成本轮新跑结果。
- 原始第一次补充运行因已填充profile inventory超过child_process缓冲区而 **ENOBUFS**，尚未进入验收；保留失败driver/log。第二次跳过非冷轮的冷库inventory，正常执行完成。
- 冷库UI init script在沙箱子文档产生10个localStorage访问拒绝，原始errors保留；补充轮无init script、该errors为空。
- 原始driver回执、失败flag、截图及时间线不修改。脚本中部分helper的通过含义较窄，以上独立解释优先；不能将若干局部true相加成联合通过。

## 证据和复核

[`result.json`](result.json) 为简要机器判定。[`evidence/index.json`](evidence/index.json) 记录原文件/归档SHA256、大小；[`evidence/SHA256SUMS`](evidence/SHA256SUMS)覆盖全部evidence文件。56项归档及解压后原文哈希已全部复核。原始文本使用确定性gzip，PNG直接保存。归档包含候选源码清单、测试/构建日志、UI配置、两轮acceptance/traffic/business frames/timeline/resources/footprint、完整sidecar日志、队列下界、来源核对和补充分析。**不提交应用、runtime、profile数据库或凭据。**

主要原始文件：

- `evidence/native-cold/{acceptance,summary,queue-lower-bound,source-numeric,scheduler-chunks,source-routes}.json.gz`
- `evidence/native-cold/{acceptance-timeline,business-frames,resource-samples}.jsonl.gz`、`traffic.json.gz`和截图。
- `evidence/native-continuation-2/{acceptance,summary,steady-analysis}.json.gz`与基础输入observer、timeline、业务帧、资源、截图。
- `evidence/native-cold/profile/logs/backend-sidecar.log.gz`：原profile多次启动共享日志，不能按目录名假定只含冷库。
- 执行过的 `native.mjs` / `continue-native.mjs` 与回执中的driverSha256一致；`continue-startup-failed.mjs`保留ENOBUFS失败版本。

复核解压至对应本地output目录后，`check-queue-bound.py`重建队列下界，`analyze-steady.py`重建补充分析。`check-sources.py`需本地保留的原profile只读数据库；公开逐目标来源recipe与核对结果，但没有发布整个数据库。`summarize.py`验证当前本地包文件/ASAR/签名、按app PID区分重启后归零的scheduler序号，并保留失败状态。冷轮203条、补充142条派发回执，各所属进程序号无缺口。

后续优先定位**首屏关键范围在可运行队列中的长等待/工作量**，然后补齐10007m视口/重启当前柱和完整11点输入→发布→WS→窗口证据。继续使用现有scheduler/coordinator/source/DataManager/前端owner；不另建下载器，不放宽3秒或历史/数值合同。本次验收完成并给出失败结论，#463本身尚未达到关闭条件。
