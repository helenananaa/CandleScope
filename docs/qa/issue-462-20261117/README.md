# #462：forming 缺口恢复专项

最终产品后端：`4a732f172bf693a5b763d3b53048b7f20b7f31b9`；前两轮诊断使用其直接前序 `de5ebad7895ce038fe88de7ddf64a65e7c6108dc`。基线为 #459 / PR #467 的 `256f3f8b53412227e8c1899c6cac0e3516adaf5b`。本项只核销 E；#447、#463 继续开放，整体冷库净 3 秒和最终同包十分钟、完整历史及生命周期没有通过声明。

## 实现与证据边界

既有实现已由真实基础 gap 跟踪 forming 依赖，全部 canonical 来源证明成立后通过 `source_gap_snapshot_required` 要求重新获取快照，不制造目标 final、目标 `SOURCE_GAP_RESOLVED` 或完整性。本次补足缺失的恢复验证，并修复前缀 owner 的一个交界竞态：可选压缩失败后释放临时 slot，锁的等待者会将这种释放误认成目标订阅换代，异常可沿输入派发传播。`hold()` 现在只在**同一原始 target epoch** 内重新查找当前 slot；无 slot 时回到既有普通输入路径，保留其来源、删除与目标围栏。真正关闭重开和关闭进程仍拒绝旧输入，未吞掉修订异常、重建 final 或新增恢复机制。最终增量还确保无 slot 回退在退出前缀任务占用后再交给既有普通输入/闭合修复，避免 owner 重入拒绝。

修复前的真实 SQLite 回归中，同代次释放/替换两个场景失败，换代/关闭两个负例通过；修复后四例均通过。它复现了 #458 留存的同类堆栈，不能据此断言旧轮全部错误只有这一个原因。三次新原生观察均无 `history target generation expired`。

诊断新增有界的 `handoff_rebinds`、gap 的 forming 基础依赖 ID、snapshot 要求累计次数及最后一次记录；沿用既有 market-data-control/storage-health 诊断入口，不增加行情读取或恢复 owner。

## 专项结果

| 层级 | 结果 | 能证明的范围 |
| --- | --- | --- |
| 修复前回归 | 2 failed / 2 passed | 临时 slot 释放与真正生命周期更换必须区分；原始失败 XML 保留 |
| 最终版本 24 个相关测试模块 | **439 passed**，118.42s（前序 438 passed，114.97s 另存） | 多/部分 gap、迟到消费者、重复通知、跨收盘升级、来源失败/重启、关闭重开、修订/删除/身份及前缀/overlay/预览围栏 |
| 新增完整恢复链路 | 四周期各通过 | 真实规范化/SQLite 修复后，旧消费者要求 snapshot；新消费者收到 102、103 两个不同 forming 值，累计体积无漏重 |
| 真实来源受控回放 | **4 个周期通过，36 项数值/缺失合同检查** | #459 原生库中的六根真实 Binance USD-M 1m 输入；跳过两根，部分修复不释放，全部修复后重新 snapshot 并恢复两次实际值；5 个 OHLCV 数值归约通过，4 个无完整证明的增强字段明确缺失，不伪造增强完整性 |
| 原生首轮 | **专项通过，57,704ms 总观察耗时** | 有种子独立 profile；四图首次和页面重新 snapshot 后各至少 4 个不同 forming 状态；201 个 K 线业务帧；44 个 WS/图表/JS 对应样本、24 个实际 1m 来源/目标对应样本；截图可见实际 C 值；已核对全部 1,010 个后端文件、ASAR 与严格签名，退出自有进程树 |
| 原生补充轮 | **形成桶依赖核对通过；四图观察门槛失败**，207,703ms | 848 个缺失 1m 位置实际写入 canonical；四个 forming gap 从等待转为 snapshot 要求并全部退休；当前目标无持久 final 行。最终仍有较早 89m/97m 闭合历史缺口（10/9 个目标位置），前两格 JS 探针未保留；101m/10007m 有 58/49 个不同图表/JS 状态。没有把此轮改判为四图通过 |
| **最终版本原生增量轮** | **专项通过，90,792ms 总观察耗时** | `4a732f172`；使用首轮行情备份，仍非全冷。四图初始/重快照后各至少 4 个实际 forming/JS 状态；413 个 K 线业务帧，42 个目标 WS/图表/JS 九字段匹配样本、42 个实际 1m 业务帧/目标对应样本、13 个 1m API 来源/目标样本、32 个屏幕 C 值匹配。后端 1,010 文件、ASAR、严格签名及完整退出均核对 |

首轮与最终增量轮只证明当前输入、业务 WS、窗口采用、JS 与屏幕实际值，不证明所有历史已齐。最终轮结束显示 204/187/180/80 根，10007m 未满足 128 根门槛；没有将 E 的专项通过写成 F 的首次就绪/EMA20/60 或完整历史通过。第二轮保留了 3 次 timeout 的 `history continuation source revision expired`（来源修订变化时的拒绝）；没有绕开围栏。较早闭合历史补齐、首两格指标保留/配置恢复及忙写时前缀继续读取的联动线索交 #463，相关接口所有权仍为 #446/#452，不能把它们算作 forming 当前目标必须等待自身收盘。

最终轮仍保留修订/代次拒绝日志：continuation 来源修订 8 条终止堆栈（其中 timeout 2 次）、source recovery binding 6、mixed target acquisition 5、native window acquisition 2、indicator generation 1、detached source revision 1。这些是日志出现次数，不能视为独立根因数；实际恢复和值链通过不等于没有错误或长期稳态通过。#463 继续关联忙写、前缀读取和前端恢复，不得忽略这些日志。

前两轮均使用 #459 真实公开行情库的只读 SQLite 备份，**不是全冷验收**。保留集成前端/运行时/插件，覆盖完整已提交后端，重新签名；不是新 release。首次轮和补充轮驱动均按回执 hash 留存，分别为 `native-first-executed.mjs` 和 `native-diagnostic-executed.mjs`；最终增量驱动为 `native-recovery.mjs`。未修改用户日常应用、profile 或全局网络配置。

## 复现与审计

```sh
CANDLESCOPE_QA_PYTHON=/path/to/test-runtime/bin/python bash docs/qa/issue-462-20261117/run-tests.sh
PYTHONPATH=backend /path/to/test-runtime/bin/python docs/qa/issue-462-20261117/replay-forming.py output/issue-462-20261117/public-source-replay.json
python3 docs/qa/issue-462-20261117/check-native.py output/issue-462-20261117/native-seeded output/issue-462-20261117/candidate
python3 docs/qa/issue-462-20261117/check-retirement.py output/issue-462-20261117/native-diagnostics
```

原生驱动沿用 #460 的候选包/Playwright/隔离输出目录/进程专属 HTTP proxy 环境参数，另提供 `CANDLESCOPE_AGGREGATION_MARKET_DB_SEED`；应用启动与需求计时分开。驱动不扣除任何外部时间，净耗时保持未知；三轮实际总观察耗时分别单独列出。不要将其解释成首次每图净 3 秒结果。

`evidence/` 保存原始失败/通过测试回执、真实输入和回放结果、三轮 acceptance、业务帧、来源/工作区时间线、服务日志、数值链核对、截图和包清单（文本按 gzip 压缩）。`SHA256SUMS` 固定所有交付证据。完整应用、行情数据库、control 文件及环境凭据只留本机，不提交。
