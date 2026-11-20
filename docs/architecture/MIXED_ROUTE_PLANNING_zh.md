# 按路由规划 mixed 回填（Route-aware mixed planning）设计

状态：已实现并默认打开（`mixed_routes.ROUTE_AWARE = True`，设为 False 即回到原来的规划）；验收见 §8 第 5 步。
B 类冲突后来由 `data_manager/finer_work_hold.py` 处理（§10，默认打开，`finer_work_hold.ENABLED = False` 关闭）。
更细的数据只细化它触及的格子（§11，`history/source_precedence.trim_rejected`，规划和读取共用）。
派发的 chunk 不再继承派发者的 ContextVar（§12）
范围：Binance USD-M 上 required 的 mixed composition chunk（典型是 10007m），冷启动历史回填
相关：`backfill/mixed_plan.py`（规划）、`backfill/source_router.py`（路由）、`backfill/fetcher.py`（获取与写入窗口）、
`backfill/reconciler.py`（派生）、`storage/native_history_fence.py`（原生写入校验）、
`backfill/family_plan.py`（细数据优先的不动点）、[COLD_FAMILY_FILL_zh.md](COLD_FAMILY_FILL_zh.md)

## 1. 问题

四图冷加载里，10007m 最后就绪，是整体时间的关键路径。它的 chunk 大部分工作时间花在作废的尝试上：
真实延迟模式（`net_real`）下，10 次成功尝试共 8.9 秒工作时间，5 次重新规划和 3 次重试共 104 秒（约 12 倍）。

逐个冲突追到写入者（`output/cold-local-cost-20261119/tools/run_blame.py`，一次加载，114 个冲突里 14 个落在 10007m）：

- **A（7 个）**：相邻两个 10007m chunk 在交界处所在的 UTC 月份都需要 1h。一个导入这个月的 1h 归档对象（或打算导入），
  另一个用 REST 取自己那几个小时，或者也导入同一个对象。后写的一方原生窗口已变，只能重新规划。
  这些冲突发生在 19–23 秒，决定了 10007m 何时完成。
- **B（6 个）**：最新的 10007m chunk（7 月底到 11 月中）与短周期图最近两周的稠密 1m 重叠，它运行期间短周期图写入，规划失效。

本设计（§2–§8）只解决 A。B 后来单独处理（§10）。

### 1.1 已试过、已撤回的三种做法

| 做法 | 结果 | 说明了什么 |
|---|---|---|
| 路由时不导入超出本 chunk 目标范围的对象 | 10007m 冲突 14 → 2，但每个 chunk 都 PARTIAL，重试一次 | 内部月份仍整月导入 1h，而计划没有算进这些行：一个 1d span 从整月 1h 的月份延伸到只取了窗口的月份，派生前被 `checked_mixed_windows` 判为"被更细数据覆盖"而拒绝 |
| mixed chunk 完全不用归档对象 | REST 限流延后 14 次，重新规划 18 次，10007m 20.7–28.7 秒 | 归档对象让请求不占 REST 限额，不能去掉 |
| 计划时把用到的每个 1h 月份补全，并改用 ≤1h 的精度覆盖 | 冲突仍为 2，但较旧的 chunk 全部在写入后的复查（`checked_mixed_windows`）耗尽位置预算 | 补全时把整月当作一个窗口，而窗口里有目标边缘自己的 1m 行：复查要把整月细化到更细的精度，超出整个 chunk 共用的 `MAX_POSITION_WORK`。cover 的窗口必须按目标的 span 切，补全的行要作为对象单独写入 |

另外两条路走不通：归档导入不能裁剪到一个 chunk 的范围（导入回执就是整个对象的幂等键）；
原生写入校验中"捕获之后即使写入相同的值也要失效"的约束保留。

### 1.2 根因

规划和路由是分开的两步：

1. `build_mixed_backfill_plan` 先按已存数据规划 cover 和要取的窗口；
2. 获取时 `HistoricalFetcher.fetch` 才调用 `HistoricalSourceRouter.prepare`，按任务窗口和阈值逐 run 决定哪些用归档对象、
   哪些用 REST，再把对象的整个范围加进原生写入校验（`planned_write_windows` → `capture_planned_write_views`）；
3. 派生时 reconciler 只按计划的窗口合成；`checked_mixed_windows` 在原生写入之后检查更细的数据，
   发现对象多写的细数据压在计划的粗 span 上就拒绝，留给下次重试重新规划。

所以计划不知道对象会写什么：对象写到计划窗口以外，写进相邻 chunk 的目标范围（A），或者写进本 chunk 计划为粗 span 的
位置（第一种做法的 PARTIAL）。每种只在路由一侧修补的办法，都会让计划和实际写入在别处对不上。

## 2. 目标与非目标

目标：

1. mixed chunk 的计划在任何捕获和获取之前就完整说明它要写什么：导入哪些对象、用 REST 取哪些窗口。
2. 写入的每一行都在本 chunk 的目标范围 `[first, stop)` 之内，不写进相邻 chunk 需要的行。
3. 计划的 cover 与要写入的全部行一致：派生时不会因为本 chunk 自己的写入而被 `checked_mixed_windows` 拒绝。
4. 请求和下载的代价不高于今天（内部月份照常用对象，只有交界月份的一小段改用 REST）。
5. 不放宽任何写入校验；任何一步失败或超出预算，这个 chunk 回到今天的做法。

非目标：

- B（最新 chunk 与短周期图重叠）：不改规划，后来由调度器处理，见 §10。
- 短周期图在冷启动时走单一底层 1m 的 chunk（它们相邻 chunk 共享日度 1m 对象，也会冲突，可作为第二步，§9）。
- FamilyFill（保持默认关）。

## 3. 设计

### 3.1 规划时就能列出候选对象

`provider.plan_objects(market_type, symbol, interval, start_ms, end_ms, now_ms)` 只依据日期计算（完成的月份用月度对象，
近期用日度对象），不访问网络；联网的 `resolve_objects`（校验和、是否已发布）留在获取时。
因此规划时可以为每个精度列出 `[first, stop)` 内的候选对象。

只保留**完全落在 `[first, stop)` 之内**的对象（本 chunk 独有）。跨越边界的对象一律不用，交界月份在本 chunk 内的部分用 REST。

### 3.2 路由决定移到规划里，规则只有一份

把路由现在的取舍规则（`_filter_daily_candidates` 的最少页数与 composed 窗口数，`_bounded_usdm_archive_candidates` 的
行数、路由范围和放大倍数限制）抽成一个纯函数，例如：

```text
select_owned_objects(objects, needed_cells_by_grid, owned_range, page_size, minimum_pages) -> 要导入的对象
```

规划和路由都调用它，两边不会分叉。对一个本 chunk 独有的对象：计划在其中需要的行足够多（达到现有阈值）就导入，否则用 REST 窗口。

### 3.3 按"将会存在的行"重新求一致的 cover

决定导入哪些对象后，在"已存可信行 ∪ 要导入的对象的全部行 ∪ 计划的 REST 窗口"上重新做一次细数据优先的细化，求不动点。
直接复用 `family_plan.plan_family_sources`（单个需求，`extra` = 要导入的对象的格子）：

- 对象写入的更细的行如果压在计划的粗 span 上（第一种做法的接缝），在规划时就把这些 span 细化掉；
- 细化后在对象以外还需要的细格子，作为 REST 窗口加入计划（仍在 `[first, stop)` 之内）；
- 对象的取舍只决定一次（第一轮），之后只增加 REST 格子，单调收敛。

细化工作发生在规划时，受现有预算约束（`MAX_POSITION_WORK`、`MAX_SOURCE_ROWS`）。超出预算就不对这个 chunk 采用本设计，
回到今天的规划。这样不会像第三种做法那样把细化推到派生时去碰预算。

### 3.4 计划的输出

- 对象任务：在任务的 metadata 里写明要导入的对象键（例如 `mixed_route_objects`）；
- REST 任务：照常是精确窗口（`mixed_fetch_windows`），读取的超前行照常丢弃（`selected_fetch_rows`）；
- `derived_source_windows`：与重新求出的 cover 一致；
- 原生写入校验：计划已经知道全部写入范围（对象 ∪ 窗口），在获取前一次捕获，不再在路由之后扩展。

### 3.5 路由服从计划

`HistoricalSourceRouter.prepare` 对带 `mixed_route_objects` 的任务不再自行挑选：只解析并导入列出的对象，
不做父批次预取（composed 任务现在已经关闭），其余全部走 REST。

对象在获取时解析失败（尚未发布、404、校验失败）：在这个对象的范围（已知在 `[first, stop)` 之内，行数不超过单个对象上限）
整段改用 REST。计划假设这些行都会存在，整段补取能保持一致；只取 cover 用到的格子会重新引入接缝。

### 3.6 派生

本 chunk 自己的写入与计划一致，`checked_mixed_windows` 不会因为它们拒绝任何窗口；它继续作为其它写入者（实时流、
其它图）的安全检查。

## 4. 正确性

- 写入校验不变。冲突减少的原因只能是相邻 chunk 不再写同一批行，以及计划与本 chunk 的写入一致。
- 每一行写入都在本 chunk 的 `[first, stop)` 内：对象只取完全在范围内的，REST 窗口来自范围内的 cover。
- 删除权限、`acquisition_revision`、mixed target 与 computation 校验都不变。
- 规划超预算、规则判断不出、对象解析失败的整段 REST 补取再失败：都退回今天的路径（下一次尝试按今天的方式规划）。

## 5. 代价

- 请求和下载：内部月份照常导入对象；每个 chunk 两端的交界月份改为 REST，每段至多一个月的 1h（≤744 行，一页）。
  一次冷加载 8 个 10007m chunk，约增加十几个小 REST 请求，对象下载略少。需要实测确认不触发限流延后。
- 规划：每个 chunk 多一次细化不动点和一次候选对象计算，冷启动时已存行很少，读取量小。需要实测 CPU。

## 6. 测试

1. **规则一致**：同样的输入下，抽出的 `select_owned_objects` 与路由现在的选择结果相同（对象完全在范围内时）。
2. **性质测试**（仿照 `tests/test_family_plan.py`）：随机已存状态和候选对象，把计划的对象和窗口写进库后：
   - 写入的行都在 `[first, stop)` 内；
   - 每个目标都能用真实 reader 完整合成，`checked_mixed_windows` 不拒绝任何计划窗口；
   - 相邻两个 chunk 的写入集合不相交。
3. **路由服从**：带 `mixed_route_objects` 的任务只导入列出的对象；解析失败时整段改 REST，派生仍完整。
4. **预算**：超出规划预算时退回今天的规划，结果与今天相同。
5. 关闭开关时现有测试全部不变。

## 7. 验收

用 `run_blame.py` 和 `run_waste.py`（`net_real`、`net_zero` 各配对多轮，开关交替）：

1. 10007m 的 A 类冲突（相邻 chunk 的 1h 原生窗口）为 0；
2. 10007m 没有因本 chunk 自身写入导致的 PARTIAL（"lack trusted composition fields/coverage"）和随之而来的重试；
3. 10007m 重新规划次数明显下降，全部就绪时间不晚于今天、目标是明显提前；
4. REST 请求数和限流延后次数不高于今天的配对中位数加一个小的余量；
5. 全量测试无新增失败。

## 8. 实施步骤

1. 抽出 `select_owned_objects`（纯函数）并让路由改用它，行为不变；规则一致测试。
   （已完成：`source_router.select_archive_objects` 返回 `ArchiveSelection`，路由的指标和每个任务的决定照旧；
   `tests/test_archive_selection.py` 在 60 组随机 run 上与原先内联的判断逐项相同，覆盖导入、预算拒绝的三种原因
   和 1d 改用 REST 的情形。只保留完全在范围内的对象由第 2 步的规划负责，这个函数本身不改变路由的选择。）
2. 规划：候选对象、导入决定、`plan_family_sources` 不动点，输出对象任务与窗口任务（开关默认关）；性质测试。
   （已完成，开关 `backfill/mixed_routes.ROUTE_AWARE` 默认关：今天的规划通过全部检查（含 `rest_request_cost`）之后，
   `route_aware_plan` 读已存行（`family_plan.read_stored_series`，FamilyFill 也改用它），单独求一次 cover，
   每个精度只取完全落在 `[first, stop)` 内的候选对象，用 `select_archive_objects` 按第一轮要取的窗口定价，
   再以导入对象的全部格子为 `extra` 求不动点，输出对象任务（`mixed_route_objects` 列出对象键；一个对象超过单任务行数时
   会拆成几个任务，列同一个键，第 3 步的路由按键去重）、REST 窗口任务和按新 cover 的派生窗口，全部带
   `mixed_target_range`。行数超预算、规则判断不出、REST 请求数高于今天的上限，都保留今天的计划
   （`mixed_route_aware=False`）。`tests/test_mixed_routes.py`：真实 Binance 目录，相邻两个 16 目标的 10007m chunk，
   12 组已存状态（冷、按网格对齐的 1m/1h/1d 片段、整月 1h），检查写入都在本 chunk 内、两 chunk 不相交、
   写入后 `checked_mixed_windows` 不拒绝任何窗口、真实 reader 完整合成；今天的规划先拒绝的状态（chunk 由调度器拆分）
   只要求路由规划没有运行。对照：按今天的规划加路由选对象，第 8、9、11 组会写出 chunk 之外（254–491 行）并与相邻 chunk
   重叠（56–126 行），即 A 类。相关的 45 个测试文件：开关关时与 HEAD 失败集合相同（另有一个 FamilyFill 的已有偶发失败，
   HEAD 上 4 次也失败 1 次）；开关强制打开时，现有 mixed 测试里 62 次路由规划全部采用（这些测试不开归档，只有 REST 窗口），
   没有新增失败。）
3. 路由服从 `mixed_route_objects`，解析失败时整段 REST；路由测试。
   （已完成：键改由路由定义为 `source_router.PLANNED_OBJECTS_KEY`，规划的 REST 任务带空列表。`prepare` 先把带这个键的
   任务交给 `_prepare_planned`：按键在目录里找到对象、照常解析（缓存、探测、解析器，抽成 `_resolve`，原路径共用），
   每个对象只开一个 singleflight、只有一个所属任务，不选别的对象、不做父批次预取，REST 任务没有对象；不带键的任务照旧选择。
   对象任务的范围就是对象本身，所以目录里找不到（`archive_planned_object_rest_fallbacks`）或解析失败时，任务没有对象，
   整段走 REST；下载失败（404、校验失败）时由取数器现有的回退在任务与对象的交集上走 REST，也是整个对象。
   `tests/test_planned_archive_routes.py` 用第 2 步的真实规划、真实路由和取数器、Binance 归档与 REST 替身：
   导入的对象恰好是列出的对象，同一次调用里的其它任务与单独路由时相同（同样的任务去掉键后，今天的路由每个 chunk 选
   3–8 个对象，其中 1–2 个跨出 chunk）；取到的行恰好是计划算进的行；一个对象 404 或不在目录里时，行仍然相同，
   对象的整段由 REST 取到。第 2 步的测试改用 Binance 真实的 REST 页大小（1000）定价。相关的 46 个测试文件：开关关时
   与 HEAD 失败集合相同；强制打开时只多出 `test_without_the_flag_the_plan_is_unchanged`（它检查的就是关闭时的行为）。）
4. 写入校验在获取前按计划一次捕获；确认 `planned_write_windows` 结果与计划一致。
   （已完成：USD-M 的原生写入校验只来自路由之后的捕获（获取前的 `capture_native_history_views` 不处理期货），
   每次运行最多 64 个窗口、32,768 行；没有校验覆盖的写入改走整个 family 的 acquisition 检查，任何并发写入都会让它失效
   （mixed 计划有多个精度，warmup 校验也不适用）。现在 `fetcher.planned_route_windows` 只凭计划给出写入窗口：每个任务的
   范围（REST，对象任务即其回退），每个列出的对象的整个范围（导入，归第一个列出它的任务）。引擎在获取前对带
   `PLANNED_OBJECTS_KEY` 的计划先捕获这些窗口，路由之后取数器报告的窗口都已存在，不再增加。路由规划在窗口放不进
   上述预算时（`native_history_fence.planned_windows_fit`，与捕获共用 `_planned_items` 的选择）保留今天的计划。
   测试：第 3 步的计划上，计划给出的窗口与路由后 `planned_write_windows` 完全相同（对象缺失时是其真子集），
   用真实存储先按计划捕获、再按路由捕获，后者不增加任何校验；预算不够时不采用路由规划。端到端
   （真实 coordinator、引擎、路由、存储，一张冷 10007m 图的两个相邻 chunk）：每个 chunk 一次成功，按计划捕获 32 个校验，
   路由后增加 0 个，图完整；开关关时同一场景两个 chunk 都以 PARTIAL（"lack trusted composition fields/coverage"）结束并重跑，
   共 4 次尝试。各种子下计划的窗口为 28–42 个、约 4–15k 行，都在预算内。相关的 50 个测试文件（加上原生、派生和 OKX 的
   范围校验测试）：开关关时与 HEAD 失败集合相同；强制打开时只多出 `test_without_the_flag_the_plan_is_unchanged`。）
5. 配对测量，按 §7 验收；全量测试。通过后默认打开。
   （配对测量已完成，见 `output/cold-local-cost-20261119/README.md` 第十二轮；`tools/run_routes.py`、`tools/pairs6.sh`。
   先跑的几次加载找出三个问题，都已修正并有测试：路由按任务最后的开盘时间查目录，而目录只在范围包含整天时才列出日度
   对象，所以计划的日度对象全部改走了 REST；引擎复用已提交的分钟、裁剪了计划对象的 1m 任务时，路由现在不导入对象，
   只用 REST 取剩下的行（整天导入会改写其它运行持有的行）；规划按每个窗口一个伪任务定价，路由"composed 1d 一页 REST
   就够时不导入"的规则从不生效，每次加载多导入 21 个月度 1d 对象，现在按合并后的 REST 任务定价，与路由看到的一致。
   最终配对（各 4 轮，`closed_once`，负载 5–10），中位数，开 / 关：
   `net_real` 全部就绪 15.8 / 20.3 秒，CPU 21.1 / 25.2 秒；`net_zero` 26.0 / 26.9 秒，34.6 / 36.3 秒。
   10007m 的 A 类冲突 0 / 7–7.5（之前两组配对的 16 次开启加载里没有一次窗口级的 A 类冲突），派发 11–13 / 19，
   "lack trusted composition" 的 PARTIAL 0 / 1–2.5，本地版本重新规划 1 / 6–7.5，修复重试 0 / 1–2.5；
   REST 请求 192–194 / 187.5–199，限流的运行 0–3 / 2.5–7.5，归档下载 23.5–26.5 / 33。
   剩下的 10007m 冲突是 B 类（§9.3，后来由 §10 处理），每次加载仍有一次最新的稠密 chunk 的 `refined_source_row_budget` 拆分，与今天相同。
   全量后端测试（约 10,700 个，跳过两个在本环境无法收集的文件：缺 `jsonschema`，以及 `test_review_regressions.py`
   引用了已删除的名字）：开关关时与 HEAD 失败集合相同（多出的 `test_amendment_inside_a_partly_consumed_native_window_stops_its_remaining_pages`
   在 HEAD 上单独跑 4 次都失败，是已有的不稳定测试）；强制打开时只多出检查关闭行为的 `test_without_the_flag_the_plan_is_unchanged`。
   §7 的五项都满足，开关已默认打开；该测试现在自己关掉开关。）

## 9. 待决定

1. **导入对象的阈值**：沿用路由现在的阈值（建议），还是对本 chunk 独有的对象更积极地导入（减少 REST，增加写入行数）。
2. **短周期图**：冷启动时它们是单一底层 1m 的 chunk，相邻 chunk 共享日度 1m 对象，也有重新规划（每次加载 4–15 次）。
   本设计稍作推广（单一底层计划也带目标范围）即可覆盖，建议作为第二步。
3. **B 的处理**：让最新的 10007m chunk 在与它重叠的短周期图 chunk 完成后再规划（小改动，去掉约 6 个冲突），
   可以与本设计并行做，也可以等本设计完成后再看是否仍需要。（已实现，见 §10。）

## 10. B 类：等短周期图的 1m 存好再规划（`data_manager/finer_work_hold.py`）

### 10.1 冲突

路由规划打开后，每次加载剩下 2 个 B 类冲突，都在最新的 10007m chunk 上。这个 chunk 有 16 个目标
（2026-07-26 06:51 起，最后一个开于 11-07 12:36），目标边缘需要 1m，获取前捕获了 11-07 12:00–12:59、
11-14 11:00–11:22 这两个小时窗口的原生视图。同时打开的 89m、97m、101m 冷启动约 13.7 天（11-06 16:57 起），
每个 chunk 约一天、16 个目标，底层都是 1m，大约 3–14 秒后写进同样的小时。10007m 的写入于是被拒绝
（"native history window changed during acquisition"），chunk 以 PARTIAL 结束。重试时 1m 已存，按更细的数据规划
超过 `MAX_SOURCE_ROWS`（16,384 行），被 `refined_source_row_budget` 拆成 [07-26..10-31] 和 [11-07] 两个 chunk 重跑。
所以每次加载有 2 个 B 类冲突、2 次没有完成的运行和 1 次预算拆分。

### 10.2 做法

调度器派发一个 qualified mixed chunk（带 `required_history_composition`）之前，先看同一 symbol（同一 exchange、
market type，默认 series identity）上其它图尚未完成的前台 chunk 可能写到哪里：

- 一个 chunk 的**可达范围**是它的目标范围 `[start, end + width)`，扩到它的底层精度可能导入的归档对象。一个月的底层行
  放得进一个对象（`MAX_USDM_ARCHIVE_OBJECT_ROWS`，如 1h、15m）时扩到整 UTC 月，否则（1m、3m、5m）扩到整 UTC 日。
  只有比 mixed chunk 窄的图才算。后台工作、其它 mixed chunk，以及已失效、失败或取消的请求都不算。
  chunk 的请求不会变，所以每个 chunk 只算一次。
- mixed chunk 的目标里，落进任何可达范围的被**扣住**。每个扣住的目标单独成一个 chunk：细数据存好以后，一个目标的行数
  就可能有一整个冷 chunk 那么多。其余连续的目标合成一个 chunk，立即派发。拆分走 `_refine_mixed_chunk`
  （cause `finer_work_hold`，不计入 `mixed_chunk_refinements`）。
- 扣住的目标等到重叠的工作全部完成再派发，最多等 `MAX_HOLD_SECONDS`（60 秒），超时后照原来的做法运行。
  释放后，它像任何后来的 chunk 一样在已存的细数据上规划，所有写入校验不变。
- mixed chunk 从不扣住别的 chunk，所以等待之间没有环。
- 几张图同时打开时，各自的请求相隔 30–77 毫秒到达调度器，顺序随机。10007m 先到时，它最新的 chunk 在任何重叠可知
  之前就派发了。所以一张 mixed 图的 initial history 里，最新的 chunk 在它的请求第一次进入派发时先等
  `SETTLE_SECONDS`（0.25 秒）；较旧的 chunk 不等。
- 这些都不依赖调度器的并发上限：app 和 bench 都用订阅模式（`max_concurrency=0`）。

### 10.3 规划的一处修正

释放后的 10-31 13:49 目标会在部分已存的 1m 上规划（短周期图已存 11-06 16:57 以后的 1m）。单个目标在这种状态下
整个由 1m 合成，比整段取这个目标多一页 REST（12 对 11）。`mixed_plan` 的 `rest_request_cost` 因此拒绝它，而
required composition 没有单一底层的回退（只有 optional 的计划会回到 `planner.plan`），拒绝就是硬失败
（"Qualified composed history could not admit this bounded repair"），10007m 永远不会就绪。现在 required composition
保留这个计划，多出的请求记在 `mixed_rest_requests_over_baseline`。`cold_rest_request_cost` 同样只拒绝 optional 的计划。
路由规划的采用条件改为 REST 不多于它取代的计划（或基线）。

### 10.4 测试

`tests/test_finer_work_hold.py`：

- 可达范围：底层 1m 扩到整日，1h 扩到整月，mixed chunk 没有可达范围；
- 只有落进可达范围的目标被扣住，每个单独一段；
- 调度器：其余目标立即派发，扣住的两个目标在短周期图完成后才派发，没有预算拆分和超时；
- 超时后扣住的目标照常运行；
- 后台工作、更宽的图和其它 mixed 图都不扣住 10007m；
- 等待：较旧的 chunk 立即运行，最新的 chunk 等 `SETTLE_SECONDS`，晚 20 毫秒提交的短周期图仍让它拆分；
- 规划：10-31 目标在部分已存的 1m 上能规划（没有 §10.3 的修正时失败）。§11 之后这个状态不再超过基线，
  改用分散的 1m 行，见 §11.4。

`test_family_fill.py` 里检查 family gate 一释放就派发的测试关掉了等待（它测的是 gate 本身）。
全量后端测试（约 10,700 个，跳过同样两个文件）：与路由规划默认打开时的上一次全量相比，只少了已修正的
`test_without_the_flag_the_plan_is_unchanged`。多出的四个失败里，三个在 HEAD 上单独跑也失败或单独跑都通过
（已知的顺序相关测试、真实 bus 测试、一个负载下的 worker 超时测试）。第四个 `test_dependent_lookup_stays_local_for_long_batches`
找出了本分支 `e5fa098fa` 的一个问题：`bulk_revisions._deletes_dependents` 对每一行都切片复制批次剩下的部分，长批次是平方的，
现在原地索引（该测试 2.4 → 0.05 秒；与行触发器逐表比对的随机测试照常通过）。

### 10.5 测量

`tools/pairs7.sh`（`FINER_HOLD=1/0` 交替，两边都打开路由规划，`closed_once`），各 4 轮，中位数，开 / 关
（`pairs/r19-hold-{real,zero}`，负载 7–11）：

| 中位数 | `net_real` 开 | 关 | `net_zero` 开 | 关 |
|---|---|---|---|---|
| 四图全部就绪 | 32.3 秒 | 35.6 秒 | 37.1 秒 | 40.8 秒 |
| 进程 CPU | 43.5 秒 | 45.8 秒 | 49.7 秒 | 54.9 秒 |
| 10007m 的 B 类冲突 | 0 | 1.5 | 0 | 1 |
| 10007m 没有完成的运行 | 0 | 2 | 0 | 2 |
| 10007m 派发 | 10 | 11 | 10 | 11 |
| 预算拆分 | 0 | 1 | 0 | 1 |
| REST 请求 | 190 | 187 | 193 | 192 |
| 限流的运行 | 0.5 | 0 | 1 | 1 |
| 归档下载 | 25 | 26 | 25 | 26 |

- 每次开启的加载（这 8 次和另外 8 次带追踪的加载）都等待一次、拆分一次、扣住两个目标，没有超时。
  加上等待之前的一组（`r18`），8 次开启加载里有 3 次 10007m 先到调度器，扣住没有生效；这一组没有 10007m 先到的加载，
  这种情形由单元测试覆盖。
- 短周期图就绪晚 2–4 秒：10007m 不再失败的目标现在与它们同时运行。
- 这一组的绝对时间比 `r18` 高约 60%，开关两边都高：机器上 Spotlight 和两个存储进程占了约 2 个核（共 8 个）。
  只有关闭一边的代码变化是上面的 `_deletes_dependents` 修正；新旧两种查找交替各 2 次（`pairs/r19-lookup`）没有一致的差别。
- 24 次开启加载里有一次（`r19-hold-real/cand-1`），释放后的 11-07 目标连续 7 次因 "canonical dependency range changed
  during acquisition" 失败（每次 20–1,600 毫秒），约 3 秒后成功。其余 68 次加载（`r15`–`r17` 的路由规划配对，`r18`、`r19` 的关闭一边，
  `r19-lookup`）里 10007m 没有出现过这种失败。bench 记下的写入里，失败前没有落进这个目标范围的。
  后来在更空闲的机器上更常见（16 次里 3 次），原因是调度器：派发的 chunk 继承了派发者的 acquisition scope，见 §12。

### 10.6 剩下的

- 释放后的 10-31 目标整个由 1m 合成，在全部 16 次开启加载里都是 10007m 最后完成的运行（8–24 秒，比较旧的 chunk 晚
  1.5–3.3 秒结束），是现在的关键路径。只在细数据已存或目标边缘用 1m、其余继续用 1h/1d，可以缩短它。（已做，见 §11。）
- 较旧的 chunk 本身在 28–40 秒才结束，主要是派生的 CPU（见 [COLD_FAMILY_FILL_zh.md](COLD_FAMILY_FILL_zh.md)）。
- 短周期图相邻 chunk 的重新规划（§9.2）不变。

## 11. 只细化更细的数据触及的格子（`history/source_precedence.trim_rejected`）

### 11.1 原因

§10 释放后的 10-31 13:49 目标，冷启动时只需取 75 行（边缘的 1m、1h、1d）；短周期图存下 11-06 16:57 以后的 1m 之后，
它要取 11-01 00:00 到 11-06 16:56 的全部 1m（8,217 行，路由规划下是 6 个整天的 1m 对象，8,640 行）。

`plan_fixed_range` 把同一精度相邻的格子合成一个 span。一个 span 只要有更细的行触及，就把整个 span 用更细的精度重新规划，
而重新规划的结果又合成一个 span。所以 11-06 下午的一个 1m 行让 1d span [11-01, 11-07) 依次细化成 4h、1h、15m、5m，
最后整段 1m。已存的 1m 从整点开始时（例如 11-07 06:00）只多出几百行，因为触及的只是最后一个 span；从整点之后开始时，
16:57 落在 1h、15m、5m 格子的中间，每一层都整段细化。

读取路径（`data_manager/mixed_history.py`）用同样的整段规则选择 cover，所以只改规划器不行：规划只存了 1d 和 11-06 的
细格子，读取仍会把 [11-01, 11-07) 细化到 1m，找不到那些 1m，目标就无法合成。这是合成的规则本身，五处必须一致：
`_MixedBackfillBuilder.refine`、`count_refined_rows`、`family_plan._refined_spans`（路由规划和 FamilyFill 用它）、
写入后的 `checked_mixed_windows`、读取路径。

### 11.2 规则

一个 span 因更细的行或删除足迹被拒绝时，只把它从第一个到最后一个被触及的格子用更细的精度重新规划；之前和之后的格子
留在原精度。任何被更细的行触及的粗格子仍然不会被采用，所以 H127 的 precedence 保证不变（见
[MIXED_HISTORY_H127.md](MIXED_HISTORY_H127.md)）。因为本精度的行不可用或缺失而被拒绝的 span 仍整段细化，与原来相同。

"被触及"对子范围是单调的（更细的行落在 `[start - width + 1, end)`，或删除足迹早于 `end`），所以第一个和最后一个
被触及的格子在前缀和后缀上二分查找，检查与拒绝整个 span 的那次相同。`trim_rejected` 是一个生成器：给出要检查的子 span，
调用方送回是否拒绝，同步（`drive`）和异步（`drive_async`）调用方共用同一段算法。每个格子都被触及时只检查两次
（首尾两个格子）；规划器和读取的批量预取现在也包括每个 span 的首尾格子，这种情形不增加存储读取。读取路径的单行探测
结果在本批内保留，与批量预取的结果一样。

### 11.3 结果

10-31 目标在 bench 的已存状态下（1m 从 11-06 16:57 起）要取的格子：1d 5 个（11-01..11-05）、4h 6 个、15m 3 个、
5m 4 个、1h 2 个、1m 3 个，共约 20 个，原来是 8,217 个 1m。路由规划与原来的规划结果相同。1m 从 11-07 06:00 起时，
原来取 360 个 1m，现在是几个 1h 和 4h。

### 11.4 测试

- `tests/test_trim_rejected.py`：200 组随机 span、更细的行和删除足迹，与逐格判断相比，中间段恰好从第一个到最后一个
  被触及的格子，前后两段都不被拒绝，检查次数不超过 `2⌈log₂ n⌉ + 2`，全部被触及时只检查首尾两格。
- `tests/test_family_plan.py`：1m 从某个整点后 37 分钟开始的后缀；规划的 1m 格子不超过冷启动的边缘格子加 4 个，
  写入后由真实 reader 完整合成。原来的 12 组随机已存状态（真实 reader 合成）照常通过。
- `tests/test_finer_work_hold.py`：10-31 目标在 bench 的已存状态下要取的行少于 100，11-06 16:00 之前没有 1m、5m、15m。
  §10.3 的回归改用分散的 1m 行（12 个），使计划的 REST 请求多于基线。
- 两个后缀测试在 HEAD 上失败；保留本节的修改、去掉 §10.3 的修正时，分散的那个失败。相关的 36 个测试文件与 HEAD 的失败集合相同。

### 11.5 测量

`tools/pairs8.sh`：同一棵树里交替，关闭一边用 `tools/no_trim_run.py` 在任何规划器或 reader 导入之前把 `trim_rejected`
换成整段细化，两边都打开路由规划和 §10 的扣住；各 4 轮，`closed_once`。

| 中位数 | `r20` `net_real` 开 | 关 | `r20` `net_zero` 开 | 关 | `r21` `net_real` 开 | 关 | `r21` `net_zero` 开 | 关 |
|---|---|---|---|---|---|---|---|---|
| 释放后 10-31 目标的运行 | 0.65 秒 | 5.4 秒 | 0.6 秒 | 4.9 秒 | 1.7 秒 | 6.85 秒 | 1.75 秒 | 5.6 秒 |
| 10007m 最后完成的是它（4 次中） | 1 | 4 | 0 | 4 | 0 | 4 | 0 | 4 |
| 四图全部就绪 | 16.3 秒 | 16.0 秒 | 13.0 秒 | 17.3 秒 | 25.3 秒 | 22.6 秒 | 20.1 秒 | 19.2 秒 |
| 进程 CPU | 22.3 秒 | 21.6 秒 | 19.1 秒 | 22.4 秒 | 34.8 秒 | 30.1 秒 | 28.2 秒 | 27.4 秒 |
| 归档下载 | 20 | 26 | 20 | 25 | 20 | 25 | 20 | 25 |

- 释放后的目标快 3–8 倍，不再是关键路径：关闭时全部 16 次加载里它都是 10007m 最后完成的运行，打开时 16 次里只有 1 次。
  现在最后完成的是较旧的 chunk，所以全部就绪时间没有一致的变化；它们主要花在派生的 CPU 上。
- `r20`（负载约 4.5）的关闭一边有 §12 的连续失败（16 次里 3 次，两边都有），`r21` 是修正 §12 之后（负载 7.6–21.9，
  噪声大），两边都没有失败。`r21` 打开一边的全部就绪和 CPU 偏高，与负载最高的几次加载对应；
  单独测量（真实 reader 合成 64 个已存的 10007m 目标）首尾格子的预取只占第一次合成的约 4%（844 对 809 毫秒），
  同样的数据用整段细化的 reader 无法合成。

## 12. 派发的 chunk 继承了派发者的 acquisition scope

### 12.1 现象

§10 扣住的目标偶尔连续失败：一次加载 9 次、4 次，最多一次 165 次（13.6 到 24.8 秒，那时较旧的 chunk 和短周期图
都已结束），每次 5–40 毫秒就以 "canonical dependency range changed during acquisition" 失败，或者派生写入以
"canonical series family changed after acquisition" 失败。开关 §11 的两边都有（`pairs/r20-trim-*`，16 次里 3 次）。

### 12.2 原因

`tools/range_trace_run.py` 记下这些拒绝时的 acquisition scope：被扣住的 11-07 目标的运行用的是 revision 1，也就是
加载开始时的库头。规划时 `check_store_range` 检查目标范围自 revision 1 以来的变化，而短周期图正是在这个范围写了 1m
（这个目标被扣住的原因），所以每次重新规划都失败。

调度器在 `_drain` 里用 `asyncio.create_task` 派发 chunk，它复制调用者的 context；`loop.call_later` 也保留安排它时的
context。`_drain` 在很多地方被调用：另一个运行在自己的 acquisition scope 里 submit，一个 chunk 的 task 结束时，
在这些地方安排的定时器。`fenced_acquisition` 看到已有的 scope 就直接沿用（为嵌套运行设计），所以被派发的 chunk 用的是
别人的 scope：别人的读取起点、`accepted`、已捕获的原生写入视图和 mixed 目标。已有 mixed 目标时 `capture_targets`
不再捕获本 chunk 的目标，派生写入找不到自己的 computation，只能走整个 family 的检查，live 流的 1m 写入就让它失效。
失败的运行在自己的 context 里重新派发，于是一直沿用同一个旧 scope，直到某次派发来自干净的 context。

这不只影响扣住的目标，也不只影响效率：一个 chunk 可能按另一个运行捕获的写入视图被放行。扣住让它常见，因为释放
正好发生在别的运行结束或定时器触发时。

### 12.3 修正

每个 chunk 的 task 都在新的空 context 里创建（`create_task(..., context=contextvars.Context())`）。运行自己取得
acquisition scope；删除权限本来就放在请求的 metadata 里（`acquisition_revision`），不靠 context 传递。会被继承的
ContextVar 还有 mixed/derived 的 computation、memory budget 的 pools 和 leases、历史输入的 adoption 等，现在都不会。

测试（`tests/test_backfill_dispatch_context.py`）：在另一个运行的 scope 里 submit 的 chunk，以及由在 scope 里安排的
定时器派发的扣住目标，运行时都没有 acquisition scope、mixed computation 或 memory lease；修正前两个都失败
（看到 `Acquisition(revision=1)`）。相关的 97 个测试文件（mixed 规划与读取、调度器、coordinator、acquisition、
memory budget）与 HEAD 的失败集合相同，只多出已知的顺序相关测试。

### 12.4 测量

修正之后（`pairs/r21-trim-{real,zero}`，16 次加载，开关 §11 的两边）：10007m 的运行全部一次完成，冲突 0，派发都是 10 次，
没有本地重新规划。修正之前（`r20`，同样 16 次）有 3 次加载出现 9、4、165 次连续失败。
