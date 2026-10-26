# 交易账户、交易笔记与轻量复盘设计草案

- 初稿日期：2026-10-16。
- 初稿代码基线：`5b4cd84ba2ec13217e83c112afb8bcaacd12d02d`，作为历史设计背景保留。
- 状态更新日期：2026-10-21。
- 实现对照：[PR #68](https://github.com/helenananaa/CandleScope/pull/68)，核对代码提交 `50488b049637e5f988b7cced488e762ae0b3f727`。
- 需求入口：[Issue #23](https://github.com/helenananaa/CandleScope/issues/23)。

## 当前实现状态与设计边界

本文保留完整产品设计，同时区分 PR #68 当前已有代码与后续要求；新增这份文档不扩展该 PR 的功能范围，也不代表 Issue #23 的交易所连接器已经交付。

| 设计范围 | PR #68 当前状态 | 后续边界 |
| --- | --- | --- |
| 账户入口 | `practice` 本地虚拟资金账户与 `manual` 手工成交账户可创建。`manual` 是外部交易事实的手工记录来源。 | `exchange_readonly`、`exchange_trading` 是规划类型，尚不可创建；真实同步与执行仍需独立连接器和验收。 |
| 模拟撮合 | 由实时 1m K 线驱动，支持市价、限价、止损及保护单；历史缺口进入追赶状态。 | 当前不模拟资金费、强平、盘口深度和部分成交。下文完整财务与产品规则仍是后续要求。 |
| 计划与笔记 | 三阶段记录、事后补记标识、首笔成交时锁定初始风险、快照图片和逐账户统计已有代码。 | 所有账户共用笔记的原则延续到未来连接器；不能据此声称真实交易所账户已接通。 |
| 轻量复盘 | 图表单元内使用统一游标裁剪 K 线、成交、笔记、持仓、盈亏与指标；更细 K 线用于重建形成中 K 线。 | 当前绘图隐藏，以快照图片保留当时画面。完整结构化上下文还原、多图共同游标等条目仍是设计目标。 |
| 成交数据导入 | 支持手工填入成交。 | CSV 导入和交易所历史/实时同步未在本次实现。 |

状态对照来自[后端模块说明](../backend/app/trading_accounts/README.md)、[前端模块说明](../frontend/src/features/trading-accounts/README.md)、[账户类型契约](../backend/app/trading_accounts/models.py)和[复盘游标模型](../frontend/src/features/trading-accounts/quickReplayModel.ts)。以下章节的完整需求用于后续实现与验收，不替代逐项运行证据。

## 1. 产品定义

在实时行情页侧边栏加入「交易账户」。用户选择账户后，可以看持仓与成交、写交易计划和笔记，并从任意决策节点进入轻量复盘。日常使用始终围绕当前行情图，不要求先创建训练任务。

产品中的三种账户入口分别是「模拟账户」「交易所 · 只读」「交易所 · 可交易」。不要把总入口叫「实盘账户」：完全模拟账户也在这里。

### 账户类型

| 类型 | 行情与资金 | 可做的事 | 必须持续显示 |
| --- | --- | --- | --- |
| 模拟账户 | 默认实时行情，本地虚拟资金 | 模拟下单、持仓管理、记录笔记、复盘、训练 | 模拟、账户名称、撮合状态 |
| 交易所 · 只读 | 交易所真实账户 | 同步成交、持仓与费用，写笔记和复盘 | 实盘只读、交易所、同步状态 |
| 交易所 · 可交易 | 交易所真实账户 | 同步成交、持仓与费用，写笔记和复盘，并可在支持范围内下单、改单、撤单 | 实盘可交易、账户、交易所、执行状态 |

交易笔记是所有账户共用的基础能力。模拟账户、交易所只读账户、交易所可交易账户均可完整使用开仓前、持仓中、平仓后记录，以及模板、自动填写、图表快照和快速复盘。只读限制的是交易所资金与订单动作，不限制本地笔记的创建、编辑和保存。

模拟账户不是交易所测试网。将交易所环境 production/demo 单独保存；测试网账户必须显示测试网标识，不能归入本地模拟账本。

账户与行情时钟分开：本地模拟账户可以在实时行情中持续练习，也能通过单独训练实例做历史训练；真实账户进入历史视图时仅查看历史事实。三者复用笔记和图表界面，但执行能力、订单与账本隔离。账户切换不能继承上一账户的下单授权或未发送订单草稿。

创建时选定交易所、产品与结算币种，后续不能通过改名称把现货账本变成永续账本。初始可开多个模拟账户；只读连接器首版仍按 issue 限定一个交易所、一个账户、一种产品。

## 2. 信息架构与交互

沿用现有右侧活动栏与主题 token，新增「交易账户」入口，不另建一套首页。

账户面板顶部：账户选择、模式标识、同步状态、添加账户。其下四个页签：

- 持仓：当前仓位、实际均价、未实现盈亏、计划止损/目标；点击定位图表。
- 交易：按交易组查看开仓、加仓、减仓、平仓，支持筛选。
- 笔记：未成交计划、待补复盘和全部记录；支持「当前账户 / 全部账户」筛选，跨账户列表明确显示每条笔记所属账户。
- 概览：净收益、R 分布、执行偏差与标签统计；默认只统计当前账户。

下单区仅在本地模拟或已开放执行的交易所账户显示。只读账户显示同步与记录入口，不出现可操作的下单表单。

点击一笔交易，图表定位到该交易，侧栏切换为详情：交易事实摘要、三阶段笔记、事件时间线和「快速复盘」。长模板在宽抽屉中编辑；窄侧栏只放摘要和快速记录，避免挤压图表。

快捷动作：

1. 图表上「写计划」：预填品种、周期、时间和图表状态，不要求已有成交。
2. 持仓行「记一笔」：追加一句话，默认阶段为持仓中。
3. 已平仓行「完成复盘」：打开结果与结论，自动事实已填好。
4. 「快速复盘」：进入独立历史图表视图，可一键回到实时行情。

订单状态与持仓事实来自所属账户；笔记不是订单指令。修改「计划止损」仅创建新计划版本。要实际修改委托，必须经过单独的订单动作。

## 3. 以交易组关联计划和笔记

结构关系：账户 → 原始成交/资金流水 → 交易组；计划和笔记可以独立存在，再关联交易组或具体成交。

交易组默认按账户、产品、合约、持仓方向与从空仓到再次空仓的生命周期归组；双向持仓分别处理。反手成交拆分为旧交易的平仓部分与新交易的开仓部分；保留同一原始成交引用和数量/费用分摊，避免重复计数。多次加减仓属于同一生命周期。

用户可调整分析分组及计划关联，但必须保留原始关系与调整记录，不能改写交易所事实。数据覆盖起点以前已存在的仓位显示「起始持仓信息不全」，不能伪造开仓价格和完整盈亏。

未成交或放弃的计划也值得保留。不要根据相同币种静默把所有计划和成交合并；有多个候选计划时由用户选择关联。

## 4. 笔记与模板

所有账户使用相同的笔记入口、编辑器与模板，不因账户是否支持下单而隐藏。尚未成交时可以先写计划；交易所断连或同步失败时仍可写本地笔记，依赖同步的自动字段保留来源和时效状态。笔记与所属账户关联，查看全部账户不会合并或改写各账户账本。

三阶段是编辑体验，底层使用带时间的追加记录：

- 开仓前：依据、预期、失效条件、风险预算。
- 持仓中：观察、操作理由、计划变更、情绪与执行偏差。
- 平仓后：实际结果、执行比较、复盘结论。

快速记录默认只需要一句话。完整模板、结构化字段与 Markdown 导出共用同一份内容，不产生两份需要同步的文本。

### 默认完整模板

【交易信息】
账户 / 来源：自动
记录时间 / 对应市场时间：自动，分别保存
交易标的 / 方向 / 周期：自动或计划填写
策略标签：可复用最近标签
计划入场 / 初始止损 / 目标价：用户填写，可从图上选价
计划风险 R（USDT）：用户填写，适用产品下提供估算
实际成交均价 / 数量：成交后自动

【开仓前】
市场环境：趋势 / 震荡 / 不确定
入场依据：
预期如何演化：
假设失效条件：
什么情况下不做这笔交易：

【持仓中】
观察与判断：
本次动作 / 理由：
计划是否改变：
新的止损 / 目标 / 风险预算：
当前情绪或执行偏差：

【平仓后】
实际毛收益 / 净收益：自动，注明币种与口径
实际净收益（R）：满足原始风险条件时自动
MFE / MAE：可计算时自动，注明粒度与估计性质
手续费 / 资金费：同步或模拟账本计算
滑点：存在有效比较基准时计算，否则留空
是否遵守交易计划：是 / 部分 / 否 / 无事前计划
实际决策与原计划的差异：

【复盘结论】
好决策：
错误或待验证的问题：
下一步检验的假设：

额外内置「30 秒简记」「持仓检查」「收盘复盘」三个短模板。支持自定义、另存为模板、默认模板和占位变量（如 symbol、interval、entry_price、net_pnl）。模板实例记录模板版本；更新模板不重写历史笔记。

### 自动填写规则

自动事实、用户判断和估算值明确区分。自动字段显示来源和更新时间，允许添加备注，不能靠改笔记覆盖成交事实；来源数据修正后留下修订痕迹。

计划记录 created_at、effective_market_time、updated_at 与版本。开仓后补写的「开仓前」内容标为事后补记；选了过去的市场时间也不能改变实际创建时间。原始计划和开仓时采用的风险版本被冻结，后续移动止损不重算历史 R 分母。

净 R = 已归属的净收益 / 事前锁定的初始风险。没有有效初始风险时显示「—」，可另做明确标识的事后估算，不能混入正式 R 统计。首版建议先支持单次初始开仓的 R；加仓交易在风险预算和分摊规则确定前只显示金额收益或标明不可比较。

线性 USDT 产品可用数量 × 入场与止损价差估算价格风险，另列预期费用；不要对反向合约或不同合约乘数套用同一公式。资金费保留正负号；多币种费用需要可追溯的换算时点与价格。无法归属或缺失的费用标为未知，净收益标为暂估。

MFE/MAE 首版优先展示持仓区间内的最大有利/不利价格变化；仓位变化时，金额口径需要按实际仓位路径计算，不能直接乘最终数量。OHLC 无法给出精确盘中路径与边界时点，标为区间估计。滑点以明确的决策价、委托价或可用基准价计算，不以任意 K 线收盘价代替。

自动保存有「保存中 / 已保存 / 失败」状态；账户、图表切换及崩溃后恢复已保存内容。原有文字不会被再次自动套模板覆盖。

## 5. 轻量复盘

### 范围

快速复盘是带时间游标的历史图表查看器，读取已发生的成交与记录。它不撮合、不推进账户、不创建 TrainingRun，不依赖完整训练引擎。

账户同步继续在后台运行；复盘视图使用独立、固定版本的数据源和时间游标，不会因实时推送跳到现在。退出时恢复原来的实时图表布局与视口。与原页面分离的复盘实例不能读取当前实盘余额并把它当作历史余额。

### 操作

- 默认「开仓前」：定位首次成交之前最后一根已完成 K 线，并保留足够历史上下文。
- 「开仓时」：有当时快照时恢复对应状态；无快照时使用明确标识的历史重建。
- 上一根 / 下一根、前进 5 根、播放/暂停、倍速。
- 上一个 / 下一个事件：计划、成交、加减仓、笔记、平仓。
- 周期切换、回到起点、查看完整结果、返回实时行情。
- 「另开训练」是独立入口，后续复用完整训练系统，在新模拟实例中练习。

交易在 10:23 开仓，图表周期为 1 小时：不能直接显示 10:00–11:00 的最终高低收与成交量。如果没有 10:23 的局部快照或更细数据，只显示截止 10:00 之前的完整 K 线，并说明盘中状态缺失；可主动选择近似视图，但标识一直可见。逐根前进按当前周期的下一完成边界推进，跳事件则推进到该事件时点。

### 「隐藏未来 K 线」的正确边界

未来数据可在本地后台预取；传入图表和指标的输入必须限定在游标可见范围。用数据投影裁剪，而不是 CSS 遮盖或只限制图表横向范围：

1. 主图、副图、十字光标、价格轴和自动缩放只接收可见数据。
2. 指标基于可见前缀计算；回退时恢复或重算状态。需要预热的历史可以向过去加载。
3. 更高周期 K 线、成交量聚合、订单流等遵守同一截止点；没有当时快照的实时盘口不展示成历史盘口。
4. 交易标记、笔记、绘图与计划版本按当时已存在的版本过滤。未来确认的拐点或重绘指标不能提前显示。
5. 盲看默认隐藏最终盈亏、平仓点、事后结论与后续时间线文字；用户主动「查看完整结果」后再展开。已知结果也能使用本工具，但不能因此称为盲测。
6. 所有多周期图共享一个市场时间游标，不按各图分别推进一根造成时间错位。
7. 每个复盘实例固定数据版本；后续补数另开新版，不静默改变当前复盘。

复用现有 MarketChartSurface 与 FROZEN_SNAPSHOT 边界，增加独立的截止时间投影适配器。现有冻结数据源只保证不可变，并不自动保证游标以后的数据不可见。实现时应让图表、指标与覆盖层统一读取同一个截止投影。

可加载有界时间窗口并分块缓存，不复制数年历史；首次定位只取足够预热的前缀。相邻前进可增量计算，回退可以先采用前缀重算。先测打开与单步延迟，再决定是否需要指标检查点，不把性能方案预设为训练引擎级别。

### 精确还原与历史重建

- 当时快照：保存截图、局部 K 线、指标版本/参数/必要状态、绘图版本、视口、时区、交易标记、计划版本与数据身份。校验相符才标为当时状态。
- 历史重建：使用当前可获取的历史行情与可用上下文，明确标为重建；指标版本不同、数据修正或缺少局部 K 线时继续提示。
- 只导入成交：可以回到成交时间，但不能找回当时未保存的想法、绘图或指标设置。

关键节点可自动保存快照：提交计划、收到开仓成交、加减仓、平仓及手动记笔记。软件离线时发生的成交，回填后仅补事实，不生成伪造的当时截图。截图提供视觉证据；结构化状态提供可交互回看。

## 6. 技术边界与复用

基础参考沿用初稿检查结果；PR #68 新增的账户、笔记与轻量复盘实现以上方状态表及对应模块说明为准：

- frontend/src/app/RightMarketRail.tsx、marketRailTypes.ts：已有侧边栏描述与面板框架，新增内置账户视图。执行动作属于宿主能力，不能让普通插件仅凭替换视图获得。
- frontend/src/styles/tokens.css：沿用表面、文字、状态色、字号与间距；账户模式同时用文字说明，不只用颜色。
- frontend/src/features/market-chart-platform/：已有实时引用、冻结快照与运行结果边界；可复用图表，不需要引入训练账户。
- backend/app/plugin_live_v2/accounts.py：现有证明契约限定 OKX demo spot，不等于生产只读账户或永续同步已经实现。
- backend/app/plugin_live_v2/vault.py：当前有 Windows DPAPI 与测试 fake 后端；其他桌面平台的凭证存储需另补。
- backend/app/replay/training/review_service.py：现有 ReviewMode 绑定训练，要求原训练暂停或结束。参考时间线交互，但核心交易笔记不能依赖它。
- 现有模拟/回放 broker 的产品规则和财务计算值得复用；实时模拟撮合需要独立接入实时行情事件与恢复语义，不能假定更换时钟就完成。

建议模块：账户管理、只读同步、交易事实/归组、计划与笔记、图表快照、轻量复盘；模拟执行和真实执行是独立适配器。

核心实体：TradingAccount、SyncCoverage、RawExchangeEvent、Order、Fill、CashFlow、TradeEpisode、TradeFillAllocation、TradePlanVersion、JournalEntryVersion、ChartSnapshot、ReviewSession。ReviewSession 是独立查看状态，不修改账户。价量金额采用精确十进制表示，UI 才做格式化。

只读同步使用 REST 历史/补齐 + 私有 WS 实时 + 周期对账；持久化游标、覆盖范围和错误。唯一身份包含交易所、环境、账户、产品与成交 ID，必要时加合约。重复、乱序、重启与 REST/WS 重叠不能重复记账。期初余额、充值、提现、划转不混作收益。

可交易账户的执行独立校验账户绑定、产品权限、精度和可用资金。请求持久化后再发送；未知结果进入查询/对账状态，不盲目重复发送。首版设计不把提币或划转包含在交易权限里。复盘实例没有真实执行能力，前端隐藏按钮不能替代后端能力检查。

实时模拟账户需明确撮合来源、费用、滑点、部分成交与断流策略。重启不能重复成交；缺少流动性证据不能把触价当成必然全部成交。重置资金创建新的练习区间，保留旧笔记与交易历史。

## 7. 交付顺序

以下保留最初的产品优先级规划。PR #68 当前先提供本地 `practice` / `manual` 账户及笔记、复盘能力；交易所只读同步仍按 Issue #23 单独跟踪，真实账户对账与恢复验收尚需补齐。

1. 统一数据模型、账户入口、三阶段笔记、模板与快照契约；首版连接范围建议以 OKX USDT 永续作为待验证候选，不把候选写成已确认支持。
2. 按 #23 首期交付只读同步、交易归组、笔记、轻量复盘，完成真实样例对账与恢复验证。
3. 加入实时模拟账户，复用产品规则、笔记与复盘，明确撮合精度；历史训练通过独立实例接入。
4. 增加真实执行，单独交付下单状态机与执行验收。

产品最终支持三类账户；代码首版只显示真正可用的类型，其他类型显示明确的规划状态，不能放置看似能连接的空表单。

## 8. 验收重点

- 三类账户都能创建、编辑、自动保存三阶段笔记并使用模板；只读权限、未成交或交易所断连不阻止本地记录；全部账户筛选保留所属账户标识。
- 只读账户在后端也无法产生交易动作；复盘视图不拥有真实执行能力。
- 部分成交、加减仓、反手、双向持仓、跨日、资金费和期初缺失都有可解释的归组与对账结果。
- 修改计划不覆盖初始计划；事后补记可区分；无有效初始风险不生成正式 R。
- 模板变量不编造未知事实；保存失败、重启恢复与备份恢复可复现。
- 开仓在 K 线中途、跨周期、回退、重绘指标、未来笔记和最终收益都不会泄漏到盲看视图。
- 导入历史交易可复盘，但未保存的当时上下文显示缺失；近似状态不声称精确还原。
- 复盘不启动训练撮合引擎，也不阻止后台只读账户继续同步。
- 模拟与真实账本、订单、统计隔离；账户切换不跨账户发送草稿；未知执行结果不重复下单。
- 记录有界窗口内首次打开与单步推进的实测延迟；结果证明的是轻量查看性能，不等于完整训练或实盘执行的资格。

## 2026-10-26 — verified OKX trade review

The read-only account now has a **Trade review** tab. It projects only complete,
reconciled USDT linear SWAP lifecycles from the existing account facts. Each
projection carries the account UID, position identity, margin mode, original
fill/trade/order IDs, contract quantities and funding bills. It does not insert
exchange fills into the manual/practice ledger or expose trading operations.

The first fill's import order is not an identity: trade IDs use the bound account,
product, instrument, side, margin mode, position ID and lifecycle creation time.
Verified financial versions are immutable and content-addressed. Repeated reads
reuse the same version; later verified changes update the current pointer while
an open journal/replay continues to request its selected version. Reverting to a
previously verified version does not create a duplicate trade or move its notes.

The journal implementation is shared through a journal-only service and frontend
transport. Exchange reviews, notes and snapshot images stay behind the desktop
session/Origin guard; writes also require CSRF and an explicit user action. Image
requests carry authority in headers, never query strings. The old fill journal
remains in its original table and associated note revisions are exposed with
actual save times; this feature does not migrate or delete the source history.

Statistics describe the retained verified sample in USDT, with gross realized
P&L, positive-as-cost fill fees, signed funding and net P&L. Coverage, excluded
cycles, unmatched fills and cached sample counts are visible. Cached historical
versions remain reviewable after sync stops or a bounded source read fails, but
are explicitly not represented as currently re-verified. These totals are not
account-level returns or independent proof of opening cash. New review notes are
post-trade; they do not manufacture pre-trade risk or R statistics.

Quick replay clips fills, their exchange-reported realized P&L, funding settlements
and journal content at the same strict `event time < cursor` boundary. Open-position
P&L and excursions are candle estimates. Historical drawings, historical indicator
configuration, inverse contracts and incomplete opening histories remain outside
this version. Pyne remains retired.
