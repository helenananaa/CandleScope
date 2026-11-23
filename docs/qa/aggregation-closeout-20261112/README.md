# 聚合议题补缺：目标生命周期与小分页恢复

日期：2026-11-12（Pacific/Auckland）。关联 #126、#129、#130；交付 PR #361。

基线 `83778381611f67b0835a7dce8a1bde08f48b9837`；产品提交
`17e57c043ea369edfc9cc01aeeb0c5a534dec854`。本阶段不关闭父 issue。

## 已复现并修复

同一目标桶内关闭最后一个消费者、取消旧恢复、再创建相同派生周期时，暖启动服务
原先只按 `SeriesKey + bucket` 保存已安排修补的标记。新目标会复用旧标记，无法
重新申请尾部修补。替换 canonical storage 后也会保留这一旧标记。

现在复用聚合器已有的目标代际；新目标可重新申请，同代消费者仍去重。存储重新
绑定时清空旧需求标记。标记仍保留原有的 2,048 项上限，不增加 writer 或修订账本。

将两条新回归复制到 `git archive origin/main backend packages` 的独立目录，在
相同 Python/依赖下运行，**两条均失败**（实际只有一次触发，预期两次）。产品
提交上的同一回归通过。测试不访问用户数据库。

## 本地验证

- 最终产品树：聚合核心、B130、真实 SQLite 共享块、H127/历史前缀、实时增量、
  暖启动、回补调度、回环 HTTP 与派生修订围栏，**522 passed**；41 条警告均为
  aiohttp 对当前 Python 已修复 cleanup 行为的弃用提示。
- 最终暖启动/调度专项：**52 passed**。集合重叠，不相加。
- 后端架构与 `git diff --check` 通过。
- [当前 head 的 CCXT integration](https://github.com/helenananaa/CandleScope/actions/runs/43135675077)
  中 `pinned-fork` 成功。该变更没有触发按打包输入筛选的 macOS 云端工作流。

新增回环场景使用实际 CCXT provider、HTTP socket、BackfillEngine、SQLite 和
GapLedger：Bybit 线性/反向永续 `5m → 10m`，调度 `chunk_bars=1` 与默认上限
分开验证。配额延期、停止、重新创建 runtime、重放账本后，两根目标各采用一次；
受限来源不绕过服务端冷却。默认上限原有的 amendment/delete 围栏仍保留。

持续前台请求下的调度用例独立于真实 socket 资格：单 lane、单目标分页、一次
延期和四个目标，检验新恢复及后续页有界取得执行机会，重复请求共享父需求，
结束后无活动任务。该用例证明调度决策，不宣称公网延迟 SLA。

## macOS arm64 原生包

本工作树重新构建 `CandleScope.app`，991 个受版本控制的后端文件逐一与包内 SHA256
一致；运行前后 `codesign --verify --deep --strict` 通过。包内只有当前 Pine/Python
指示器运行时，没有恢复 Pyne；退役入口回归 **8 passed**。

隔离 profile 仅通过 SQLite backup 复制此前公开行情 QA 的 canonical 数据库；未复制
准备缓存或用户布局。**这是已有基础行情下的恢复验收，不是冷库首次加载资格。**
公开 OKX 连接未替换响应。结果 [native6-acceptance.json](evidence/native6-acceptance.json)：

- 45m/90m 双图各 128 根已闭合记录，与严格 `repair=none` 后端区间读取比较 OHLCV。
- 切到 1m/5m、释放派生目标，再于同一目标桶内切回，128 根历史锚点及数值保持。
- 保存后完整退出，再启动同一 profile，45m/90m 布局和严格区间结果保持。
- 三阶段共 **768 根**闭合记录比较，renderer error 为 0。
- 两次退出分别 **3,530 / 5,636 ms**，各自 10 个所属进程均退出。

截图：[初始](evidence/initial.png)、[重建](evidence/recreated.png)、
[保存重启](evidence/restored.png)。复现脚本 [native.mjs](native.mjs)。128 根是当前
分阶段可见窗口；未据此声明自动扩展到 500 根或深历史验收通过。

此前尝试也保留：[失败摘要](evidence/failed-attempts.json)。前三次空 profile 运行
未完成原脚本的 500 根或就绪条件，不算冷启动通过；整 profile 克隆触发绝对路径
cache ownership 拒绝，属于无效验收准备；另一次原生启动超过旧脚本 90 秒等待。
当前 runtime 的归档能力探测仍在启动就绪之前等待，需单独处理其延迟。未把这些
失败归因于已经证实的上游限流，也未用暖库结果覆盖它们。

## 证据

[证据索引及 SHA256](evidence/index.json) 包含最终 522 项日志/XML、52 项专项、
未修复基线的两条失败回归、991 文件包内清单、原生回执及截图。测试集合重叠，
不累计。原始 profile、行情 DB 和控制连接凭据不进入仓库；原始运行数据仍保存在
工作区 `output/aggregation-closeout-20261112/`。

## 父议题仍需核销

| 议题 | 本阶段贡献 | 剩余关闭条件 |
| --- | --- | --- |
| #130 公共底座 | 同桶目标重建/存储重绑恢复修复；小分页配额和账本恢复组合 | 活跃桌面跨版本/请求去重、其余既定市场与周期的跨路径证据、资源矩阵 |
| #129 实时执行器 | 目标生命周期恢复不再被旧需求标记压制 | 按需预览、跨目标基础状态共享、窗口外修正/重建及压力验证 |
| #126 一致性与预算 | 存储重绑不误用旧需求状态 | 原清单的消费者/writer 审计、整体内存与长时资源资格 |
| #127 历史执行器 | 本 PR 不交付混合执行 | 混合覆盖/资格、执行接线、共享与首屏调度、真实冷热性能 |

原 issue 的要求、历史证据和平台边界继续有效；原生结果与受控数据、组件和
录制输入分别记录。
