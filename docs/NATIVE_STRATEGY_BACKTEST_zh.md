# Pine / Pyne 原生策略接入

现在包含原生历史回测、原生历史交互回放，以及独立的 CandleScope 撮合反馈 V6。原生模式由 Pine 或 Pyne 唯一维护成交、持仓、权益；宿主反馈模式由 CandleScope 唯一维护账户。两类运行不拼接账本、不二次撮合。下文 V2–V5 记录历史阶段；当前新增能力与限制以 V6 为准。

## 使用

启动当前代码的后端和前端，打开“策略研究”，选择历史数据，进入“Pine / Pyne 完整策略”，再选择原生回测或 CandleScope 撮合反馈。选择语言，粘贴完整策略源码并运行。行情页的策略测试面板也提供该入口；已有宿主策略附件继续使用原来的撮合模式。

报告在研究页结果区显示原生权益、价格、已平仓交易的开平仓标记、数值 plot、交易表和订单表。点击交易或标记可定位主图。完整原生输出（包括其他绘图对象、统计和持仓）保留在报告与 JSON 导出中。复杂绘图对象目前保留数据，未全部映射到 CandleScope 的绘图界面。

资金、手续费、仓位和订单行为由各引擎的策略声明配置。参数栏是 JSON 对象：Pine 使用唯一的 input 标题或 callSiteId，例如 `{"Threshold": 200}`；Pyne 使用原生参数名称。未知或歧义 Pine 参数会拒绝执行。

两个引擎的原生语义可以产生不同成交。不同模式和不同引擎的报告不能拼接成一份账户账本。

## 引擎与安装

- Pine：`pine-compat-runtime 0.3.0rc1`，从独立仓库的 Windows wheel 安装。
- Pyne：`pyne-runtime 0.4.0`，从独立仓库构建 wheel 后安装。
- 各自通过 `candlescope-plugin-pine-compat` / `candlescope-plugin-pyne` 的原生策略入口执行；通用引擎扩展位于下述独立工作树，原工作树保持原状。
- Pyne 的批量源码进入真实 `PyneRuntime`；`init(ctx)` / `on_bar(ctx, bar)` 源码进入真实增量 session，以已确认历史柱 seed。宿主只观察引擎公开权益属性，版本固定为 0.4.0，并对原始报告做直接运行等价测试。

安装命令（Python 版本必须与 wheel 匹配，本次为 Windows Python 3.12）：

```powershell
python backend/scripts/install_native_strategy_plugins.py `
  --wheelhouse output/external-completion-v6/wheels --activate
```

wheelhouse 必须恰好包含 SDK、两个插件、两个运行时及 numpy 的六个 wheel。安装脚本使用独立 venv、离线安装、pip check 和两个真实插件的身份探测；安装收据记录 wheel SHA256。安装到 `%LOCALAPPDATA%/CandleScope/plugins/native-installs/<bundle hash>/`，通过原子替换 `native-strategy-registry.json` 激活。

指标插件的 `runtime-registry.json` 不被改写。已有原生注册表会备份到安装目录的 `previous-native-registry.json`。可恢复该文件完成原生安装回滚；首次安装则移走新增的原生注册表。恢复后新运行使用恢复后的版本，既有报告仍保留其原始身份。

解析优先级：`CANDLESCOPE_NATIVE_RUNTIME_REGISTRY` → `CANDLESCOPE_RUNTIME_REGISTRY` → 默认原生注册表（若存在）→ 默认指标注册表。显式环境变量优先于本机安装。仍遵守现有 `BACKTEST_ENABLED`、`BACKTEST_BAR_ENABLED` 和 `CANDLESCOPE_PLUGIN_HOST_ENABLED` 开关。

## 数据与原生 API

路由前缀 `/api/v1/backtests/native`：

| 接口 | 用途 |
| --- | --- |
| `GET /capabilities` | 探测真实已安装引擎及代码身份 |
| `POST /runs` | 创建原生运行，要求 `Idempotency-Key` 请求头 |
| `GET /runs` | 最近 100 条原生历史 |
| `GET /runs/{id}` | 状态、错误或完整报告 |
| `POST /runs/{id}/cancel` | 终止运行，禁止迟到结果覆盖取消状态 |
| `GET /runs/{id}/export` | 导出完整记录 |

主数据来自现有数据集及 `/api/v1/backtests/datasets/snapshot`。创建体包含 `language`、`source`、`parameters`、`context: {symbol, timeframe}` 及 `dataset_id`、`data_epoch`、`snapshot_hash`、`start_time_ms`、`end_time_ms`、`interval`、`exchange`、`market_type`。timeframe 使用引擎语法（1 分钟为 `"1"`），interval 使用宿主语法（`"1m"`）。

高级输入也已接到真实引擎，目前通过界面的“额外数据与 Pine 库”或 API 提供：

- `contexts`：最多 16 个额外固定数据引用，每个引用增加 `symbol`、`timeframe`，供 `request.security` 等请求使用。
- `libraries`：Pine 导入路径到完整库源码的映射。
- `magnifier`：Pine 的低周期固定数据引用。必须同品种、低于主周期且完整覆盖每根主柱；由宿主构造成运行时的 chartBars 输入。

界面支持主图历史、参数、额外请求数据、库源码和 Magnifier。请求品种键必须与源码一致（本地数据默认 LOCAL 前缀，可编辑）；运行前重新校验数据修订，再冻结快照。缺失输入、快照失配、断柱、不完整主柱、引擎拒绝的语法和语义均明确失败，不降级为简单信号或宿主成交。

运行输入包含源码、参数、固定数据和库源码以及已安装 SDK、插件、引擎的内容身份，生成 input/source hash。返回结果再次校验身份与账户权威；完整结果含 bars 后生成 report hash。记录使用独立 `native-backtests.db`，不写宿主成交账本。

宿主策略：原生运行、回放推进与宿主撮合共享最多 2 个执行名额；单次执行期限 120 秒，输入/输出各 64 MiB。它们属于 CandleScope 的资源策略，不改变独立引擎的默认产品策略。Pyne 使用宿主 safe 模式；这不是操作系统安全沙箱。

## 验证和边界

真实安装的 wheel 验证覆盖两种语言完整源码、参数影响、重复运行确定性、原生订单/权益/绘图、Pyne 批量和增量报告等价、额外请求数据、Pine Magnifier、原生保证金拒单、无二次撮合、幂等、取消和重启中断。浏览器使用真实 HTTP 服务及 200 根导入 K 线，Pine 示例得到 5 笔已平仓交易，Pyne 示例得到 6 笔；两者差异保留。

本次没有宣称任意 Pine/Python 兼容：Pine 遵守该 wheel 的标准 OHLCV、线性账户等能力边界；Pyne 遵守宿主 safe 执行策略。Pyne 0.4.0 的部分无订单批量策略不输出 strategy 报告且原生 equity 序列为零，适配器保留其原值并显示 `PYNE_EMPTY_NATIVE_REPORT`，不会由宿主补造账户。

## 原生交互回放

完成原生回测后，在报告中点击“创建回放”。支持步进、播放、暂停、跳转到指定柱数、保存和恢复回放快照；回放历史持久化，重启会将未完成推进标为 INTERRUPTED，可以继续操作。

V4 的 Pine 策略（含 contexts、Magnifier）和 Pyne init/on_bar 策略（含 contexts）使用 `FIXED_HORIZON_INCREMENTAL`：真实引擎会话保留计算和账户状态，连续推进不再重跑之前的柱。历史区间在创建时固定，`barstate.islast` 等末柱标记以完整区间为准；它与把当前前缀当成完整历史的模式不同。未来柱的价格不会提前执行。到达终点必须与初始整段原生回测的完整 report hash 相同，否则失败。

Pyne 批量源码的回放仍显式使用 `HISTORICAL_PREFIX_REBUILD`。两种方法在界面和记录中区分，不使用实时追加接口冒充历史执行。

持久化快照保存固定输入身份、游标及当时的原生报告，是宿主可重建检查点。V3 会话进程内另保留最多 8 个真实状态快照用于回退；Pyne 脚本对象不能快照时，回退会从固定输入重建。宿主最多缓存 2 个会话进程，淘汰、重启后按原输入恢复到目标游标，再继续增量推进。没有把进程内 Rust/Python 对象序列化到数据库。继续执行使用创建运行时冻结的安装入口并复核内容身份。额外数据只暴露已完成且不超出当前边界的柱，Magnifier 也按主柱截断。创建早于此升级、没有保存 frozen input 的运行需先重新回测一次。

前缀模式的连续播放成本随历史长度增长；会话模式避免重复执行历史，但完整报告和状态快照仍有复制成本，不宣称整条图表/报告链路是常数时间。暂停会取消当前未提交计算，只有完整计算成功的游标才会提交。研究主图仍可查看全历史，不作为盲测训练的数据保密界面。

接口位于 `/api/v1/backtests/native/replays`。创建体为 `{run_id}`；`GET /{id}`、`GET /{id}/export` 查看或导出当前进度；`POST /{id}/commands` 接受 `{revision, action, target?, snapshot_id?}`。action 为 step、play、pause、seek、snapshot、restore。除暂停外，过期 revision 会拒绝。

## CandleScope 撮合反馈 V2

在完整策略编辑器中选择“CandleScope 撮合反馈”，设置初始资金、滑点和成交费用。API 使用独立的 `/api/v1/backtests/external/runs`，记录明确标为 `CANDLESCOPE`，报告的账户权威为 `candlescope`。原生与宿主运行列表分开，宿主记录不能进入原生回放。

执行链为：真实 Pine / Pyne 源码计算 → `external-broker/1` 订单意图 → 现有 `SimulationKernel` 撮合 → 真实持仓/均价/权益/损益反馈 → 下一次源码计算。运行时不执行自己的成交阶段；报告、账户曲线与成交标记均来自宿主内核。双方保留先前账户和意图记录，发现历史意图随前缀增长发生变化即拒绝，避免边界敏感脚本改写已经撮合的决策。

V2 初始版本支持市价、限价、止损及止损限价 entry，反手、按 qty 或 qty_percent 部分平仓、exit 止盈止损 OCO、同 ID 挂单替换、cancel / cancel_all。每柱最多 64 个意图，单净持仓且不加仓，只允许一个待成交开仓单。Pine、Pyne 批量和 Pyne init/on_bar 均经真实运行时解释；Pyne 批量价格与数量支持序列。

V2 初始版本中，金字塔加仓、多个待成交开仓单、未映射的原生成交设置、逐 tick 自动重算、追踪止损、按 tick 距离设置 profit/loss，以及不在外部账户契约中的字段仍明确拒绝。宿主撮合不宣称原生 broker 语义等价。原生模式原有能力保持独立。

两个独立引擎的宿主无关扩展位于 `E:/projects/pine-external-broker` 和 `E:/projects/pyne-external-broker`，分支均为 `codex/external-broker-v1`。各自 `docs/EXTERNAL_BROKER_V1.md` 说明接口。原工作树现有修改未动。

后续阶段 wheel 集位于 `output/external-strategy-validation/wheels`，安装方法与上文相同，更换 wheelhouse 路径即可。安装使用新的内容寻址目录，旧安装保留，升级后的原生回测通过新安装重新验收。

这是一份本机源码和安装交付，尚未发布插件版本或打包新的桌面安装器。已有后端进程需重启才会加载新增路由。

2026-09-20 第一阶段曾激活内容寻址安装 `7083f433b9dccdb2ad69709259a5d304abbd13da12d7227e86ceec7430293bf9`（V2 升级前）。验收记录见 [回放与宿主反馈验收](evidence/native-strategy/2026-09-20-replay-external-qualification.json)，包含 wheel 哈希、运行身份、浏览器记录和回放终点一致性结果。


## V2 撮合数据与固定输入

编辑器的“撮合数据精度”提供三种选择：

- `BAR_APPROX`：原有下一柱保守撮合，包括同柱止盈止损冲突的最差情形。
- `TRADE_TAPE`：主图收盘后决策，使用后续真实成交事件撮合。聚合成交会明确标为 `AGG_TRADE_TAPE`，不会冒充逐笔原始成交。
- `BOOK_ASSISTED`：使用成交事件和当时可见的买一/卖一做保守成交判断，支持止损触发及止损限价。它不是排队位置精确模型，不模拟完整深度队列。

逐笔模式未上传 JSON 时尝试读取现有本地聚合成交归档；归档未开启或不足时失败。订单簿模式目前从固定 JSON 上传接入。上传体是 `execution_data`，随运行保存并计入输入哈希：

```json
{
  "symbol": "BTCUSDT",
  "events": [
    {"time_ms": 0, "role": "ORDER_BOOK", "payload": {"book_sequence": 1, "snapshot": true, "bid": "99", "ask": "101"}},
    {"time_ms": 0, "role": "TRADES", "payload": {"source_event_kind": "AGG_TRADE", "source_sequence": 1, "price": "100", "qty": "1"}}
  ]
}
```

该片段仅说明字段。实际输入必须完整覆盖选定 K 线；成交聚合出的 OHLCV 必须与主图一致。成交 ID 必须连续且时间有序；订单簿从有效快照开始，后续序列必须连续，禁止交叉盘口、缺失价格及不完整输入。模式不会因缺失数据降级为 BAR。

JSON API 在 `/external/runs` 创建体中增加 `execution_fidelity` 与可选 `execution_data`。每次运行保存真实成交模型、脚本运行时身份与宿主代码身份。引擎只收到截止当前柱的 OHLCV 和账户反馈，不会收到未来逐笔行情。

V2 wheel 集使用 `output/external-strategy-v2/wheels`；测试和安装收据在同名目录。后续 V3 的会话和成交回调见下文。


V2 曾启用安装 `bb1ab0ffd833514f020a8415d034cb2f393cda6ed337e2471736f4ded53c2ef4`。原安装保留用于回滚。V2 验收见 [价格订单与事件撮合验收](evidence/native-strategy/2026-09-20-external-v2-qualification.json)。本轮用确定性小数据验证撮合与反馈契约，不宣称通过生产大归档性能或真实队列校准验收。


## V3 原生会话与宿主成交回调

在 TRADE_TAPE 或 BOOK_ASSISTED 模式勾选“成交后执行策略”，API 对应 `fill_recalculation: true`。每一笔实际成交完成后，以当时的账户和截至该事件的部分 OHLCV 调用引擎。订单簿/成交序列、费用、权益和持仓始终由宿主内核负责；新意图最早在下一行情事件成交。BAR_APPROX 无法提供这一时间粒度，明确拒绝该选项。

Pine 脚本必须声明 `calc_on_order_fills=true`，运行时在同一柱内执行额外 pass，保持原有指标检查点语义；不把一次成交伪装成一根新 K 线。回调中的 `barstate.isconfirmed` 为 false，收盘 pass 为 true，历史/实时标记保持历史模式。

Pyne 必须使用增量脚本并显式提供 `on_fill(ctx, bar)`；`on_bar` 仍只在收盘调用，避免把用户主动 `.update()` 的增量指标意外推进多次。两种回调共用真实 ctx 状态；账户访问均来自宿主。批量向量脚本不支持此回调配置。

```python
def init(ctx):
    ctx.strategy.configure(calc_on_order_fills=True)

def on_bar(ctx, bar):
    if ctx.bar_index == 0:
        ctx.strategy.entry("L", ctx.strategy.long, qty=1)

def on_fill(ctx, bar):
    if ctx.strategy.position_size > 0:
        ctx.strategy.exit("Protection", "L", stop=ctx.strategy.position_avg_price * 0.98)
```

宿主每柱最多 64 次成交回调加 1 次收盘、最多 64 个订单意图；超限失败，不截断结果。每次调用验证之前的 `(bar_index, pass_index)` 意图未被改写。导出中的 `raw_output.execution_passes` 保留每次触发的时间、可见柱、账户和 confirmed 标记，`kernel.decisions` 标注 ORDER_FILL/BAR_CLOSE。会话模式和成交回调是两个独立接口：宿主成交回调目前仍重建完整事件前缀，尚未做大归档吞吐验收。

V3 wheel 集位于 `output/native-strategy-v3b/wheels`。V3 当时保持单净持仓、一个待成交开仓单、无金字塔加仓；盘口模型为买一/卖一加成交事件，并非完整深度队列。高级数据选择器在 V4 补齐；全部复杂图形渲染、追踪止损及 tick 距离 profit/loss 仍未实现。原生引擎支持的能力仍可在原生模式使用；不支持的宿主配置明确拒绝。

本机 V3 曾启用安装 `d88e726c6b1825a49c12e3c8d17a9240f980ef8d2a6cbdaf81865534b36d03a9`，旧安装保留。验收见 [有状态回放与成交回调](evidence/native-strategy/2026-09-20-sessions-fill-qualification.json)。


## V4 高级输入与时间语义修正

原生编辑器可选择多个 request 数据集、Pine Magnifier 低周期数据，并输入导入路径到库源码的 JSON。请求数据冻结所选数据集的完整范围；Magnifier 冻结主图范围。过期修订、重复请求键、缺失或错误输入明确拒绝，不自动替换数据。切换语言会清空高级输入，Pyne 不接受 Pine 库与 Magnifier 配置。

Pine 通用历史会话现在接收固定 request/Magnifier 输入；Pyne 增量会话继续使用固定请求 provider。两者通过首步无提前高周期值、终点与整段报告相等的测试；Magnifier 与库还覆盖快照恢复。已验证策略的中间无订单状态不会再被 Pyne 适配器误判为非策略。

修复 Pine 适配器的秒/毫秒错误：CandleScope 公共 K 线和图表交易时间使用秒，Pine 引擎输入、账户反馈及原始报告时间使用毫秒。适配器版本升至 pine-native/2、pine-external/2。修复前生成的 Pine 结果可能受时间、日历或 request 对齐错误影响，应重新运行；既有记录及其原始版本身份不改写。

行情图入口现在也会发送 fill_recalculation，与本地数据入口一致。宿主撮合的单净持仓、单待成交开仓单限制保持明确；多开仓单归属、金字塔加仓和完整盘口队列尚未接入。

V4 wheel 集为 output/native-inputs-v4/wheels；内容身份、本机安装和验收见 [高级输入验收](evidence/native-strategy/2026-09-20-inputs-v4-qualification.json)。这是本机候选交付，不等于发布新版本或桌面安装器。


## V5 宿主撮合请求数据

CandleScope 撮合反馈模式新增“添加请求数据”，可选固定本地数据集并编辑与源码一致的品种键。Pine、Pyne 批量和 Pyne init/on_bar 策略都通过实际运行时使用请求数据。每次收盘决策前，宿主只向引擎传入截至该边界已完整收盘的额外柱；空的已知数据流可返回 na，未提供的请求品种仍拒绝。

请求数据随运行冻结，参与输入哈希。BAR_APPROX、TRADE_TAPE、BOOK_ASSISTED 的成交仍由 CandleScope 内核产生；请求数据不携带账户，也不参与第二次撮合。若 lookahead 等语义导致过去订单意图被重写，整次运行以 EXTERNAL_NONCAUSAL_PREFIX 失败，不交付混合账本。

V5 初始版本限收盘决策：contexts 与 fill_recalculation 同时设置会明确拒绝。Pine 库源码和 Magnifier 仍属于原生模式；宿主模式不接收。切换执行模式会清空高级输入，避免把另一模式的数据配置无声带入。

修复了能力探测仅接受旧 adapter /1 的错误；现在识别已验收的 Pine /1–/3 和 Pyne /1–/2，并检查协议。引擎扩展仍是通用 request_bars / data_provider 接口，数据可见性策略留在 CandleScope。

V5 安装包位于 output/external-inputs-v5/wheels；验收见 [宿主请求数据验收](evidence/native-strategy/2026-09-20-external-inputs-v5-qualification.json)。多开仓单、加仓的逐笔归属、追踪止损、tick 距离订单和完整盘口队列仍待接入。


## V6 多开仓单、距离订单与逐次请求数据

宿主模式现在支持多个待成交开仓单和 `pyramiding=1..64`。开仓 ID 对应实际成交数量，`close(id)` 和 `exit(from_entry=...)` 只减少该 ID 的数量；未指定 ID 时按先入先出分配。挂单反手在实际成交时计算需平掉的数量，不能使用提交时的旧持仓。超过加仓上限的待成交单会取消。

账户仍只有宿主内核一份，使用净持仓均价计算资金、费用和损益。开仓归属是数量分配记录，不是另一份逐笔成本账户，也不宣称与原生引擎逐单盈亏等价。成交表增加 `script_order_id`、`closed_entries`、`opened_entry`；完整导出保留 `entry_allocation`、未平数量和每次分配。

`strategy.exit` 支持 `profit/loss` tick 距离，以及 `trail_price` 或 `trail_points` 配合 `trail_offset`。距离必须为正数，并在界面明确设置最小价格变动 `price_tick`；两个引擎的 `syminfo.mintick` 使用该设置。它用于距离换算，不表示已获得交易所全部合约过滤规则。同一止盈腿不得同时设置 limit/profit，同一止损腿不得同时设置 stop/loss；不支持的组合明确拒绝。

距离以对应开仓 ID 的实际成交数量加权价格为基准。BAR 每根柱内固定基准，按最坏情况处理同时触达的 OCO；入场尚未成交的保护单在该柱不会推断盘中路径。TRADE_TAPE/BOOK_ASSISTED 的移动止损按有序成交价推进，保留相同 ID、归属和参数替换时的最高/最低价；首次触发后剩余数量作为市价单继续成交。BAR 模式明确拒绝移动止损，因为 OHLC 不足以恢复其盘中路径。

请求数据现在可与成交回调组合。宿主为每个 pass 冻结截至当时已收盘的额外数据，两个引擎逐 pass 切换 provider 并清除请求缓存。后续高周期柱收盘不能改写此前回调的可见输入。Pyne 在 init 中保存的 request 别名也绑定当前 pass。宿主继续校验历史意图不变，账户、成交与脚本反馈均来自同一宿主。

V6 候选 wheel 位于 `output/external-completion-v6/wheels`。适配身份为 pine-external/4、pyne-external/3；内容寻址安装和测试结果记录于本阶段验收文件。此接口未改变原生运行或原生增量快照格式。

本机已激活安装 `dbbe8c5eab1747fb24baf779627185a857bf35801ebc296855c0b49d2f3a272e`，V5 安装保留用于回滚。[V6 安装与完整验收记录](evidence/native-strategy/2026-09-20-completion-v6-qualification.json) 包含正式安装路径下的 123 项回归、独立接口 19 项、共有内核 97 项、Pine 运行时 1840 项、前端 138 项，以及浏览器中两种语言五笔成交和相同最终权益的证据。逐笔请求数据还覆盖收盘前最后一毫秒同时间多事件的可见性边界。

V6 当时未完成的范围：完整深度队列撮合、全部复杂图形渲染，以及大归档上逐回调前缀重算的性能验收。以下 V7 补充其中一部分。BOOK_ASSISTED 仍只代表买一/卖一辅助模型。原生模式、宿主模式的报告和账户不得混用。

## V7 深度撮合、图形对象与归档运行成本

新增 `BOOK_DEPTH` 模式，成交模型为 `FULL_L2_PESSIMISTIC_FIFO_V1`。必须显式上传完整初始 L2 深度、连续 `book_sequence` 更新，以及含 `aggressor_side: BUY/SELL` 的成交。每个盘口事件包含 `bids`、`asks` 两个 `[price, quantity]` 数组；完整快照必须声明 `snapshot: true, depth_complete: true`，增量中数量为零表示删除价位。断序、重置、缺边、交叉盘口、不完整快照及缺失成交方向都拒绝运行。

主动单在下一个成交事件逐档消耗剩余可见深度，跨价限价单收 taker 费用。重复相同快照不会补回已消耗的假设流动性。被动单排在当时可见数量和较早本方订单之后，只有同价格、相反主动方向的成交推进队列，撤单不推进队列。此模型不等于真实交易所排队重建：L2 不包含订单级优先级，导出的 `raw_output.depth_model.queue_exact` 固定为 false。主动单容量取盘口深度，不以触发成交的数量为上限；被动单共享触发成交容量。完整真实深度归档的校准尚未完成。

每个深度档位成交都经过同一宿主账户和开仓数量归属接口；启用成交后重算时，脚本能按顺序看到每笔部分成交后的持仓。独立开仓单现在带显式独立分组，避免旧内核把恰好同批同数量的限价和止损开仓单误组为 OCO。

报告新增六类对象视图：line、label、box、polyline、linefill 和 table。支持 Pine 对象快照的回放位置过滤、删除状态、Pyne 对象、时间/柱索引坐标、合并单元格和多个 pane。文本按文本转义，颜色不允许 SVG URL。对象超过 5000 或单表超过 10000 格时明确提示，完整结果仍可导出。该视图不是原平台逐像素复刻；标签外形、字体、曲线插值和表格布局存在差异。plotcandle/plotbar、plotshape/plotchar/plotarrow、背景着色及序列渐变填充仍未全部可视化，原始输出保留。

宿主适配版本提升为 `pine-external/5`、`pyne-external/4`。一次宿主运行复用一个隔离评估进程，身份校验、取消、超时和输出预算继续生效；Pine 缓存当前源码的编译程序。策略状态仍按可见事件前缀重建，每次核对已经提交的历史决策，未改变账户权威来源。宿主模型标记为 `DEPTH_QUEUE_PERSISTENT_EVALUATOR_V7`。

归档基准脚本 `backend/scripts/benchmark_native_v7.py` 校验本地 BTCUSDT 2026-06-01 归档的 17 个 parquet 哈希和 1,643,542 笔连续成交，聚合全天 1440 根分钟柱。两种语言分别测试 60 柱单次启动/复用进程的完整报告一致性、全天 BAR、前 120 分钟 106,420 笔成交，以及启用成交后重算的相同行情。结果分别记录数据准入、执行和报告编码时间，不能解释为生产数据库调度、图表绘制或高频密集成交策略的性能保证；前缀重建的大规模复杂度仍存在。

最终源码的归档计时为 9 项通过、1 项失败：并发回归负载下 Pyne 全天 1440 柱触发原有 120 秒期限。该失败保留，不将全天性能标为稳定通过；没有上调期限。两种语言 60 柱进程复用前后的完整报告哈希一致，逐笔与逐成交回调样本通过。样本回调仅 4 笔成交，不能代表高频成交压力。

本阶段的安装、测试、性能和限制以 [V7 验收记录](evidence/native-strategy/2026-09-20-native-v7-qualification.json) 为准。浏览器验收命令被自动审批拒绝（仅返回 blocked by policy），因此本轮没有浏览器视觉验收证据；没有发布公共版本或桌面安装包。

## V8 序列图形与 Pyne 回调成本

报告现在接入运行时输出的蜡烛、OHLC、字符/形状/箭头、背景着色、柱体着色、水平线、普通填充和 Pine 纵向渐变填充。Pine RGB/RGBA 数值颜色（包括低 RGB 的 alpha 标记）正确解码；颜色不会进入价格轴范围。隐藏序列、显示窗口限制、offset、缺失值和绝对坐标零值均有回归。Pyne 使用实际时间映射，其运行时已处理的位移不会重复应用。

这里提供的是报告图形视图：形状、标签、字体及曲线仍有近似，每根柱使用一片填充；不承诺 TradingView 像素级等价。当前 Pyne 运行时没有 `plotbar` 接口，不能因 Pine 前端支持而宣称 Pyne 也支持。Pyne 已有 `plotcandle`、marker、着色和普通填充则直接展示。完整原始输出继续可导出。

已用当前 React 组件和两种已安装引擎的真实输出完成静态预览，以及完整策略页面的浏览器验收。后者使用仅绑定 `127.0.0.1` 的独立后端、独立数据库和五柱固定数据：Pine、Pyne 均完成整段运行、图形展示、单步及跳转；Pyne 另验证真实开平仓记录、保存快照及恢复至第一柱。此证据覆盖本地候选，不代表桌面发行包或生产数据环境验收。

独立 Pyne 候选优化普通 Python 回调参数检查，带自定义签名或包装器的函数保留原反射路径；每次读取当前 code 对象，因此动态替换函数代码仍生效。普通标量 OHLCV 使用独立字典复制，嵌套/自定义元数据保留深拷贝。两项优化都不改变脚本状态、账户权威、快照语义版本或宿主期限。候选 wheel 使用独立内容哈希，不是公共 Pyne 0.4.0 发布版本的替换发布。

顺序执行的 720 柱旧/新对照为 26.14 秒与 19.09 / 20.02 秒；除运行时身份外，完整报告哈希三次一致。此工作负载实测执行时间缩短约 23%–27%，并分别记录宿主及工作进程 CPU 时间。这个比例不能外推为任意脚本、逐笔策略或图表刷新提速。

最终候选全天 1440 柱执行为 73.55 / 65.48 秒，均在原有 120 秒期限内完成，23 笔成交且完整语义报告哈希一致。性能记录仍保留初次仅优化参数检查时的超时结果。源码哈希、1252 项 Pyne 核心回归、47 项候选安装回归、24 项最终激活安装回归及 149 项前端回归，以 [V8 验收记录](evidence/native-strategy/2026-09-20-native-v8-qualification.json) 为准。重复前缀计算仍存在，任意大数据量或任意 CPU 争抢下的 120 秒完成保证不在验收范围内。

## OKX 历史深度归档核验

后续已新增独立 `BOOK_SAMPLED` 模式，不修改本节完整深度准入结论。下载、配套 K 线导入、采样撮合与连续采集命令见 [OKX 采样盘口使用说明](OKX_SAMPLED_BACKTEST_zh.md)。

已从 [OKX 官方历史数据](https://www.okx.com/zh-hans/historical-data) 的公开下载接口获取 BTC-USDT 现货 2026-06-01 的 5000 档订单簿，以及 2026-06-01、06-02 两份逐笔成交文件。原件位于 `output/native-v8/`，SHA256、官方 URL、字段与全量统计保存在 [归档审计](evidence/native-strategy/2026-09-20-okx-depth-archive-audit.json)。可运行 `python backend/scripts/audit_okx_depth_archive.py --directory output/native-v8` 复核，无需解压到文件系统。

订单簿覆盖 UTC 6 月 1 日，包含 96 次快照、86304 次增量，买卖各 5000 档，更新间隔主要为 1000 毫秒。成交文件按 UTC+8 日期切分，因此需要两份文件覆盖同一 UTC 日；两份共 1122236 笔，其中 503193 笔位于订单簿首末记录时段内。成交含 `buy/sell` 字段。

这解决了“能否取得真实归档”，尚未解决完整队列模型验收：该档位上限不代表完整市场深度，文件没有 `seqId/prevSeqId`，不能证明事件无丢失，也不能恢复秒内盘口变化及跨流事件先后。审计明确返回 `book_depth_admissible: false`，没有伪造 `depth_complete` 或用本地行号冒充交易所连续序列。该归档可留作后续有限深度、采样模型研究；当前 `BOOK_DEPTH` 完整输入要求保持不变。L2 队列始终是显式假设，不等于真实订单优先级。
