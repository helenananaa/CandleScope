# #130 公共聚合底座核销回执

日期：2026-11-12，Apple M1 / macOS 26.6.2 / CPython 3.12.15 / Electron 43.3.0。
产品提交 `3878a4ad69196903e630ede4530f77d19e0e5d4c`，交付 PR #366。
本报告核销 #130 的公共协议、核心、块底座和最低历史/实时消费条件；
#126、#127、#129 各自的完整实现和性能范围继续保留。

## 本轮修复

多个自定义周期可以先后排入相同基础种子需求；历史重试也可能在规范数据已经
提交后重新取回相同的已确认窗口。现在两类需求均在执行时重查 canonical 数据：

- 原有准入下的 Binance/OKX 原生 UTC 固定网格种子，复用与 Bybit 相同的可信
  收盘、真实边界和值校验；临时、手工、未知或缺失组成继续补取。
- 普通历史读取复用既有 `derived_source_windows`、K130 与 D126 scoped write
  proof。源/目标重叠修订、删除权限和旧结果围栏继续有效。
- 调度 owner 记录至多 32 种当前需求用途。多个读需求合并后仍可复用；混入显式
  刷新、未知用途或超出边界则保守处理。刷新消费者撤销后重新计算当前用途。
- 显式刷新保持完整范围。没有新增缓存、writer、下载 lane 或交易所能力。

在未修改的 main `9dbea6904` 独立归档中，新矩阵 **24 failed / 16 passed**；
修复后的源复用与真实调度合并/撤销专项 **43 passed**。最终相关回归 **573 passed**，
涵盖实际 SQLite、CCXT provider、H127/B130/K130、查询/交付修订、HTTP 回环、
原生/派生读视图和 Pyne 退役护栏。专项集合重叠，不累计。架构与 whitespace 通过。
[产品提交 pinned-fork CI](https://github.com/helenananaa/CandleScope/actions/runs/43148431432) 成功。

## 真实粗细来源与数学证明

四份 Binance USD-M BTCUSDT 2026-10 月归档分别为 1m/5m/15m/1h；下载字节与
官方 `.CHECKSUM`、本报告固定 SHA256 均一致。只资格化 **10 月 1–17 日 UTC 的
前 16 天**，不把这一采样扩大为全月或其他产品保证。

- 23,040 根 1m；384 根 1h、1,536 根 15m、4,608 根 5m，合计 6,528 根原生粗
  K 线。每根与同源分钟独立 Decimal 参考比较，九字段最大差为 0。
- 89m/97m/101m/10007m 的 **55 组**实际 H127 混合读取，通过 1/7/256 行分页，
  与独立分钟参考比较 OHLCV、quote volume、trades、taker buy base/quote 和最终性。
  浮点组合契约为相对 `1e-12` / 绝对 `1e-8`，没有拆分跨界粗 K 线。
- 一个真实 10007m 目标规划 177 根混合输入，分钟参考为 10007 根。这是本次
  输入与物理读取证据，不是默认图表已经加速的声明。
- 读后 B130 200 个条目、682,449 估算字节，低于现有 16 MiB / 1024 条预算；
  161 hits，leases/views/inflight/retired entries 均为 0，工作预留归零。

这组录制源读取运行于 `ef8f0e0fa`；实际消费的计划、H127、K130、B130 和 SQLite
模块与当前产品逐字节相同，见 [代码等价清单](evidence/source-code-equivalence.json)。
它独立于后面的真实公网桌面流程，不提升图表准入或承诺所有来源可混合。

复现：先以一个新的 output 路径运行 [download-inputs.py](download-inputs.py)，再在
`backend` 的 Python 导入环境运行 [source-mixed.py](source-mixed.py)。两者均接收该
output 路径；仅使用独立数据库。输入地址和 SHA256 在 [inputs.json](evidence/inputs.json)。

## 原生包：空库、深历史、目标重建及保存重启

`native-cold4` 使用全新 profile，**没有行情数据库 seed 或响应替换**。
45m/90m 真实 OKX spot BTC-USDT 双图在首屏后显式左翻页，每格取得至少 500 根。
三阶段对图表闭合窗口的九字段做严格 `repair=none` 区间对照，共 **3,578 根**：
初始深历史、切至 1m/5m 后在同一目标桶内重建、保存完整退出后重启。

增强字段保留实际能力：OKX 未提供的 trades/taker 字段维持 unknown/null，没有填零。
保存重启恢复周期/双图、近期闭合锚点和严格历史一致性；不据此承诺恢复完全相同
数量的已加载窗口。两次完整退出为 **6,427 / 4,785 ms**，各自 10 个所属进程全部退出。

[初始](evidence/initial.png) · [重建](evidence/recreated.png) · [保存重启](evidence/restored.png)
· [摘要](evidence/summary.json) · [完整回执](evidence/native-cold4-acceptance.json.gz)
· [原生脚本](../aggregation-closeout-20261112/native.mjs)。严格读取允许有界等待一致
视图，等待期间不发起新 repair；不能把首个 pending 响应误记为已通过。

## 原生前端保持打开的跨版本恢复

`native-version3` 从无 seed 的新 profile 开始，始终保持同一个 Electron 文档、
两格图表 DOM 和 2m/4m 会话。私有 wrapper 只在同一 endpoint/SQLite profile 上
替换其所属 sidecar：当前包内后端 → main `837783816` 原始后端 → 当前包内后端。
前端没有导航或重载，每个阶段收到新鲜真实 `bar.updated` 帧，严格无修补读取同一
闭合锚点的 OHLCV 一致。

- 三代分别只有 **1 条成功建立的 K 线 socket、1 次 subscribe**；每个目标一次
  恢复订阅。断服期间两次切换各有 8 次未完成握手的有限重试，不能说“总共仅一次
  连接尝试”。同一 socket 的幂等 update 也保留在原始记录。
- 实际 CCXT HTTP 发送边界共 18 次 K 线请求，18 次完成。按“相同完整窗口已由
  上游逐行 confirm=1”审计，当前两代与旧代在本轮均为 **0 次重复**。不能用本地
  时钟经过桶尾替代来源确认，也不承诺不同时间的旧版永远不重取。
- 完整退出 **5,383 ms**，11 个所属进程全部退出。

这是有意控制 sidecar 版本切换、使用真实公网数据的原生前端测试；旧版使用当前
包的相同依赖，并非另一个历史发行包。旧版 991 个后端 app 文件与 `837783816`
逐一一致，当前包 993 个文件与产品提交逐一一致。控制 wrapper 只记录公开请求，
不替换数据响应。[脚本](native-version-roundtrip.mjs) / [wrapper](version-sidecar.py) /
[完整回执](evidence/native-version3-acceptance.json.gz)。

## 包与失败记录

底包由当前正常构建脚本在 `ef8f0e0fa` 生成，使用当前第一方 Pine/Python 插件；
随后仅覆盖本轮修改的两个 Python 模块并重新封签，前端/依赖/插件未变。993 个
tracked backend app 文件与当前产品一致；运行前后 deep strict 签名验证通过。
[封装过程](evidence/package-assembly-final.json.gz) /
[全量文件及插件清单](evidence/package-source-manifest-final.json.gz)。未替换用户已安装应用。

[失败摘要](evidence/failed-attempts.json) 保留首个深历史立即断言失败、早期脚本错误
要求相同深历史窗口头锚点，以及旧 wrapper 被 multiprocessing 重导入的准备错误。
`native-version2` 在干净 wrapper 上真实捕获了重复的完整确认历史窗口，
[失败回执](evidence/native-version2-failed-acceptance.json.gz) 继续保留；本轮因此补接
普通历史读取，而非只用种子专项代替端到端证明。`native-cold3` 在较早产品上也
通过，但关闭使用上面的最终产品 `native-cold4` / `native-version3`。

原始 profile、数据库、未脱敏日志和全部失败现场仍在工作区 output；仓库只保存
受限回执、公开输入 hash、测试日志和截图，控制授权 token 不发布。
[证据文件 SHA256 索引](evidence/index.json)。

## 原 #130 完成定义的交叉核对

| 原职责 | 交付及证据 |
| --- | --- |
| 130-A/C0、130-B/K130 | #173 的只读组成/摘要、字段/覆盖/最终性核心；#269 数字输入；#316 固定/日历、DST/上市边界/归档与实时对照；本轮真实混合九字段补验 |
| 130-C/B130 | #174 公共块、lease/singleflight、#191 GC 原子性；#316 精确足迹、保守失效、饱和缓存及多档共同预算回执；本轮真实混合资源释放和 573 项回归 |
| 130-D 最低消费与 J | #183 H127、#199 前缀/overlay、#316 默认门槛/修订/交付/多图/Bybit 资格、#318 历史覆盖组合；#361 生命周期/存储重绑和单目标页恢复；本轮冷原生/跨版本恢复/请求审计 |
| 数学/修订/释放边界 | K130 参考/跨路径测试，真实 SQLite 新旧回填、amend/delete、晚结果、回滚、lease/预算；官方录制对照与当前 573 项选择；未知最终性不升级 |
| 剩余点逐项核销 | 其他已定市场/周期沿 #316/#318 原始回执，本轮补真实混合与冷恢复；同一活跃桌面跨版本及重复请求审计通过；#361 已验证极小分页排队上界 |

#130 的 P5 明确只要求底座和最低双方消费资格，不要求整个 #127/#129 或全部来源
优化路线关闭。#126 的全 writer/read 审计与共同内存资格、#127 的默认混合选择/
日历执行/首屏调度及性能推广、#129 的共享基础状态/按需预览/窗口外重建，仍归各自
原 issue。Windows、其他来源/接口和无限规模未因本报告自动取得发行资格。
