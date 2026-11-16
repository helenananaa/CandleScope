# R129：闭合组成退休、规范恢复与提交屏障

基线 main `bbd7087ac9fb8885121cb0fdcab5264a73f247a3`；首个产品候选 `cc8a6b594`，最终产品 `cf2957c639477eb0f042270a765acdd6a293ec0f`。后续仅补文档、脚本、原始证据；最终包全部后端文件与 checkout 逐一校验。

本批补 #129 的 closed/no-prefix 组成保留及退休组成的修正，消费既有 H127/B130/D126。仍保留 compact builder 的旧组成重建，与 **builder 本身已被逐出后的完整窗口外恢复** 是不同范围；后者及完整原始资源/来源/消费矩阵继续，不据此关闭整个 issue。

## 行为与 owner

默认 COMPONENT、已 authoritative CLOSED、合格原生固定网格、完整已流逝覆盖，可把原组成索引替换为既有 immutable H127 prefix。有初始前缀和没有初始前缀均支持；仍使用原 65536 来源 slots 上限。退出前逐页比较至多128个已接纳 leaf 与可信规范行，再由原 K130 计算和比较九字段、能力 mask、计数与时间投影。汇总相同但单条相反的修正不能获得退休许可。

可选退休保留 status/finality/close reason、创建/更新时间、接纳/计算/已发布水位、原 acquisition 与删除权限 floor；没有新的发布或规范写入。预算、容量、字段/网格/身份或修订不合格，保留原索引和明确诊断。`BAR_AGG_COMPACT_CLOSED_COMPONENTS=false` 禁用新的可选维护，不停用已有前缀的必要恢复。

H127 runtime 只新增最多128项 IDs/epoch/source spelling 待办，消费原 realtime-state 预算，每项1KiB；不持有 builder/raw 输入。原 timeout loop 每轮排空一项，没有新 timer、后台 task、来源订阅、持久 writer、修订账本或全局缓存。昂贵的分页在目标锁外，最终修订验证/采用才使用原目标锁。同目标下一形成桶可以继续接纳；并发修正、重绑、解绑和取消使旧读失效。旧读失败的局部 slot 清理必须保留同目标较新待办及已有前缀。

物理工作通过既有 publisher payload 登记保留状态，并在原预算中预留冻结索引/证明图全重及有界 staging 空间。解绑后仍计量在途图，取消等待物理工作退出，所有 scope 正常/错误/取消释放。H127 自身继续按256 slots页面和既有 B130 lease/cache 预算工作。

## 持久接纳与真正完成

原 publisher 返回时可能只是 durable admission，原 dispatcher 仍拥有 native commit。退休先排空这个 owner 再取得规范快照。覆盖前缀内的已闭合输入也必须先等待该提交，不能因旧 revision 暂时不变就忽略来源修正。

已经 closed 的目标发生来源修正时，从完整规范窗口重建；复用 D126 canonical recovery 协议，fresh acquisition 不替代旧 explicit-delete 权限 floor。新读不能复活用户显式删除的目标。缺失/不可信覆盖撤销原 close，保持 gap/provisional 或要求恢复。持久证明从逐条来源回执转换为规范前缀及事务内版本验证，后续 amendment 使用相应规范来源标记；不伪造保留 source_ref。

`baseline-source-commit.log` 在完整旧版后端复现了提交屏障缺口，关闭可选退休、已有6条前缀+1条尾部：暂停原 dispatcher 后，来源修正已 admission，旧目标回调却在 native commit 前结束，未等待该 owner。新版两种实际 pinned CCXT OKX 回执路径分别验证已全部退休与仍保留接缝的修正，最终只新增一次正确 amendment，并由原 writer 读回。

## 检查与失败证据

- 最终完整 CCXT integration：**2218 passed / 66 warnings / 264.62s**。架构检查通过。
- 新增23项：21个状态/owner/维护测试和2个真实 fork 回执测试。完整集成纳入全部；stock 四平台 Pine host 只纳入无需 fork 的21项。
- 7m/89m/10007m、已有前缀/无前缀、旧极值和总量修正、缺失与相反 leaf 修正、未知字段不误提升、显式回退、源/配置/策略重绑、工作预算拒绝、同版本不重复维护、物理读期间取消/解绑、旧读失败保留新待办、删除前缀/全部数据/显式目标、容量和一轮一项、原 timer 与同目标下一桶形成输入并行均覆盖。
- 原生/独立受控检查并不证明所有消费者、所有来源、长时资源、builder 已逐出后恢复或完整性能矩阵。

开发失败全部保留：initial 的遗漏 BarStatus import；initial2/3 的 fixture 未声明已知增强字段；大桶在 native commit 尚未完成时被原 revision fence 正确拒绝；增加原 dispatcher drain 后通过。lifetime/sources 的诊断字段名错误已修正。早期完整选集 ci-initial 为2213通过/1失败，真实回执仍保留接缝的修正暴露旧 acquisition floor，随后补完整规范恢复及显式删除权限。jobs 初次未等待 durable dispatcher 完成便查询规范库，改为等待其既有交付。`newer-job-regression.log` 在首候选准确复现旧 slot 清理删掉新待办；修复后23项与最终完整选集通过。原输出、app/profile/SQLite 均未删除。

## 同输入成本与证据范围

`cost.py` 在完整旧后端、最终后端禁用可选维护、最终启用维护的独立进程，各运行45m/15m、90m/30m（3个组成）和10007m/1m（10007个组成）。种子构造/规范批写/受控源索引建立在计时窗外；最后一个原生输入走原 DataManager callback/router/bridge/持久 writer。所有正式 trial 和热身的规范行九字段/边界/source 与消费者事件哈希跨模式相同，最终 reserved=0。

每组1次热身、3次 process CPU/墙钟采样，另一次 tracemalloc。成本脚本暂停原自动 timeout task，单独调用同一个维护入口，区分输入回调返回和维护工作；原 timer、下一桶输入及真实网络另有单测/原生证据。等待 dispatcher 的其他时间不冒充已被完整测量的端到端闭合延迟。source hash 在采样前后冻结并记录。

| CPU中位 ms | 旧输入回调 | 新禁用输入回调 | 新启用输入回调 | 新独立维护 |
| --- | ---: | ---: | ---: | ---: |
| 45m / 15m | 54.837 | 54.098 | 52.050 | 24.787 |
| 90m / 30m | 49.115 | 56.139 | 51.298 | 24.663 |
| 10007m / 1m | 47.835 | 57.419 | 45.520 | 1805.157 |

| 保留/分配 | 旧45m | 新45m | 旧10007m | 新10007m |
| --- | ---: | ---: | ---: | ---: |
| 原组成数量 | 3 | 0 | 10007 | 0 |
| 单状态可达图字节 | 7953 | 4080 | 11392221 | 4194 |
| 登记 owners 合计去重可达图字节 | 28358 | 26937 | 11412737 | 619787 |
| B130 entries | 0 | 1 | 0 | 626 |
| 独立分配 peak 字节 | 112950 | 131639 | 503537 | 2869356 |

10007m 保留图的下降包括新增公共块、owner 元数据和其他登记根；不是仅统计原组成。独立维护付出约1.81秒CPU，分配peak约5.70倍；45m/90m也增加维护工作和分配。没有宣称总CPU下降。原状态数据在 tracemalloc 开始前已有，故分配peak不含它；不据此推断进程峰值。

机器负载未冻结，有并行原生/CI；这些是受控、无网络、无来源回执的成本采样，不是RSS、稳定P95/P99、闭合吞吐或整应用资格。candidate1成本和所有失败也保留。MemoryBudget measure_heap 是登记Python值的去重图，不含外部/分配器/SQLite/plugin进程内存。

## 最终 macOS arm64 组装资格

保留 frontend/runtime/plugins build `ef8f0e0fa6df299a823f4460b701eb1c3c98361f`，覆盖全部 **1002** 个 tracked backend app 文件；最终产品为 `cf2957c639477eb0f042270a765acdd6a293ec0f`。所有文件、asar哈希及前后严格签名通过，是全后端覆盖组装包，不冒充新 release build。

两独立全新profile、真实公开OKX REST/WS，无seed、响应替换、bootstrap hook或额外观察订阅，仅隔离进程使用既有本地proxy。45m/90m首开及显式左翻页至每图500 → 1m/5m各500 → 目标释放/重建 → 保存、完整退出、重启。常规流程累计 **4450** 根已闭合九字段比对通过。

独立见证流程在重建后通过公开图表配置改为2m/7m，等待真实2m source close及原 timer自动维护。公开只读diagnostics记录 `interval=2m / components=2 / reason=compacted`，该已闭合图表K线九字段与strict canonical一致。随后恢复45m/90m并保存重启，累计 **5614** 根常规闭合对照，另单独验证该2m闭合值。driver没有调用维护入口、注入输入、增加观察消费者或改变生产限流。所有最终四次进程树退出为10/10；七张截图直接查看，图表已绘制。

截图中盘口仍有连接中，2m/7m新桶有实时等待状态；未把这些计为全行情面板或持续无断线通过。该见证证明小桶真实接线，不代替原生10007组成、迟到修正注入、forming oracle、Windows/Intel桌面或长期压力。完整大桶/修订/取消由受控层明确分别证明。

首候选cc8的两个原生流程同样通过，但后补竞态测试发现新待办被删除的问题，因此最终重新组装并复跑两独立profile。两代app、manifest、签名、完整回执均保留。`archive.py`只遮蔽临时字符串contextToken，保留数值active_read_tokens；source-hashes与evidence-index可复核。

## 仍按原 issue 关闭条件继续

尚需完成：builder本身被逐出closed缓存之后的有界完整窗口恢复（当前旧来源回读仍可能整桶展开）；未合格来源/网格与资源压力下的状态窗口策略；所有来源/消费者、语义屏障、独立forming及指标/策略、长期与多目标CPU/RSS/延迟矩阵；#126/#127的其他writer/read、归档载荷与首屏调度。原始范围不变，本批不是整个议题验收完成。
