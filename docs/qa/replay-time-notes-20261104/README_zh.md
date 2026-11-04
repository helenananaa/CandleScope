# 正式回放时间笔记：首批实现与证据

关联 #166 / #179。应用源码 `4db5ac6a`，main 基线 `395007ac`。本批交付可编辑文本、历史时刻有效版本、回退补记与上下文绑定草稿，**不关闭 #166，也不声称原生包或 Windows 验收通过**。

## 行为与归属

- 沿用前端 managed replay operations 与后端 `DataManagerCore.replay`，TrainingRunService 在已有运行 actor 的串行边界保存；TrainingRunStore 的既有 SQLite transaction owner 持有注释表。没有新的行情缓存、账户或后台网络任务。
- schema 26 → 27 只添加笔记/版本表和查询索引。升级测试逐表比较原有记录；actor 随后正常恢复时会释放旧 controller 并生成恢复 checkpoint，这属于既有恢复行为。
- 笔记记录运行、轨道/数据版本、市场时间、实际保存时间与版本。历史读取同时约束虚拟时间和 review timeline sequence；同一毫秒的后续事件也不能泄漏文本。缺失历史版本明确报错，不替换为最新内容。
- 回看状态只允许新建复盘补记或编辑已有补记，不改写原始计划。笔记保存不会推进源游标、订单或金融快照。
- 同 client ID、预期版本、字段及原上下文的重试返回该次提交的确切版本；并发编辑显式冲突。草稿保留原上下文和 pending submission，重试不借用新时钟。另存为当前时刻新笔记是显式操作，原恢复数据保留；未来事件/时刻的草稿不可在较早视图打开或复制。
- 每运行最多 500 条、每条最多 100 版、单版字段 JSON 64 KiB、运行累计文本及上下文 8 MiB。HTTP 仍受已有完整请求体大小限制；面板输入最多 16,000 字符。尚未提供版本历史分页 UI。

## 验证

| 层级 | 结果与范围 |
|---|---|
| 后端 | 71 项通过：笔记、版本 26 升级、并发编辑、训练 API 和 replay 架构测试 |
| 前端 | 30 项通过：笔记、manager lease、指标偏好、Review rail、通用 JournalEditor；随后同毫秒草稿 key 修正重跑 6 项通过 |
| 静态与构建 | TypeScript、所改笔记文件 ESLint、生产构建、前端架构、30 语言 i18n 通过；构建仍有既有 chunk 大小提示 |
| 后端架构脚本 | 未全绿，10 条问题与 main 日志逐字相同，新增 0 |
| 真实 HTTP / 浏览器 | Chrome 156 + 生产压缩 React，实际 router / manager / SQLite、明确 fixture 行情：5 组流程通过，renderer 异常 / 残留 worker / 外网尝试均 0 |
| 响应丢失 | 丢弃实际 200 提交响应后，面板保留草稿；卸载并新建编辑器后同 client ID 重试，记录/版本数量不增加。这是编辑器重建，不是浏览器或桌面完整重启 |
| 后端完全退出与新进程 | PID 15036 → 15038，共用原 SQLite，4 条可见笔记及版本、回看上下文、源/账户快照一致；两次正常退出均关闭 manager，流及外网尝试 0 |

`evidence/qualification.json` 为机器记录；`browser5-committed/` 含实际界面截图和结果；`http-browser-5/` 含新进程前后数据和退出回执。原始失败（同毫秒内容泄漏测试和升级测试误把既有恢复字段当作不变量）保留在压缩日志中，没有作为通过证据。最早浏览器失败是 fixture controller TTL 到期，TTL 改为 300 秒；未放宽产品校验。

## 复现入口

使用包含项目依赖的 Python，设置 `PYTHONPATH=backend:<bundled-site-packages>`、`PYTHONDONTWRITEBYTECODE=1`。测试不安装新依赖。

```sh
python -B -m pytest -p no:cacheprovider backend/tests/test_replay_training_notes.py backend/tests/test_replay_v2_training_phase1.py backend/tests/test_replay_v2_training_api.py backend/tests/test_replay_architecture.py
```

真实 HTTP：以新的私有输出目录设置 `CANDLESCOPE_NOTE_QA_ROOT` 和空闲 loopback `CANDLESCOPE_NOTE_QA_PORT`，启动 `http_server.py`。随后在 frontend 运行：

```sh
CANDLESCOPE_QA_BACKEND_URL=http://127.0.0.1:<port> node scripts/frontend-script-integration.mjs --replay-notes --out ../output/<private-run>
```

正常退出该服务后，用同一目录/端口运行 `restart_check.py`；它拥有并正常退出两个子进程，核对持久化与 manager 清理。fixture server 在导入后端前安装 loopback-only 网络守卫；它不是产品导入行情能力的替代品。

## 剩余

交易/成交关联、截图绑定版本及揭示边界、版本历史分页 UI、用户导入 BAR/市场成交、更多多商品与重连场景，以及真实已安装包保存/完整退出/重启和 Windows 均待后续。源码、HTTP/组件及后端新进程证据不替代这些验收。

## 完整 CI 同命令复查

PR 首次 macOS CI 在新测试调用 `getItem(key)` 处发现 TS2554。原增量 `tsc -b` 不能代替项目的 `tsc --noEmit` gate，之前类型检查口径已修正。存储适配器补齐标准 key 参数，并拒绝错 key；未放宽测试。完整本地 `npm run check` 最终 exit 0：4869 个 functional、1 个独立性能 gate、130 个 desktop 测试均通过，显式 TypeScript、lint（0 errors / 1 条既有 SingleChartPanes warning）、架构、插件架构、30 locale key 检查及生产 build 通过。初次完整本地检查也发现韩语/巴西葡语不可使用英文占位，现已补齐对应 25 项笔记文案；其余非中英 locale 仍采用英文 fallback，未声称全面翻译完成。失败及修复后的完整日志均在 evidence。远程新 head CI 仍须独立核对。

## 与导入 BAR 整合的原生文本笔记验证

整合应用源码 a355ebe4，依赖 #236 的24f4796d，含 main84feb73f。当前完整前端 npm run check exit0：4869 functional +1独立性能 +130 desktop、显式类型/lint/build/架构等通过；169项整合后端回归通过（4条既有提示），追加2项目标clock测试通过（1项与169重叠）。

原生发现并修复一个实际时钟问题：已有下单检查点后，单轨道可继续提交adapter进度；原笔记错误地一直读取旧global checkpoint时间，导致画面推进后GET422。笔记当前时钟现读取同事务run虚拟时间，checkpoint序号仍绑定CAS；全局cohort写入本来就在同事务同步run时间。回归先失败再通过，双FULL轨道也校验相同已提交global时间。

macOS arm64真实包中，创建事前计划、推进后修改同一笔记为v2、旧时刻API返回v1，均未改变金融快照。保留未保存草稿后完整退出，PID27771→27805恢复原v2和草稿。正常退出会产生新的SHUTDOWN运行事件，旧草稿按原上下文保存返回409，正文保留；通过明确的“另存为当前时刻的新笔记”生成新ID/v1，旧笔记v2和旧恢复数据保留，没有静默重绑定。两次正常完整退出536ms/546ms，renderer异常和外网尝试0。1042源码/SDK、164构建文件、9插件资产、76插件源匹配，前后严格签名通过。

最新原生证据为 evidence/native-imported-bar；restored-imported-replay.png在保存结果刷新及20根5m历史真正加载后截图。更早的restored-saved-note-and-draft.png只记录保存后刷新中的中间画面。此前原生失败、旧检查点时钟回归失败及最终通过日志保留。当前native是文本笔记/版本/草稿限定范围；实际图形Review回退、截图和交易关联尚未验收，整个#166继续开放。
