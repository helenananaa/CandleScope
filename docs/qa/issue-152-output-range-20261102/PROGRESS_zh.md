# Pine 已显示时间范围与标记协议修复

产品提交b5e79488、fe0a65b8、40f2b544；已整合main #224/437eba53，Pine、SDK、宿主supervisor及payload所有者字节未因该合并改变。该工作引用#152，不关闭整个issue。

## 实际问题与修复

实际锁定引擎中，`plot(close,offset=-1)`在形成中close从102变为103时，上一根显示位置的值已变化，但宿主按当前源bar_time裁剪后，WebSocket补丁的data为空。原始引擎/桥接/宿主回执在evidence/negative-offset-before.json.gz，驱动同时保留。时间样本包含实际间隙，修复不通过减去固定周期猜测目标时间。

桥接以同一已验证输出前缀计算`meta.outputUpdate`：包含旧尾部删除和新尾部的显示时间范围。宿主使用既有`indicator.replace_range`，一致裁剪全部定时投影，空数据也会清除旧点；未使用的嵌套完整Render IR不进入范围帧。初始、恢复、历史修正、结构变化和不能证明输出基线时采用完整快照，范围包含被滑动输入省略的保留前缀。对象scene沿用完整替换。未知或无效更新声明也交付完整快照，旧插件无声明时保持已有契约。协议详见docs/architecture/RENDER_UPDATE_RANGES.md。

真实wheel的标记消息又复现了数字size=2被前端字符串协议拒收。桥接现在保留Pine的auto/tiny/small/normal/large/huge符号值，6个实际引擎用例覆盖该映射。不改变数学、OHLC、费用、撮合或支持的形状集合；不恢复Pyne。

## 当前证据

- 实际pinned engine下完整桥接包240项通过、1项原有能力跳过（compact external append不具备）。宿主组合45项通过，包含新增可靠范围帧背压测试；满队列要求重新同步，不把旧时间范围变化作为尾部preview丢弃。
- 正式PluginInstaller全新安装当前SDK/桥接wheel，真实RuntimeSupervisor执行16步输出和44步输入比较通过，4个进程正常停止。包括滚窗、修正、会话淘汰、错误基线、进程重启与journal恢复。比较完整语义时只排除新的outputUpdate传输范围元数据，并独立验证它；其余输出、诊断、输入和执行元数据仍严格比较。
- 七组真实进程+正式payload适配器冻结消息：负偏移曲线、na删除、标记、背景色、最后标记记录消失、旧历史修正、show_last。前端正式parser/dispatch/reducer/范围替换/cache采用后与完整结果一致，另有独立值、删除和时间断言。58项相关前端检查通过；最后7组再次通过，TypeScript与改动文件ESLint通过。
- 新bundle为13a57c1901dd0a902fdefcea73ccabb5c8f3c93acba1b16ef74b6ad3d1f9cb09，桥接wheel为5878bf5e3e16fdf23fe3f4e575d9944cb95a72d5f5db592acc6748cff8198db0。SDK wheel仍ede643...，引擎wheel仍06c009...；桥接源摘要9b6fb85c...。bundle-source-check.json核对当前76个SDK/桥接源文件与wheel精确字节及当前来源指纹。历史发布锁、保留应用/profile均未改写。

## 实际IPC范围

measure_transport.py观察真实stdin/stdout帧，不替换响应；相同当前代码，关闭两种协商补丁的对照与正式协商路线交替执行，3规模各3次30 tick。完整调用者语义相同，18个进程均停止。这个对照不是“本PR前后的性能变化”：既有SDK输入/输出补丁在main220中已经工作。

| 历史bars | 对照请求bytes | 当前协商请求bytes | 对照响应bytes | 当前协商响应bytes |
| --- | ---: | ---: | ---: | ---: |
| 1,000 | 101,410 | 553 | 137,772 | 3,079.5 |
| 10,000 | 1,010,410 | 554 | 1,361,774 | 3,085.5 |
| 50,000 | 5,050,410 | 554 | 6,801,774 | 3,087.5 |

表为稳定tick帧大小中位数；种子另存。当前50k协商往返P50三次约21.03/11.53/11.89ms，对照约1958/1083/1048ms。本机同期观察到其他高CPU进程，逐次时延完整保留，不能据跨轮差异宣称新增优化收益、回退或产品SLO。JSON观察和完整结果比较在计时后执行。main220/f9a075包的早先9次实测也单独保留，不混成当前资格。

## 失败与范围限制

首次进程检查在故意丢失bars基线时，旧测试把新的snapshot范围元数据与对照range元数据直接比较而失败；保留日志，补上独立恢复声明断言后重跑。旧marker size导致前端拒收的原消息/失败日志保留；原包6274d230和controlled install仍在output。最初测试源默认xcross不受支持，以及结构消失不能要求范围模式的测试判断也保留，已改为受支持circle与明确结构快照断言。测试的可选range类型检查失败记录与修正后检查分别保留。

本地真实进程和前端模型证据不等于原生LIVE界面、在线冷加载、Windows或完整发布验收。当前提交CI仍需资格。native.result()仍完整物化；宿主仍准备窗口、重复source/context、完整对象scene和部分O(N)处理也未消除。没有复制Pine引擎或为了传输量截短计算历史，不能宣布整个#152完成。

Binance公共IP冷却截止2026-11-02T16:14:01.202Z前，未为本轮启动LIVE应用或请求公共来源。#200/#149/#177的线上原生补验继续遵守此限制。
