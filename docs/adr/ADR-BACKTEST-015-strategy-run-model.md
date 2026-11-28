# ADR-BACKTEST-015：统一策略运行模型——一种 Run，模式拆成字段，界面按用途划分

- 状态：Accepted（2026-11-21 用户确认 §7.1：替换 #165 的“三个模式按钮”；2026-11-22 用户确认 O1、O4；2026-11-23 用户确认 O3；2026-11-27 用户确认 O2）
- 实施：P0–P6 已在 2026-11-23 经集成 PR #565 合并到 main（原分步 PR #513–#563）。1.0 不设
  `VITE_CHART_STRATEGY_FOLLOW_ENABLED`（当时默认关闭），图表上的 FOLLOW 界面保持关闭，实时运行走图表
  策略测试器的运行模式（纯历史 / 历史接实时 / 纯实时；仅 Python、仅 1 分钟图表）。1.1 起该开关默认打开
  （2026-11-27 确认 O2 之后）：固定的 Python 结果随新 K 线延伸、原生 Pine 跟随实时 K 线、图表面板为单一
  策略列表并从菜单打开前向跟踪、`forward` 控制命令可用；设为 `0` 回到 1.0 的运行模式。见
  [RELEASE_NOTES.md](../../RELEASE_NOTES.md#chart-strategies-and-live-bars)。
- 日期：2026-11-21
- 基线：`main@aae80d98`
- 修订：[ADR-BACKTEST-002](ADR-BACKTEST-002-host-owned-execution.md)（补充 `authority=SCRIPT` 例外）、[ADR-BACKTEST-013](ADR-BACKTEST-013-CHART-FIRST-STRATEGY-TESTER.md)（图表层不再暴露引擎和模式切换）
- 不替代：ADR-BACKTEST-001、003、011、012、014；[CONTINUOUS_STRATEGY_EXECUTION_20261104_zh.md](../architecture/CONTINUOUS_STRATEGY_EXECUTION_20261104_zh.md)（其持久化、补缺口与修补语义整体归入 FORWARD）
- 关联：#157、#158、#165、#332、#333、#334

## 1. 背景

### 1.1 问题不在功能多，而在维度被编码成了模式

用户对一次策略执行实际只有六个互相独立的选择，但它们在三处被编码成互斥的“模式”：

| 独立选择 | 现在的编码位置 |
| --- | --- |
| 语言（Pine / Python / 内置 / 外部模型） | 研究页 `python` 模式；持续运行只接受 Python |
| 账户由谁维护（宿主撮合 / 引擎自有） | 图表面板 `NATIVE` / `CANDLESCOPE`；`/native` 独立端点族 |
| 撮合精度（ADR-003 五档） | 研究页 `precise` 模式；挂载记录 `fidelityPreference` |
| 时间方式（固定历史 / 跟随行情 / 前向记录） | 图表面板 `HISTORY` / `HISTORY_LIVE` / `LIVE_ONLY`；`/continuous` 独立端点族 |
| 实验形式（单次 / 参数批量 / 走前样本外 / 多市场） | 研究页 `robust` / `multi` 模式；`study.py` 与 `study_v2.py` 并存 |
| 结果的看法（图上 / 报告 / 结果回放） | 研究页 `replay` 模式；后端三套回放读取 |

三组切换分别是：图表面板的 `NATIVE`/`CANDLESCOPE` 与 `HISTORY`/`HISTORY_LIVE`/`LIVE_ONLY`
（`chart-tester/ChartStrategyTesterPanel.tsx`、`chartStrategyPanelPreferences.ts`），以及研究页的
`quick`/`precise`/`robust`/`python`/`multi`/`replay`（`backtest/research/backtestResearchModes.ts`）。

### 1.2 每个组合长成了一条独立竖井

| 环节 | 现有并行实现（`main@aae80d98`） |
| --- | --- |
| 运行端点 | `/backtests/runs`、`/backtests/native/runs`、`/backtests/external/runs`、`/backtests/continuous/runs`、`/backtests/studies` |
| 存储 | `backtest.db`、`native-backtests.db`、`continuous-strategy.sqlite3` |
| 能力查询 | `/backtests/capabilities`、`/backtests/native/capabilities`、`/backtests/continuous/capabilities` |
| 进度传输 | 运行事件流（`/runs/{id}/events`）、前端轮询（`native/nativeRunPolling.ts`、`nativeReplayPolling.ts`）、WebSocket（`continuous.v1`） |
| Pine 执行路径 | `strategy/pine_adapter.py`（仅示例 `pine-long-flat-v1`）、`strategy/pine_engine.py`（`pine-engine-chart-v1`，宿主撮合）、`external.py`（宿主撮合 + 原生账户反馈）、`native.py`（引擎自有账户） |
| 结果回放读取 | `result_replay.py`、`native_replay.py`、`external_replay.py` |
| 撮合核 | `simulation/` 下 9 个 kernel，其中 `pine_bar_kernel.py`、`pine_chart_kernel.py`、`pine_v2_bar_kernel.py` 是 Pine 专用的 K 线撮合变体 |
| 策略代码存放 | 前端 localStorage 草稿（`StrategyDraftStore.ts`）、后端 strategy-revisions/bundles、持续运行内嵌代码、研究挂回经 localStorage 交接（`researchSelectedVersion.ts`）、持续运行引用存 localStorage（`continuousRunReference.ts`） |
| 新旧版本并存 | `study.py`/`study_v2.py`、`pine_workbench.py`/`pine_workbench_v2.py`，均仍被引用 |
| 图表 | 主工作区之外，研究页另有 4 套：`StrategyResearchChart`、`StrategyResearchLiveChart`、`ResearchMarketChart`、`StrategyResultReplayChart` |

### 1.3 后果

- 每个新需求都要在某一条竖井里重做生命周期、进度、结果和回放。#157 即如此：持续运行只存在于
  “SDK Python + 图表 1m + 原生加密 + 杠杆 1、资金费关”这一条竖井
  （`ContinuousStrategyPanel.tsx` 的 `qualified`、`continuous_definition.py`），
  最接近 TradingView 语义的原生 Pine 没有实时路径。
- 同一策略在图表和研究页可能走不同路径，结果一致性只能逐路径验证，原生 plot 只画在报告面板，
  不上主图。
- 违反 #165“全链路经过两个 Manager、页面不直连”：原生组件直接调用 API
  （`NativeStrategyPanel.tsx`、`NativeReplayControls.tsx`、`NativeStrategyComparison.tsx`）。
- 主路径出现引擎、模式、Run 生命周期按钮，违背 ADR-013“主路径零内部术语”的目标。持续运行文案
  “切换品种或周期、移除策略，只会改变当前图表观察的内容”（`continuousMessages.ts`）与图表策略
  的用户预期相反。

## 2. 决策概要

策略执行只有一种对象：**Run**。

```
Run = StrategyVersion × Parameters × InputSpec × ExecutionProfile × ClockPolicy
```

§1.1 的六个选择全部变成显式字段或上层对象：语言属于 `StrategyVersion`；账户维护方与精度属于
`ExecutionProfile`；时间方式是 `ClockPolicy`；实验形式是 `Experiment`（一组 Run）；结果看法只是
前端对 `RunResult` 的不同视图。界面按用途划分，引擎由字段自动选择，用户不再切换模式。

## 3. 领域模型

### 3.1 StrategyVersion

- 内容寻址：`version_hash` 覆盖语言、源码、库、编译器/运行时/适配器身份；参数 schema 由其派生。
- 后端唯一存放，扩展现有 strategy-revisions/bundles。草稿是可变工作副本，也存后端；Run 只引用 hash。
- 用户不管理版本：创建任何 Run 时自动落版本，“命名保存”只是给 hash 起名。这样既满足 #165
  “含实时模式不要求用户创建或选择版本”，又让每个 Run 可追溯到确切代码。
- 语言：`pine`、`python`、`builtin`；外部模型以连接引用表示。不包含 Pyne（§8）。

### 3.2 InputSpec

- 主序列（exchange/market/symbol/interval 与序列身份）、范围 `[from, to)` 或 `[from, live)`、预热条数、
  额外 contexts（`request.security` 等）、执行基础时钟（K 线 / 1m 放大 / aggTrade）。
- 由后端 DataManager 解析为固定前缀回执（现有 `PrefixReceipt` 与 datasets snapshot），按需附加实时
  尾巴。策略输入永不复用图表的可变序列、Store 或订阅（保留 #165 原则）。
- 图表周期是信号周期，1m 是执行基础时钟，二者分离；取代“图表本身必须是 1m”的限制。

### 3.3 ExecutionProfile

- `authority: HOST | SCRIPT`。
  - `HOST`：宿主内核唯一维护订单、成交、账户与报告（ADR-002、ADR-012）。
  - `SCRIPT`：引擎唯一维护账户（目前仅原生 Pine），宿主只校验身份、存档与投影展示；不二次撮合，
    不拼接账本（沿用 `native.py` 与 `docs/NATIVE_STRATEGY_BACKTEST_zh.md` 的规则）。
  - 两者在类型上不可混用：`SCRIPT` 成交不得进入 `HOST` 账本、成本敏感性、练习账户或跨 Run 账本拼接。
- `fidelity`：沿用 ADR-003 五档与报告用语，不新增。
- 账户模型、仓位、费用、滑点、杠杆、funding、执行真实性修订。`SCRIPT` 时这些来自脚本声明，界面只读。
- 默认：Pine → `SCRIPT`；Python、内置 → `HOST`。Pine 的宿主撮合是执行选项，不是独立模式（O4）。

### 3.4 ClockPolicy

| | `FIXED` | `FOLLOW` | `FORWARD` |
| --- | --- | --- | --- |
| 用途 | 研究、实验 | 挂在图表上看、调参 | 前向跟踪、模拟账户 |
| 输入 | 固定快照，止于 `to` | 固定前缀 + 实时尾巴 | 从启动时刻起的实时，可带历史起点 |
| 所有者 | 用户或 Experiment | 图表单元格（租约） | 账户 |
| 生命周期 | 算完即终态 | 无图表持有时停止 | 用户显式停止 |
| 持久化 | 结果不可变、可导出 | 仅按输入身份缓存，不是事实来源 | 代码、参数、检查点、游标与结果（现有 continuous store 语义） |
| 已处理数据被修订 | 不受影响（输入已固定） | 自动重算受影响后缀并在图上提示，无需审批 | `REPAIR_REQUIRED`，按手动确认或自动修补授权处理（#165/#333 原规则） |
| 参数或代码变化 | 新建 Run | 防抖后新建 Run 原子替换；旧结果标 `STALE`，直到新初始结果就绪 | 不允许；变更即新建 Run |
| 换品种、周期 | 不适用 | 跟随图表：取消旧 Run，按新输入新建 | 不受图表影响 |
| 退出与重启 | 已完成结果可读；未完成标 `INTERRUPTED` | 后台不运行；重开时输入身份与前缀回执匹配则从缓存检查点续算，否则重算 | 从最后已提交游标补缺口再接实时；补不齐保持未就绪 |

关键不变量：对确定性、只在收盘 K 线决策的策略，`FOLLOW` 的信号、订单、成交、权益与同输入
`FIXED` 逐条相同。这是 `FOLLOW` 可以“直接重算”的前提，必须由测试保证（§6 P0、P4）。
`FORWARD` 只在三种情况与重算结果不同：盘中执行、非确定性输入（外部模型、墙钟）、已处理数据被修订。
只有这三种情况和模拟账户才需要持久记录。

约束：

- 外部模型不允许 `FOLLOW`，只允许 `FIXED`（逐次决策调用留痕，沿用 `/provider-connections/runs/{id}/trace`）或 `FORWARD`。
  注意命名：`/backtests/external/runs`（`external.py`）是“外部 Pine 引擎 + 宿主撮合反馈”，不是外部模型。
- 形成中的 K 线：`FOLLOW` 可显示未确认预览，从不提交成交；`FORWARD` 不显示预览。盘中逐 tick 执行不在本 ADR 范围。
- `FORWARD` 在信号周期的收盘 K 线上推进（B-333）：任意整分钟的固定长度周期（1m、5m、1h、1d、周一对齐的 1w），
  与同序列、同周期的 `FIXED` 一样消费收盘 K 线，因此同输入结果逐条相同；月周期与带时区的日历周期没有固定长度，不支持。
- #165 原三模式映射：纯历史 → `FIXED`；历史 + 实时 → 看图用 `FOLLOW`，要持久记录用 `FORWARD(from=历史起点)`；
  纯实时 → `FORWARD(from=now)`。

### 3.5 Run 与引擎

- 一个 Run 记录：`run_id`、五项身份哈希、`clock_policy`、`authority`、状态、已提交身份。已提交身份沿用
  `continuous.v1` 的 `generation / revision / checkpoint_revision / sequence / event_time_ms / data_revision`。
- 状态集合取现有各路径状态的并集，按 `ClockPolicy` 约束可达性：`STALE` 只属于 `FOLLOW`，
  `REPAIR_REQUIRED` 只属于 `FORWARD`，`COMPLETED` 只属于 `FIXED`。
- 引擎是实现 `strategy/protocol.py` 中 `StrategyProvider` 的插件
  （`describe / prepare / warmup / step / on_execution_report / snapshot / restore / close`）。
  `FOLLOW` 与 `FORWARD` 要求增量 `step` 和 `snapshot/restore`。`SCRIPT` 引擎另经适配层把自有账户事件
  投影进统一结果，不进入 `HOST` 账本。
- 不支持增量的引擎只开放 `FIXED`，或以前缀重建实现 `FOLLOW` 并声明成本（O1）。
- 引擎由 `StrategyVersion.language` 与 `ExecutionProfile.authority` 决定，能力矩阵声明可用组合。

### 3.6 Experiment

- 一组 `FIXED` Run，加生成规则（参数网格、多份 InputSpec、走前分折）和选择规则。
- 新建只用 Study V2 身份（ADR-011）；V1 Study 保持只读，不被新实现重新解释。
- 参数稳健性、多市场、批量运行（`strategyResearchBatch.ts`）都表达为生成规则，不再是页面模式。

### 3.7 RunResult 与揭示读取

- 统一结果结构 `RunResultV1`：orders、fills、positions、equity、plots、drawings、logs、rejections、summary，
  附已提交身份与 `authority` 标签。plots 复用指标视图合同（`features/indicators` 的
  `mainOverlayLines / subPanes / markers / fills / hlines / bgcolors`），只共享渲染合同，不共享指标计算运行时。
- 后端为现有 report、原生结果、continuous 分页各写一个投影适配器，不改写旧库。
- 结果回放 = 对任意 Run 的已保存结果按前缀揭示，合并三套回放的读取侧。需要推进引擎会话的交互回放
  （原生 `FIXED_HORIZON_INCREMENTAL`）是 `FIXED` Run 上的步进控制，二者分开（与 #334“区分推进计算与查看已保存结果”一致）。

### 3.8 传输与能力

- 所有 Run 经前端 `StrategyDataManager`（MarketDataManager）与后端 DataManager；组件不直接调用运行 API。
- 统一流协议由 `continuous.v1` 推广：HTTP 取初始结果，WebSocket 推增量，带已提交身份，按 generation
  拒绝旧代结果。`FIXED` 也走它（进度与终态），取代前端轮询。
- 一个能力矩阵，按 language × authority × fidelity × clock_policy × market 声明支持，取代三个
  capabilities 端点。前端只据此禁用选项，不再自行写死资格判断。

## 4. 界面

| 界面 | 做什么 | 使用的对象 |
| --- | --- | --- |
| 图表 | 挂策略、看图、调参 | 默认 `FOLLOW`；“前向跟踪”显式创建 `FORWARD`，其成交作为独立图层叠加 |
| 研究工作区 | 批量、样本外、多市场、导入数据、结果比较 | `Experiment` 与单个 `FIXED` |
| 账户 | 所有前向跟踪与模拟账户 | `FORWARD` |
| 回放 | 任意 Run 的结果回放 | 统一揭示读取器 |

三处共用一个图表表面、一个 `StrategyOverlay`（plots、进出场标记、持仓线、挂单线）和一套
`RunResultViews`（概览、绩效、交易列表、属性）。ADR-013 的运行时隔离保留：共享组件与合同，
不共享 store、WebSocket、chart-session 或 Run 状态。

旧切换的去向：

| 旧 | 新 |
| --- | --- |
| 图表 `NATIVE` / `CANDLESCOPE` | `ExecutionProfile.authority`（Pine 默认 `SCRIPT`） |
| 图表 `HISTORY` | 图表上为 `FOLLOW`；要固定结果时“在研究中打开”，创建 `FIXED` |
| 图表 `HISTORY_LIVE` | `FOLLOW`（看图）或 `FORWARD(from=历史起点)`（要持久记录） |
| 图表 `LIVE_ONLY` | `FORWARD(from=now)` |
| 研究 `quick` | 研究工作区默认：单个 `FIXED` |
| 研究 `precise` | `ExecutionProfile.fidelity` |
| 研究 `robust` | `Experiment`（参数生成 + Study V2） |
| 研究 `python` | 不是模式，是 `StrategyVersion.language` |
| 研究 `multi` | `Experiment`（多份 InputSpec） |
| 研究 `replay` | 任意 Run 的结果视图 |

不并入：正式回放 `TrainingRun`（ADR-001）；练习账户 `trading_accounts` 与 FORWARD 账户的关系待定（O3）。

## 5. 现有代码的归属

| 现有 | 归入 |
| --- | --- |
| `/backtests/runs`、`service.py`、`runtime.py`、`repository.py` | `Run(FIXED, HOST)` 适配器 |
| `/backtests/native/runs`、`native.py` | `Run(FIXED, SCRIPT)` 适配器 |
| `/backtests/native/replays`、`native_replay.py` 的步进侧 | `FIXED` Run 的引擎步进控制 |
| `/backtests/external/runs`、`external*.py` | `Run(FIXED, HOST)`，provider 为 Pine 反馈 |
| `strategy/pine_engine.py`、`strategy/pine_adapter.py` | `HOST` 下的 Pine provider；示例 provider 只保留为模板 |
| `/backtests/continuous/*`、`continuous_*.py` | `FORWARD` 的实现基础；其 bar host/source 推广为 `FOLLOW` 与 `FORWARD` 共用的实时推进器 |
| `/backtests/studies`、`study.py`、`study_v2.py` | `Experiment`（新建仅 V2，V1 只读） |
| `result_replay.py` 与 `native_replay.py`、`external_replay.py` 的读取侧 | 统一揭示读取器 |
| 三个 capabilities 端点 | 一个能力矩阵 |
| `simulation/kernel.py` 与三个 Pine 专用 K 线核 | 收敛为一个 `HOST` K 线撮合核（P6）；`trade_kernel`、`dual_clock_kernel`、`book_kernel`、`depth_kernel`、`sampled_book_kernel` 作为不同成交时钟保留 |
| 前端 localStorage 草稿、研究挂回交接、持续运行引用 | 后端 `StrategyVersion` 与 Run 引用（P3） |
| 研究页 4 套图表、`BacktestResearchApp` | 共享图表表面与研究工作区（P5） |

## 6. 迁移步骤

逐步替换：每步可单独合入，新功能放在 flag 后（沿用 ADR-013 的做法）。旧端点只在新入口替代且
对照证据一致后删除。P1 与 P3 互不依赖，可在 P0 之后并行。

| 步骤 | 内容 | 门槛 |
| --- | --- | --- |
| P0 对照基准 | 为每条现有路径（宿主 BAR、宿主 aggTrade 双时钟、宿主 Pine 引擎、外部 Pine 反馈、原生 Pine、持续 Python）固定输入，记录信号、订单、成交、权益摘要；补齐 FIXED 与分批推进的等价测试 | 在 CI 运行；后续步骤不得改变摘要，除非 ADR 记录了语义变更 |
| P1 统一结果与渲染 | `RunResultV1` 与后端投影适配器；前端 `StrategyOverlay`、`RunResultViews`，图表面板和研究页同时换上；原生 plot 画到主图 | P0 摘要不变；视觉评审通过 |
| P2 统一 Run 门面 | 统一运行端点（命名待定）、能力矩阵、统一流协议；所有 Run 经两个 Manager；旧端点降为适配器 | 架构测试禁止组件直接调用运行 API；前端轮询消失 |
| P3 策略版本收口 | 内容寻址版本与后端草稿；现有 localStorage 草稿、挂回交接和持续运行引用一次性导入后端，原数据保留 | 完全退出并重启后，草稿、图表挂载和运行引用均可恢复 |
| P4 FOLLOW 与图表 | 从持续运行抽出实时推进器，支持任意信号周期（1m 基础时钟）与 Pine；图表面板改为一个策略列表；两组切换下线；“前向跟踪”创建 `FORWARD`。按 O1 拆为：P4a `SCRIPT` 的 `FOLLOW`（前缀重建）；P4b `HOST` 的 `FOLLOW`（实时推进器，任意信号周期）；P4c 策略列表、切换下线与“前向跟踪” | 同输入 `FOLLOW` 与 `FIXED` 逐条相同；换品种、周期、参数的行为符合 §3.4；#157 新验收 |
| P5 研究工作区 | 在共享图表与结果组件上重建；模式改为字段；`Experiment` 承接批量、稳健性、多市场；删除 `BacktestResearchApp` 与研究页自有图表；`backtest.html`、`local.html` 保留重定向。按依赖拆为：P5a 交易所数据作为工作区输入（序列 + 固定范围，显示准备进度、失败与重试，不再经旧高级研究页）；P5b `Experiment`（批量、多市场、稳健性生成一组 `FIXED` Run，后端持有与恢复）；P5c 模式改为字段，研究工具的功能迁入工作区（撮合精度档位与运行配置、语言定引擎、结果比较与信号追踪、结果回放与训练回放、运行列表、版本与快速试运行、外部模型连接），不删除功能；P5d 删除 `BacktestResearchApp` 与研究页自有图表（统一到 `MarketChartSurface` 与 `StrategyOverlay`），`?context`、`?run`、`?study`、`?compare`、`?mode` 深链在工作区打开 | #332 验收；旧深链可打开 |
| P6 撮合核收敛 | 三个 Pine 专用 K 线核并入 `HOST` K 线核；评估与练习账户共用账户模型（O3）；旧核先留作对照，摘要一致后删除。按依赖拆为：P6a 内核级对照摘要，覆盖每个账户模型 × 成交时钟（含三个 Pine 专用核），作为本步门槛的依据，不改行为；P6b 一个 `HOST` K 线核：Pine OHLC 路径、图表 K 线生命周期与 V2 路径成为 K 线核声明的成交时钟（`bar_clock`），对照为 P6a 由旧核算出的摘要与沿用旧类名的既有测试，摘要与检查点载荷逐一一致，已存检查点仍可恢复；旧类名暂作只设时钟的子类；P6c 调用方（`service.py`、`external.py`、Pine 工作台、成本敏感性）切到 `HOST` K 线核，删除三个 Pine 专用核；P6d 宿主 Pine 引擎的盘口数据路径（`chart_book.py`）并入外部反馈路径（P5c4c 已定：盘口精度只在 Pine 面板的 CandleScope 撮合）：新建的宿主 Pine 盘口 Run 显式拒绝并指向 CandleScope 撮合，能力矩阵的宿主 Pine 不再列出盘口精度；已存的 Run 照常执行、续算与读取；内置与 Python 策略保留宿主盘口路径；P6e 账户模型共用（O3，2026-11-23 用户确认以练习账户规则为共用模型）：P6e1 练习撮合对照摘要（单向/双向持仓、毛保证金购买力、挂单与括号单、形成中 K 线的增量路径）；P6e2 练习账户模型与 K 线路径原样移入 `app/simulation`，练习账户改为调用；P6e3 `HOST` 内核获得该账户模型与成交路径，`FIXED` 与 `FORWARD` 可用且逐条一致；P6e4 前向跟踪在该模型上运行，账户页把前向跟踪与练习账户并列，各自账本；现有 Run 与练习账户的结果不变 | 每个账户模型 × 成交时钟的 P0 摘要一致 |

## 7. 对现有需求与 issue 的影响

### 7.1 需要确认的需求变更

#165 的“纯历史 / 历史 + 实时 / 纯实时三个模式按钮”被替换：用户不再选模式。图表默认 `FOLLOW`，
“前向跟踪”显式创建 `FORWARD`，研究工作区只创建 `FIXED` 与 `Experiment`。#165 的其余原则全部保留：
输入快照隔离、两个 Manager、历史与实时交接无遗漏无重复、修补需确认或授权（仅 `FORWARD`）、
检查点后缀重算。**用户已于 2026-11-21 确认此项，本 ADR 转为 Accepted。**

### 7.2 建议的 issue 重新划分

| issue | 对应 |
| --- | --- |
| #157 图表策略 | P4：`FOLLOW` 语义与图表体验 |
| #158 图表与研究双向流转 | P3 + P5：版本与参数在图表、研究间流转 |
| #165 策略工作区总议题 | 按 §7.1 更新三模式条款，其余不变 |
| #332 策略工作区 | P5 |
| #333 持续策略 | `FORWARD`：交接、修补、检查点与退出恢复条款不变；“三种启动模式”条款按 §7.1 改写（纯历史归 `FIXED`） |
| #334 策略结果回放 | P1、P2 的统一揭示读取器 |

### 7.3 对既有 ADR 的修订

- ADR-002：`authority=SCRIPT` 是唯一允许的例外，仅限声明了自有账户语义的原生引擎；`SCRIPT`
  结果永不进入 `HOST` 账本。其余插件仍只输出 `SIGNAL` / `TARGET_POSITION` / `ORDER_INTENT`。
- ADR-013：保留双层体验、每单元格运行时隔离、`STALE` 语义和“无授权不联网补数据”。图表层不再
  暴露引擎和模式切换；`FOLLOW` 在 `STALE` 之后自动重算，不等用户点击运行；需要下载数据时仍进入
  `NEEDS_DATA` 并等待授权。

## 8. 约束

- Pyne 已退役（`AGENTS.md`）：统一 provider 接口不包含 Pyne；`native-backtests.db` 中既有 Pyne 记录
  只读保留；新建 Pyne 请求显式拒绝，不迁移、不改标签为 Pine 或 Python。
- 保留用户数据与历史 QA 证据：迁移只增加适配与导入，不删除旧库、旧记录或旧证据。
- 共享基础设施保持语言中立；Pine、Python、前端 JavaScript 指标与社区插件各自的合同不变。
- 不新增语言、市场或精度档位；ADR-003 的精度用语不变。
- 正式回放 `TrainingRun` 不并入（ADR-001）。

## 9. 开放问题

- **O1 原生 Pine 的实时追加。** 现有 `FIXED_HORIZON_INCREMENTAL` 在创建时固定区间，`barstate.islast`
  等按完整区间计算（`docs/NATIVE_STRATEGY_BACKTEST_zh.md`）。`FOLLOW` 需要引擎支持区间延长与实时柱
  语义。在此之前，`SCRIPT` 的 `FOLLOW` 只能用“每根收盘做前缀重建”并设条数预算，或暂不开放。
  **已确认（2026-11-22）：每根收盘做前缀重建。** `SCRIPT` 的 `FOLLOW` 在每根信号周期 K 线收盘后，
  对最新前缀新建一次 `FIXED` Run，并原子替换图上的结果；因此与同输入 `FIXED` 逐条相同（§3.4 不变量
  直接成立），`barstate.islast` 等按该前缀的语义计算。引擎支持区间延长与实时柱后，再改为增量推进。
  **增量推进（B-157a，2026-11-27）：** 引擎补丁 `host-contracts-v6.patch` 给固定历史会话加了区间延长
  （`HistoricalSession.extend`）：会话推进到终点后可接上后续收盘 K 线，结果与一次给出全部 K 线逐条相同。
  运行时声明 `follow_session`（`candlescope.pine-follow/1`）后，宿主为每个被跟随的用户 Run 保留一个引擎会话
  （`backend/app/backtest/native_follow_sessions.py`，最多 4 个，空闲 15 分钟关闭）；新一次重建若只是上一次
  输入多了后续 K 线，就延长该会话，只执行新 K 线；否则新开会话。每次重建仍是一个普通 `FIXED` Run，结果与
  同输入 `FIXED` 逐条相同（§3.4）。脚本在较早 K 线读取数据终点（`barstate.islast`、`last_bar_index`、
  `timenow` 等）、用 `calc_bars_count`、或带上下文/放大镜/边界/交易时段等随 K 线冻结的输入时，运行时不开会话，
  继续整段重建；任何会话失败都回落到整段重建。可延长时，图表保留上一次重建的起点（窗口最多到预算的两倍，
  即 10,000 根），之后从最新 5,000 根重新开始，每 5,000 根收盘只整段重建一次；不可延长时仍按 5,000 根滑动。
- **O2** `FOLLOW` 的默认条数预算、缓存容量与淘汰规则。建议默认值（P4 实测后确认）：
  - `SCRIPT` 前缀重建每次最多 5,000 根信号周期 K 线（取最近的），超出部分不参与该次重建；
  - 同一单元格同时只算一次重建，期间收盘的 K 线合并进下一次，不排队；
  - 按输入身份（代码、参数、前缀回执）去重：相同输入复用已有 Run，不重算；
  - 每个工作区保留最多 8 个 `FOLLOW` 结果，按最近使用淘汰；没有图表租约即停止，不在后台运行；
  - `HOST` 的 `FOLLOW` 用增量 `step`，窗口上限 20,000 根。

  **已确认（2026-11-27）：**
  - `SCRIPT` 前缀重建上限保持 5,000 根（`frontend/src/features/backtest/follow/scriptFollow.ts`）。
  - 8 个结果的上限此前没有实现：每次 Pine 重建都作为普通原生 Run 永久保存（1m 图表每天约 1,440 个）。
    现在每次重建在请求头 `Strategy-Follow-Of` 中写明它重建的用户 Run（基准，不进入 Run 的输入）；原生 Run
    库对每个基准只保留最新一次已完成的重建、仍在运行的重建，以及比它更新的最近一次失败；最近活跃的 8 个
    基准保留结果，更早的基准删除其重建，图表回到用户自己的 Run（`backend/app/backtest/native_follow_results.py`）。
    用户自己的 Run 永不删除；有回放引用的重建转为用户的 Run 保留；相同输入共用的重建在任一基准仍显示它时保留。
    重建不出现在 Run 列表中，也不登记策略版本（基准已登记）。
  - Python（`HOST`）的实时 `FOLLOW` 每个后端最多 16 个，第 17 个拒绝（`FOLLOW_CAPACITY_EXCEEDED`），不改为淘汰。
  - `HOST` 窗口保持现状：起点最多回溯 20,000 根；累积到 40,000 根时从最新 20,000 根重新计算（约每 20,000 根
    新 K 线一次，1m 约 14 天），不改为每根滑动。
- **O3** `FORWARD` 账户与练习账户（`trading_accounts`，#500 刚加入对冲模式）是同一对象还是互相引用。
  **已确认（2026-11-23）：共用账户模型，各自账本。** `FORWARD` Run 与练习账户用同一账户模型（保证金、费用、单向/双向持仓、成交路径），各自保留账本：策略成交永不进入手动练习账户的账本、交易与日志；账户页把前向跟踪与练习账户并列展示。共用模型采用练习账户规则（单向或双向持仓、按毛名义价值计保证金、Maker/Taker 费用、K 线路径成交）；前向跟踪改用该模型后按练习账户的方式成交，现有 `FIXED` 与已运行的 `FORWARD` 结果不变。
- **O4** Pine 的宿主撮合（`pine-engine-chart-v1`、外部反馈）作为执行选项保留在图表层，还是只在研究工作区出现。
  **已确认（2026-11-22）：图表层保留一个执行选项。** 图表上的 Pine 策略在“成交与账户”设置中选择“按脚本设置”
  （`SCRIPT`，默认）或“CandleScope 撮合”（外部反馈路径，`HOST`）。图表的 Python 策略位不再切换为 Pine，
  因此 `pine-engine-chart-v1` 不再作为新的图表入口；已保存在该位置的 Pine 草稿仍可打开和运行，不迁移、不删除。
  研究工作区的执行选项在 P5 决定。
- **O5** P2 只建统一索引与适配；是否最终合并 `backtest.db`、`native-backtests.db`、`continuous-strategy.sqlite3`。

## 10. 后果

正面：

- 每个关注点只有一条实现路径，新需求只做一次；图表与研究页的结果由同一路径产生。
- `FOLLOW` 让图表策略获得 TradingView 式行为，持久化与修补的复杂度只留在 `FORWARD`。
- 主路径不再出现引擎、模式和 Run 生命周期按钮。

代价与风险：

- 迁移规模大：后端 `app/backtest` 约 3.8 万行（`service.py` 单文件约 5.9 千行），前端
  `features/backtest` 与 `features/strategy-research` 约 2.2 万行。
- P0 对照基准是硬前提；没有它，P1 之后的任何一步都无法证明财务结果未变。
- 适配期内新旧入口并存；正在其他工作树推进的相关工作（例如原生验收、持续策略验收）会与本迁移冲突，需要按步骤协调合入顺序。
