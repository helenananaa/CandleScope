# 按路由规划 mixed 回填（Route-aware mixed planning）设计

状态：已实现并默认打开（`mixed_routes.ROUTE_AWARE = True`，设为 False 即回到原来的规划）；验收见 §8 第 5 步
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

本设计只解决 A。B 单独处理（§9）。

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

- B（最新 chunk 与短周期图重叠），见 §9。
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
   剩下的 10007m 冲突是 B 类（§9.3），每次加载仍有一次最新的稠密 chunk 的 `refined_source_row_budget` 拆分，与今天相同。
   全量后端测试（约 10,700 个，跳过两个在本环境无法收集的文件：缺 `jsonschema`，以及 `test_review_regressions.py`
   引用了已删除的名字）：开关关时与 HEAD 失败集合相同（多出的 `test_amendment_inside_a_partly_consumed_native_window_stops_its_remaining_pages`
   在 HEAD 上单独跑 4 次都失败，是已有的不稳定测试）；强制打开时只多出检查关闭行为的 `test_without_the_flag_the_plan_is_unchanged`。
   §7 的五项都满足，开关已默认打开；该测试现在自己关掉开关。）

## 9. 待决定

1. **导入对象的阈值**：沿用路由现在的阈值（建议），还是对本 chunk 独有的对象更积极地导入（减少 REST，增加写入行数）。
2. **短周期图**：冷启动时它们是单一底层 1m 的 chunk，相邻 chunk 共享日度 1m 对象，也有重新规划（每次加载 4–15 次）。
   本设计稍作推广（单一底层计划也带目标范围）即可覆盖，建议作为第二步。
3. **B 的处理**：让最新的 10007m chunk 在与它重叠的短周期图 chunk 完成后再规划（小改动，去掉约 6 个冲突），
   可以与本设计并行做，也可以等本设计完成后再看是否仍需要。
