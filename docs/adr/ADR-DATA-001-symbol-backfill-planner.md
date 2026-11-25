# ADR-DATA-001：每个品种一个历史回补规划器——大自定义周期首次加载

- 状态：Proposed（等待用户审阅 §11 的待决定项；审阅前不开始主体实现）
- 日期：2026-11-25
- 基线：`main@861bf22db`（1.0.0 候选）
- 关联：#572（1.1 第一项）、#447、#463；快修 PR #619（forming 种子不再每次轮询重复提交回补）
- 参考，不合并：搁置栈 #436、#464–#467、#469、#471、#473、#474、#477、#508、#511（取用清单见 §9）。
  #468、#470、#472、#475、#476 编号落在这个范围内，但不是性能栈。
- 不在本 ADR 内：B-445（从 #436 移植 EMA 增量），另行处理。

## 1. 背景

### 1.1 RC4 测量（macOS 安装包，同一网络）

| 场景 | 结果 |
| --- | --- |
| Binance USD-M BTCUSDT 89m 冷加载 | 约 325 秒收敛，前约 2 分钟一根都没有 |
| 同上，关闭后重开（热） | 约 19 秒 |
| Binance spot 90s | 196 秒，期间反复冲突 |
| OKX spot / perp 89m | 4 分钟时仍未就绪 |
| 1m + 89m 分屏，向左翻页 | 每页超过 120 秒 |

1.0 的发布说明已经写明：大自定义周期第一次加载慢，以后改进。

### 1.2 现在一张 89m 图打开后发生什么

以 RC 冷加载 89m 的 sidecar 日志为例（`output/rc/0be80267f/runs/cold-89m-binance-futures`，5 分 10 秒）。
同一个品种同时有下面这些需求，各自进入回补协调器，互相不知道对方：

| 来源 | 调用 | 进入调度器的 lane | RC 次数 |
| --- | --- | --- | --- |
| 首屏历史 `GET /klines/history?count_back=221` | `custom_query` 找缺口 → `project_base_repair_to_target` | `…:BTCUSDT:89m`（`derived_from=1m`） | 19 |
| 视口范围 `GET /klines/range?repair=async` | 同上 | 同上 | 182 |
| 最新 `GET /klines/latest`（约每秒一次） | `ensure_stream` → `seed_if_needed` → 当前 89m 桶的 1m 组件 | `…:BTCUSDT:1m` | 208 |
| 自定义周期尾部 `warm_start_custom_tail` | 每个目标生命周期一次，最近 6 小时 | `…:89m` | 1 |
| 实时流断档 `_handle_ingestion_gap` | WS 掉线后的 1m 缺口 | `…:1m` | 若干 |
| 另一张图（1m 图、向左翻页） | 各自的 history/range/before | 各自的 lane | 场景而定 |

调度器每个 `(exchange, market, symbol, interval)` 一条 lane。89m 的历史和 1m 的种子在不同 lane 上同时跑，
但写的是同一张 1m 表。每次运行各自建 acquisition、各自规划、各自写入并校验，结果是：

- 两次 89m 运行都是 PARTIAL：一次 81 秒取了 4,320 根只写入 2,224 根，一次 48 秒取了 16,552 根只写入 11,520 根。
  失败原因都是 `StaleAcquisition: warmup change receipts do not cover the acquisition`
  （`storage/warmup_revision_fence.py`）：运行期间别的写入者让 1m 序列变了，而块变更回执只保留最近
  1,024 个修订（`revisions.BLOCK_CHANGE_WINDOW`），长时间的获取无法证明自己的范围没被动过。
- 5 分钟后，当前桶仍然只有 2/84 根可信的 1m 组件。种子提交了 208 次，没有一次把它补齐。

### 1.3 两个 RC 原因，已复现

**原因一：归档优先，失败后才退回 REST。**
`HistoricalSourceRouter.prepare` 只要一个任务需要至少 `HISTORY_ARCHIVE_MIN_REST_PAGES`（3）页 REST，就选归档对象，
不看这个网络上归档主机是否可用。`HistoricalFetcher._fetch_routed_task` 先等归档结果，失败了才为该对象的范围发 REST。
归档请求的总预算是 60 秒（`archive_cache` → `archive_transport.request_archive`）。失败只按对象记负缓存
（`_remember_completed_failure`），不按主机记，所以下一个对象还要再等一次完整预算。

- RC 日志：同一个日度对象 `daily:2026-11-18` 报了 5 次 `rest_fallback … archive request exceeded its total time budget`，
  前两次相隔约 60 秒；同期 S3 的 TLS 握手超过 60 秒；REST 自己也受 `exchangeInfo` 超时影响（40 行，
  CCXT 先要加载 markets，`Page fetch error (attempt 1/4)`）。
- 复现：`output/backfill-planner-1.1/probes/archive_first_probe.py`（真实 router 与 fetcher，归档主机卡住 N 秒后报预算错误，
  REST 立即应答，3,001 根 1m）。REST 开始时间与归档开始时间之差：

  | 归档卡住 | 0 秒 | 2 秒 | 5 秒 | 10 秒 |
  | --- | --- | --- | --- | --- |
  | REST 等待 | 0.002 秒 | 2.003 秒 | 5.004 秒 | 10.004 秒 |

  即 REST 一定排在归档失败之后；在 RC 网络上就是 60 秒。

**原因二：forming 桶的种子反复触发底层回补。**
`/klines/latest` 每秒一次调用 `ensure_stream`，每次都重跑 `_seed_custom_interval`。只要当前桶缺可信 1m，
就再提交一次 `[桶开始, now]` 的 1m 回补。RC 日志里 208 次种子与 208 次 `/klines/latest` 一一对应。

- 复现：`output/backfill-planner-1.1/probes/forming_seed_probe.py`（真实 `BackfillCoordinator` 与 warm-start，
  89m 历史和第一次种子回补在途，模拟 300 次每秒轮询）：main 上 300 次提交、调度器去重 294 次。
- 已单独修复：PR #619。同一目标桶、同一目标生命周期只提交一次；只有新收盘且仍缺的组件、更紧急的需求、
  或 60 秒后重新武装才再提交。300 次 → 6 次，去重 294 → 0。它只去掉空转，不会让当前桶更早补齐：
  1m 的种子回补和 89m 的历史仍然是两个互相竞争的需求，这正是本 ADR 要解决的。

### 1.4 已经试过的"按交易对统一"

搁置栈 #508 做过一次 FamilyFill（`docs/architecture/COLD_FAMILY_FILL_zh.md`，未合入）：在现有 chunk 流程之上，
先统一规划一个交易对的源数据，再门控 chunk。离线基准（`net_zero`，无网络）结论：首屏明显提前
（10007m 4.3 秒 vs 13.1 秒），但四图全部就绪更慢（36.6 秒 vs 25.4 秒），CPU 多约 40%。原因是每个分片都是一次完整的
引擎运行（准入、校验捕获、路由、写入、ledger、缓存回读），统一规划在图自己的运行之外又加了约 100 次。

两点教训直接进入本设计：

1. 统一规划必须**替换**各图各自的获取，而不是叠在上面再加一层门控。
2. 分片的固定开销要低：一个品种的分片在同一个执行器里跑，而不是每片一次完整的 `BackfillEngine.run`。

另外，那次测量是无网络的 CPU 基准。RC 暴露的是网络上的问题：路线选择、请求排队、长时间获取和实时写入冲突。
本设计以 RC 场景为准。

## 2. 决定

每个 `(exchange, market_type, symbol, identity)` 一个 **SymbolHistoryPlanner**（下称规划器），运行在事件循环上，
拥有这个品种全部**历史源数据**的获取：

```text
图表 / 指标 / 策略 / 实时流 的历史需求
   │  register(demand)：目标周期、目标范围、紧急程度、所属者
   ▼
SymbolHistoryPlanner（每个品种至多一个）
   1. 需求 → 源格子：按 IntervalResolver 的 base 把目标范围换成源周期的格子（89m→1m，90s→1s）
   2. 合并：同一源周期的格子取并集，每格记下所属者集合和最高紧急度；减去库里已有的可信收盘行
   3. 切片：按紧急度和由新到旧切成片；每片只有一个写入者，声明自己的写入范围
   4. 路线：每片选归档或 REST（§4，一个纯函数 + 路线健康）
   5. 执行：在同一个执行器里取数、原生写入（沿用 fetcher / reconciler 的原生写入和校验）
   6. 释放：一片提交后，唤醒源格子已齐全的目标窗口去派生（沿用现有派生路径）
   ▼
派生与发布（现有：reconciler 派生、custom_query 读取、事件推送）
```

规划器只管"源数据何时、从哪里、由谁取"。派生规则、读取规则、写入校验、gap ledger、实时流都不改。
调度器（`BackfillScheduler`）继续负责规划器以外的工作：手动修复、ledger 对账、存储审计、非本品种的请求。

第一版的范围是**单一底层的派生周期**（89m、97m、90s、OKX 89m 等，RC 的全部场景）以及同品种的原生周期图
（例如分屏里的 1m 图），因为它们写同一张源表。多源合成（10007m 这类 mixed composition）第一版仍走现有 chunk 流程，
规划器只保证不与它的写入范围重叠（§7.3）；之后按测量决定是否接入（§10 S8）。

## 3. 需求合并

### 3.1 需求的形状

```text
Demand(
  owner      = 请求的 demand_scope + generation（已有），或 ensure_stream 的 consumer，或目标生命周期 token
  target     = (interval, [start, end))
  kind       = forming | first_screen | page_back | viewport | tail | gap_repair | prefetch
  created_at
)
```

紧急度由 `kind` 决定，从高到低：`forming`（每个打开的目标的当前桶）> `first_screen`（可见图的 `count_back` 最新部分）
> `page_back`（正在向左翻的那一页）> `viewport` / `gap_repair` > `tail` > `prefetch`。同一级内由新到旧。

### 3.2 换算与合并

- 目标范围按 `IntervalResolver(purpose=HISTORY)` 的 base 换成源格子；源周期不同的需求各自成集合
  （例如 Binance spot 90s 用 1s，89m 用 1m）。
- 同一源周期的需求取并集。一格有多个所属者时，紧急度取最高的那个。于是：
  - 89m 和 97m 两张图的重叠时间只取一次 1m；
  - 分屏里的 1m 图和 89m 图向左翻页，取的是同一批 1m 格子，一片同时满足两张图；
  - 种子（当前桶）和视口历史不再是两个 lane，而是同一张格子图上紧急度不同的两段。
- 减去库里已有的可信收盘行（`source_is_trusted_final` 且已收盘）。读一次、按需增量更新：
  规划器自己的写入提交后直接更新，不再回读整段；别的写入者（手动修复、其它进程）通过修订事件通知。

### 3.3 轮询不再产生需求

`/klines/latest` 和 `/klines/range?repair=async` 的重复轮询只读取。它们对同一 owner、同一范围的重复登记是幂等的
（只刷新租约时间），不触发新的规划或获取。这一点把 RC 里 208 次种子和 182 次 range 轮询的重复规划一并去掉。

## 4. 每段的路线：归档还是 REST

### 4.1 一个纯函数

```text
choose_route(piece, objects, health, now) -> Route(kind=ARCHIVE|REST, objects=[...], rest_windows=[...])
```

输入：片的源格子；可用的归档对象（只有已发布的整天/整月，Binance 日度文件次日才有，所以当天和前一天总是 REST）；
本地 ZIP 缓存命中；REST 代价（格子数 / 页大小 × 权重）；路线健康（§4.2）；片的紧急度。#508 已经把路由选择做成一个纯函数
（`d5fa599ad`），以它为起点。规则：

1. 本地缓存有新鲜对象：用归档，不联网。
2. 紧急片（`forming`、`first_screen`、`page_back`）：默认 REST。只有当归档主机健康、对象可用、而且 REST 代价超过
   `K` 页（建议 `K = 8`，约 8,000 根 1m）时才用归档；即使用归档，也给它一个短的**首字节期限**（建议 8 秒），
   过期立刻对同一范围发 REST，归档在后台继续下载，供以后的需求用缓存。
3. 不紧急的片（`viewport` 以外更深的历史、`tail`、`prefetch`）：可用对象且健康时用归档，阈值沿用 3 页。
4. 归档主机不健康：全部 REST，后台每 5 分钟用一个对象探测一次，成功即恢复。

### 4.2 路线健康

按主机（`data.binance.vision`、`fapi.binance.com`、`www.okx.com` 等）记：最近的首字节延迟（EWMA）、连续超时次数、
最后失败时间。连续 2 次超时或 1 次握手超时 → 不健康，冷却 5 分钟。今天只有按对象的负缓存，所以 RC 里同一网络上每个新对象
都要再等 60 秒。

REST 一侧：`exchangeInfo`（CCXT 加载 markets）是所有 REST 页和 WS 的共同前提。它超时不应按"第 1/4 次页请求失败"计入
每一片的重试次数，而是作为品种级的前提状态：前提未就绪时片不消耗重试，等前提就绪后一起开始。

### 4.3 与 #610 的关系

首字节期限需要在归档下载路径上加一个期限。`backfill/archive_cache.py` 正被 #610 修改，所以这一步排在 #610 合并之后；
路线函数和健康表放在 `source_router.py` 与新模块里，不碰 `archive_cache.py`。

## 5. 向左翻页

- 图表的 `query_before` 登记 `page_back` 需求：`[新左端, 当前左端)`，大小沿用前端的页大小。
- 规划器把这一页切成片，紧急度高于视口其余部分。片边界对齐归档对象（整天）或 REST 页预算。
- 每个品种预取**一页**超出可见左端的数据（`prefetch`，最低紧急度）。多张图共用这一份预取。
- 已确认的左边界（上市时间，`_record_confirmed_left_boundary`）照旧，规划器不会越过它。
- 回应方式不变：API 先返回已存的部分并标 pending，片提交后的进度事件让图表重新请求。
- 分屏 1m + 89m：两张图的翻页落在同一批 1m 格子上，一片满足两者。RC 里每页超过 120 秒，原因是两张图在两条 lane 上各自取、
  互相使对方的获取失效。

## 6. 取消

- 每个需求有所属者租约（已有的 `demand_scope` / `demand_generation` / `demand_owner_id`，以及 `ensure_stream` 的 consumer）。
  图关闭、换品种或周期、或 generation 被新请求取代时，释放它的全部需求（`advance_demand_scope`、`revoke_demand_owner` 的现有语义）。
- 格子的所属者集合变空即从格子图删除；还没开始的片如果已经没有所属者，直接丢弃。
- 正在执行的片：当前这一页完成并照常提交（取到的数据不浪费，校验照常把关），之后不再开始下一页。
- `forming` 需求属于目标生命周期（`history_target_token`）：关掉再打开是一个新需求，与 #619 的语义一致。
- 进程关闭：未开始的片丢弃，正在执行的片按现有关闭流程取消。

## 7. forming 柱与修订的围栏

### 7.1 只规划已收盘的源格子

- 收盘边界 = 最后一根已收盘源柱（`last_closed_bar_open_ms`），再加上已有的延迟：秒级源的 `source_second_close_delay`，
  以及 Binance 只有 REST 的收盘要等 REST 缓存稳定（#611，收盘后 15 秒）。
- 正在形成的源柱和目标的当前桶属于实时流和聚合器（warm-start 种子、`adopt_history_prefix`）。规划器的 `forming` 需求
  只要当前桶里已收盘的组件。
- WS 收盘与 REST 快照的先后规则（#606、#611）不变：规划器取到的 REST 行仍按现有来源优先级合并。

### 7.2 写入范围先声明，写入校验不放宽

- 每片是一个 acquisition，取数之前声明写入范围：REST 页的格子，以及归档对象的完整范围（整天、整月），并捕获原生范围视图
  （`capture_planned_write_views`，#602 的做法）。品种内别处的写入（例如实时流每分钟写最新一根）不再让它失效。
- 规划器是本品种受管范围内唯一的历史写入者。受管范围内仍可能与它冲突的只有：实时流写最新收盘的 1m（只影响 `forming` 片）、
  手动修复、其它进程。这些照常由校验拒绝并重试该片。
- 片的大小有上限（建议每片不超过 4,000 根、单次获取不超过 60 秒）。RC 里 81 秒的长获取让 1,024 个修订的回执窗口被挤掉，
  这是 `warmup change receipts do not cover the acquisition` 的直接原因。再取 #465 的"按实际消费的输入证明"
  （`9a5ec8d15`）作为第二道：回执不够时，用已消费输入的摘要证明范围未变。
- native / derived / warmup / mixed 的写入校验、删除权限下限、`acquisition_revision` 全部不改。冲突减少只能是因为受管范围内
  没有并发写入者，不是因为校验变松。

### 7.3 派生的门控

- 一个目标窗口 `[target.start, target.end)` 只有在与它重叠的源片全部提交之后才派生（按写入范围判断，#508 §6.1 的结论：
  源行插入会触发 `kline_dependents_*` 删除重叠的派生柱）。
- 多源合成（10007m）第一版不接入，但规划器的片不写进它正在执行的 chunk 的写入范围（反过来它的 chunk 也按现有校验把关）。

### 7.4 修订

- 已提交范围内的源数据被修订（例如 REST 修正刚收盘的一根）：受影响的目标桶由现有的 dependents 触发器和修订事件重算。
  规划器只在修订**删除**了行时才把那些格子重新列为缺失；数值修正不重新获取。
- 修订事件与规划器自己的提交走同一条更新路径，格子图不会因为自己的写入回读整段。

## 8. 代码组织与 `backfill_coordinator.py` 的拆分

新模块（`backend/app/data_engine/data_manager/symbol_history/`）：

| 文件 | 内容 |
| --- | --- |
| `demands.py` | 需求、所属者租约、紧急度 |
| `slots.py` | 源格子集合（按周期的区间集，带所属者与紧急度） |
| `routes.py` | `choose_route` 纯函数、路线健康表 |
| `pieces.py` | 切片、写入范围声明、片执行器（复用 fetcher / reconciler 的原生写入） |
| `planner.py` | `SymbolHistoryPlanner` 与按品种的注册表 |

接入点：`DataManager` 提交缺口（`_submit_missing_ranges`）、warm-start 种子与尾部、`query_before`、实时流断档，
在开关打开时改为向规划器登记需求；关闭时走现有路径。

`backfill_coordinator.py`（3,970 行）只在改到的地方拆：

| 拆出 | 现在的位置 | 什么时候拆 |
| --- | --- | --- |
| 请求准入（`trigger`、`request`、`_request_in_loop`、需求 scope/owner） → `backfill_admission.py` | 约 237–440、2210–2330 | S4，规划器接入时 |
| 带重试执行（`_run_with_retries`、完成与缓存回读） → `backfill_execution.py` | 约 2386–2800 | S4 |
| 左边界（`_record_confirmed_left_boundary` 等） → `backfill_boundary.py` | 约 3685–3960 | S6，翻页时 |
| ledger 写后队列 → `backfill_ledger_writer.py` | 约 2938–3200 | 改到时 |
| 启动扫描与审计、ledger 对账 | 约 659–2137 | 不改就不拆 |

## 9. 从搁置栈取用什么

搁置栈的基础是 2026-11-17 的 main，不能整体合入。#436 的 55 个提交里有 6 个已经以等价补丁在 main 上
（`493f43980`、`25bc04b3b`、`306e5e140`、`b51dfb095`、`6f4e9f06f`、`62e9edb29`，后两个即 #568）；
其余各 PR 没有任何提交在 main 上。#444、#446 已经分别经 #569、#570 移植。

| PR | 取用 | 方式 | 不取 |
| --- | --- | --- | --- |
| #436 | `e1d37f368` warm-start 的大回放让出事件循环、存储读放到有界执行器（种子每次轮询都在事件循环上读存储） | 改写后单独 PR | `b4fe4fa01` EMA（B-445，另行）；`d54e06323` 等指标执行（#444 已移植）；`e5d20a4a3`、`345172362`、`1ea7f1c2b`（#446 一组，先核对 #570 是否已覆盖）；mixed 大区间获取的一组提交（`b70e037df`、`2f57e978c`、`a5816a3c8`、`60df99d2b`、`52a3d0207`、`ae03b0166`、`56c5c7bb7`、`9f92d3d7e`、`95af148f9`、`d44ad86f6`），由规划器替代，只作边界情况参考；`e062d3fa9` 内存额度提到 192 MiB（没有测量依据不改） |
| #436 | `9d149fbd0` 前台满载时跳过队列扫描；`7d21eec06` 合并嵌套的 pending 轮询且不丢所属者；`f960032b7` latest 读复用已校验的尾部 | 与 S3 一起评估：规划器接入后调度器负载下降，如测量仍有收益再取 | QA 文档提交 |
| #464 | 按片的路由回执（决策、范围、REST 页数、归档行数、拒绝次数） | 作为规划器片回执的格式 | 按合同拆分归档 run（规划器的片只有一个合同） |
| #465 | `9a5ec8d15` 用实际消费的输入证明有界 warmup 写入（RC 的 `warmup change receipts` 失败） | 改写到片的写入上，带原测试 | — |
| #466 | 缺 preview 时只读当前桶、不重取已收盘前缀；本地探测上限 8 次 | 与 `forming` 需求一起改写 | 目标页复用的其余部分（由格子图替代） |
| #467 | 去重时按实际覆盖而不是父请求包络判断 | 调度器仍处理的工作需要它，单独 PR | aged 派发公平性（规划器自己排序）；256 条诊断环（可选） |
| #469 | `de5ebad78`、`4a732f172` 临时释放前缀 slot 时保持实时交接（`history target generation expired`） | 先看 1.0 上是否还出现这个错误，出现再取 | QA 文档 |
| #471 | — | — | 桌面存储允许 v9 键（`saveChartWorkspace` 在应用里没有调用者，价值低）；失败验收记录 |
| #473 | `ca260f0d3` 有类型的修订冲突重新规划而不耗尽需求；`1597dabb1` 执行器准入让出而不丢需求 | 改写到片执行器 | 依赖订阅机制本身（由格子图替代） |
| #474 | 资源许可到达后在原阶段续跑、不重新派发 | 改写到片执行器 | 其余 |
| #477 | — | — | 按阶段的内存公平和额度上调（没有测量到内存压力前不做） |
| #508 | `d5fa599ad` 路由选择纯函数（§4 的起点）；`c52ebad39` 冷源选择缓存；`b0252a9aa` 源柱只删除不窄于它的派生柱；`ee8214644` 冷路径固定开销（能力查询不再深拷贝交易所文档，约 40 秒 CPU/次加载）；`e5fa098fa` + `55dff7f5e` 批量修订记账与线性依赖查找、内存准入死锁修复；`d0221e1e6` 派发的 chunk 不继承派发者的 ContextVar | 各自独立的小 PR，带原测试，S3 | FamilyFill 本体（`family_fill.py`，叠加门控，已测得更慢）；`finer_work_hold`（由格子图替代）；`d971e2741` 复用已提交分钟（由格子图替代） |
| #508 | `8c1d35539` `plan_family_sources`、route-aware mixed planning 一组（`6a2920285`、`c76450ee7`、`7f8f73812`、`1664497dc`）、`9c5b1278c` | 多源合成接入时（S8）再取 | — |
| #511 | `d2172637c` 缓存读冲突不再安排整窗修复（`/klines/history`、`/klines/range` 曾为已存的柱安排修复）；`cf46f6b3b` H127 页按组件元组读取 | 单独 PR，S3 | — |

取用完成后由用户决定关闭这些 PR，并在每个 PR 里留下取用了哪些提交的链接。

## 10. 测量计划与实施步骤

### 10.1 场景（与 RC 相同）

| 编号 | 场景 | 脚本（主检出 `output/rc/0be80267f/`，git 忽略） | 记录 |
| --- | --- | --- | --- |
| M1 | Binance USD-M BTCUSDT 89m 冷加载 + 关闭重开 | `cold-89m.mjs` | 首根 K 线时间、就绪时间（`marketReady && !loading && !initialHistoryPending`）、30 秒采样的根数、热重开时间 |
| M2 | Binance spot 90s 冷加载 | `custom-matrix.mjs`（只选 90s 一例） | 同上，加冲突次数 |
| M3 | OKX spot / perp 89m 冷加载 | `cold-89m.mjs`（`CE=okx CM=spot CS=BTC-USDT`；perp 用 `CM=futures CS=BTC-USDT-SWAP`） | 同上，上限 10 分钟 |
| M4 | 1m + 89m 分屏，连续向左翻 3 页 | `recheck16.mjs` / `probe-16p.mjs` | 每页时间、接缝缺口 |

后端计数（sidecar 日志和 `snapshot()`）：种子提交次数、调度器 submitted/deduped/merged、`StaleAcquisition` 次数与类型、
`rest_fallback` 次数和每次等待、归档字节数、REST 页数、`exchangeInfo` 超时次数。

### 10.2 方法

- 改前：1.0.0 正式安装包。改后：同一 CI 工作流从栈顶构建的 macOS 安装包。用 `RC_APP` 指定，`RC_TAG` 分开 profile；
  每次冷加载用新 profile。
- 同一台机器、同一网络和代理设置，改前改后**交替**跑，每个场景至少 3 对，同一小时内完成。每对开始前记录一次网络：
  `curl` 到 `fapi.binance.com/fapi/v1/exchangeInfo`、`api.binance.com`、`data.binance.vision` 和 `www.okx.com` 的连接与首字节时间。
  两侧网络等级不同的一对不计入。
- 报中位数和每一对的原始值，不跨轮次比较绝对时间（机器负载会让绝对值相差 ±60%）。
- 另有两个本地可重复的探针（无网络）：`forming_seed_probe.py`、`archive_first_probe.py`，现在在 git 忽略的
  `output/backfill-planner-1.1/probes/`，S2 时改写成提交进仓库的测试。每个实施 PR 跑一次，结果写进 PR。

### 10.3 验收

1. M1 冷加载就绪时间中位数比 1.0.0 少一半以上（约 325 秒 → 160 秒以内），前 30 秒内出现首屏 K 线；热重开不变差（约 19 秒）。
2. M2、M3 在 4 分钟内就绪，M2 的冲突次数下降。
3. M4 每页 30 秒以内，无接缝缺口。
4. 受管范围内的 `StaleAcquisition` 只剩最新一分钟的实时写入引起的那类。
5. 归档主机不可用时，紧急片的 REST 在 8 秒内开始。
6. 1.0.0 之后的所有回归测试照常通过，写入校验没有放宽。

数字目标是建议，由用户确认（§11 Q4）。

### 10.4 实施步骤（叠加的小 PR，每个带测试和测量）

| 步骤 | 内容 | 依赖 |
| --- | --- | --- |
| S0 | PR #619：forming 种子每个桶只提交一次 | 已开 |
| S1 | 改前测量：1.0.0 安装包上的 M1–M4，结果写进本 ADR 的附录 | 1.0.0 打 tag |
| S2 | 路线健康表 + `choose_route` 纯函数；紧急片 REST 优先 | — |
| S2b | 归档首字节期限，超时立即 REST | #610 合并后（`archive_cache.py`） |
| S3 | 搁置栈的独立修复，各一个 PR：#508 的固定开销、批量记账、ContextVar、派生柱删除范围；#511 的缓存读冲突；#465 的输入证明 | — |
| S4 | 规划器骨架（需求、格子图、片、执行器），开关默认关；拆出请求准入与执行 | S2 |
| S5 | 单一底层派生周期接入：history、range、种子、尾部；`forming` 片优先 | S4 |
| S6 | 向左翻页与预取；取消；拆出左边界 | S5 |
| S7 | 同品种的原生周期图接入（分屏 1m + 89m） | S6 |
| S8 | 多源合成（10007m）接入，按测量决定 | S7 |
| S9 | 改后测量 M1–M4，达标后开关默认打开；旧路径在 1.2 删除 | S7 |

任何一片失败或超时，规划器把那段格子交还现有流程，行为等同今天（#508 FamilyFill §6.4 的回退方式）。

## 11. 待决定

- **Q1 第一版范围**：单一底层派生周期 + 同品种原生周期图，多源合成（10007m）放到 S8 再定。是否同意？
- **Q2 紧急片默认 REST**：首屏、当前桶、正在翻的那页默认走 REST，归档只在 REST 超过 8 页且主机健康时用，并有 8 秒首字节期限。
  是否同意这两个数（8 页、8 秒）？
- **Q3 开关**：规划器先以开关（默认关）上线，测量达标后默认打开，旧路径在 1.2 删除。还是测量达标后直接替换？
- **Q4 验收数字**：§10.3 的目标（M1 冷加载减半、M2/M3 4 分钟内、M4 每页 30 秒内、紧急片 8 秒内开始 REST）是否合适？
- **Q5 S3 的顺序**：搁置栈的独立修复先于规划器单独合入（风险小、收益可单独测量），还是并入规划器的 PR？
