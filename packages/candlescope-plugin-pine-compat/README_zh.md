# CandleScope Pine Compatibility 插件

本包把独立发布的
[`pine-compat-runtime`](https://github.com/helenananaa/pine-compat-runtime) wheel
桥接到公开的 `candlescope.script-runtime/1` SDK。包内只有适配代码，不包含 Pine
引擎源码快照，也不导入 CandleScope 后端私有模块。

适配器 `0.3.2` 使用官方 `pine-compat-runtime==0.3.2` 的 Windows、Linux、
macOS Apple Silicon 和 Intel wheel；各平台发布锁分别固定真实文件和校验值。
`release/release-lock.json` 锁定引擎、SDK 和 bridge 的内容哈希，旧发布锁
保存在 `release-lock.0.2.0.json` 和 `release-lock.0.3.0.json`。分析/输出/增量协议为 6/9/4。
渐变填充因 Render IR v1 无法表达而明确拒绝；纯色填充继续支持。资源超限
以 `E_RESOURCE_BUDGET` 诊断返回。

支持历史批计算，以及已确认历史末尾的一根 forming bar。WebSocket 订阅通过
`options.pineSessionId` 保留原生会话，支持替换、收盘确认和追加；传输仍返回完整
Render IR 快照。HTTP 计算保持独立。分析结果的 `meta.hostRequirements` 暴露
引擎的宿主需求清单，不代表这些外部能力已经接入。

每个 sidecar 最多保留 8 个最近使用的会话。历史窗口变化、源码或参数变化、
会话淘汰、进程重启会重新播算，并返回 `meta.sessionReset=true`。冷启动按盘中
接入处理，无法恢复此前的 tick/varip 状态。尚未提供跨进程会话恢复或无限历史保留。

当前源码候选增加显式执行时钟、分析缓存及实际价格网格。指标使用宿主观察时间；
原生回测与回放使用冻结的柱收盘时间。`syminfo.mintick/minmove/pricescale` 缺少
实际价格网格时明确拒绝，不使用合成默认值。原生回测高级输入可手动指定价格步长。
单位点值以外的合约仍受上游引擎限制。

指标的 `request.security/security_lower_tf` 和旧版 `security` 可读取明确交易所和市场
类型的完整本地标准蜡烛，未收盘数据不跨可见边界，计算过程不自动下载。继承图表
symbol/timeframe 的请求可使用图表身份；动态或嵌套请求需在编辑器声明有限的上下文
列表（`params.__pineContexts` → `options.pineRequestContexts`），最多 16 个，缺少实际
所需的数据时明确报错，不推测动态表达式的结果或替换市场。跨交易所可显式指定
`marketType`，未指定时保持图表市场类型。指标编辑器可提供版本化库路径到源码的映射，保存于
`params.__pineLibraries`，通过 `options.pineLibrarySources` 传入分析与执行。
分析缓存、编译和会话身份包含完整库源码，结果记录依赖摘要；传递依赖也须显式提供。

最新开发核心 `b9200480e` 的 schema 3 汇率输入已接入：指标使用
`params.__pineCurrencyRates` → `options.pineCurrencyRates`，原生回测、数据准备和回放
使用冻结的 `currency_rates`。汇率按 `effectiveTime`（实际可用时刻，Unix 毫秒）查询，
不将未来帧用于较早的柱；缺少币种对不会用恒等汇率代替。报价币种通过真实交易所
元数据或显式 `metadata.currency` 提供，不根据交易对名称猜测。这是本地源码候选，
尚未发布为官方插件包。图表策略和宿主撮合工作台的版本化库源码也随修订/运行冻结。

复杂对象改为原生快照通道 `collections.objects.pineScenes` / `drawings`，直接在实际
图表坐标中绘制纵线、箭头线、标签、矩形、曲线与填充多段线、线间填充和定位表格，
表格支持合并单元格。删除/隐藏会清除旧对象；旧范围响应不能覆盖更新的对象状态。
坐标保留初始执行窗口和原始时间线，支持时间缺口、历史前插与回放。
字体、曲线、箭头尺寸与渐变插值采用宿主实现，不宣称 TradingView 像素一致。
plotchar/plotarrow/plotbar/plotcandle 和垂直渐变填充也已接入同一呈现通道。
插件要求 `render.native-scene/1` 能力，旧宿主会明确拒绝，避免静默丢失图形。

新图表策略修订使用 `PINE_ENGINE` / `pine-engine-chart-v1`，由隔离进程调用真实引擎，
每步接收宿主实际账户。首批支持收盘市价开平仓、一个入场 ID 和净持仓；复杂价格单、
加仓、请求数据及盘中回调使用独立原生/宿主撮合工作台。已有 `PINE_SUBSET` 修订保留
原语义。编译身份绑定已安装引擎，安装变化需重新编译；检查点保存可见柱与账户记录。

`pine-external/6` 与图表评估进程协商追加输入，覆盖稳定请求上下文和已确认成交回调组。
配套独立引擎候选 `0.3.2+external.1` 新增 `Program.external_session().append(...)`，
保留已提交解释器状态，只执行新增柱和账户反馈。历史修正、上下文变化、未确认回调替换、
进程重启以及依赖数据集末端的脚本仍按语义重建。`barstate.islast`、last_bar_index/time、
可见范围与 calc_bars_count 依赖不能直接复用增长前缀；合成 ticker 也保留重算。
旧引擎保留批算回退。输出仍是完整快照，因此没有消除全部随历史长度增长的传输成本。

上游独立分支 `codex/external-incremental-host` 基于官方 0.3.2 提交构建增量引擎；
`qualify_source_candidate.py --engine-wheel <候选whl>` 可生成并离线验收绑定该摘要的
独立候选包。正式发布锁与用户已激活插件不变。

本地运行：

```powershell
python -m pip install --no-index --find-links <候选wheel目录> candlescope-plugin-pine-compat==0.3.2
python -m candlescope_plugin_pine_compat
```

构建器接受三个 wheel：本 bridge、SDK `0.2.0` 和锁定的 Pine 引擎 wheel。
构建候选包时传入 `--lock release/release-lock.candidate.json`，以及三次 `--wheel`
和一个 `--output`。候选包须通过安装器和真实 sidecar 验证后再启用。

## 回测安装边界

官方 0.3.1 wheel 已补齐 `Program.run_external` 和 `Program.historical_session`，
解决 0.3.0 的回测升级阻塞。冻结 bridge、SDK 和引擎 wheel 并验收后，通过
`install_native_strategy_plugins.py --runtime pine --activate` 仅升级 Pine 回测，
保留其他注册项。安装指标 CSPKG 不会自动注册原生策略回测。
