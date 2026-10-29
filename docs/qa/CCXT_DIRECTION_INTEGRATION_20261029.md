# CCXT 公共行情方向整合记录

> 本文记录最初的整合基线。后续统一 provider、公平调度、归档准入、正式发布及新增验收以
> [PR #145 完成度更新](CCXT_DIRECTION_COMPLETION_20261029.md) 为准；下文“仍然保持草稿的原因”是当时状态。

本分支把来源完整性、K 线时间边界、归档导入和公共请求调度作为同一个审查单元。保留四个原 PR 的全部提交和历史 QA；下面的整合验证与原 PR 的独立验收分开记录，测试数量不相加。

## 范围与来源

基线：`b84b5e3d514e43fca556613fe107e29d12f7a329`。

| 原 PR / Issue | 纳入的提交 | 负责的能力 |
| --- | --- | --- |
| [#141](https://github.com/helenananaa/CandleScope/pull/141) / #113 | `651071db2f85ea232caade465cc89a7678122f35` | 固定 fork、四条市场链路的源字段及闭合证据、源修订、冷归档、历史补证 |
| [#142](https://github.com/helenananaa/CandleScope/pull/142) / #117 | `b5338d65579e353b924bb114b51cb7d7eda83df2` | 原生时间边界、固定锚点、日历周期、身份传播、旧行隔离及 Pine 候选补丁 |
| [#143](https://github.com/helenananaa/CandleScope/pull/143) / #125 | `b0ea65a243a6d4beb7b05aca0e7f9f67808d222e` | 每次物理 HTTP 尝试、WS 控制、共享元数据和目录 IPC 的公共准入与前台优先级 |
| [#139](https://github.com/helenananaa/CandleScope/pull/139) / #124 | `ff0d92893e88f1feb6c730dd2d8962b1d3b9ab5f` | 默认入口归档路由、代理租约、持久导入证明、ZIP 清理与回放重试 |

原 PR 关闭表示被总 PR 接替，不表示已经合入 main 或关联 Issue 的所有验收完成。#137、#138、#144 保持独立，不隐式纳入其实现或验收结论。

## 整合处理

- CCXT 客户端同时保留原始响应捕获、物理请求准入和 owned resolver；普通创建与 raw-hook 创建分支、四个市场 profile 都绑定公共预算。
- 目录加载同时保留调用方优先级、限定市场范围及关闭后的保护。OKX 同时保留 WS 443 配置、UTC REST/WS 周期映射和重连逻辑。
- 历史分页采用明确的 interval 边界，避免固定秒数替代月历边界。
- 新增真实本地 HTTP 组合检查：CCXT 内部失败重试分别结算预算，只捕获成功响应；真实 fork 的历史请求贯穿目录、时间、K 线请求，保留精确源字符串、闭合证据及规范时间边界。
- 历史补证增加显式 `--legacy` 入口，从 `klines_legacy_basis_v1` 选择原生身份的旧行。先保留审计，再重新抓取并通过正常规范化/交付路径写入 active 表；不直接搬回旧值、不修改隔离表。旧源 journal 的已交付标志不能替代 active 投影检查，失败可重试，成功可重复运行。
- Provider sidecar 测试使用真实 permit 管理器，并在直接驱动 BackfillEngine 的测试入口模拟协调器等待；Windows TLS 测试向显式连接器注入测试 CA，保留证书校验。
- 新增 `CCXT integration` CI 和统一后端检查入口。CI 构建并校验锁定 wheel，强制运行 fork 合同，避免缺少 fork 时静默跳过相关测试。此工作流不改变发行包依赖或默认启用开关。

## 组合验证

环境：Windows Python 3.12.7 隔离 venv（共享主机依赖，只在本地 venv 安装补充依赖），独立 DATA_DIR；fork 使用 WSL Ubuntu Python 3.12.13 构建，再安装通用 wheel。未修改用户生产库。

锁定 fork：`43f7d748b22757873e1b81776e150ca67b67da07`；上游基线为 4.5.60。重新构建 wheel 的 SHA-256 与锁文件一致：

```text
8520ad4b0f9004f6340da3da49ec7f455fc7579d85cb375d145741f3806f625c
```

最终后端组合检查：**587 passed，0 skipped，142.00 秒，退出码 0**；包含最终 legacy 投影检查和 Pyne 退役回归。保留 1 项 aiohttp 弃用警告，以及测试进程退出时的 Binance 未关闭会话提示；后者尚未定位，不将本次结果视为无资源清理问题的证明。此前一轮同范围检查为 587 passed / 144.39 秒，不重复计数。

统一复现入口（先使用隔离环境运行 `backend/scripts/install_ccxt_fork.py`）：

```text
python backend/scripts/ccxt_contracts/integration.py --timeout=90 --junitxml=../output/ccxt-integration/backend.xml
```

前端：architecture、plugin、30 个语言目录、TypeScript、ESLint 通过；功能测试 4,441 passed / 1 skipped；独立绘图性能 gate 1 passed（本机 p95 0.124 ms）；桌面测试重跑 123 passed；生产 Vite build 通过，保留大 chunk 提示。首次 `npm run check` 在桌面本地 MCP 的一次 `fetch failed` 停止；未改写成一次全绿，也未改动该无关模块。重跑整个 desktop suite 后单独完成 build。

保留的早期后端失败：未安装 async pytest 插件的收集失败；vanilla CCXT 初轮 357 passed / 55 skipped / 2 failed（provider 测试替身接口和 Windows 测试 CA）；安装 fork 后 410 passed / 4 skipped / 1 failed（直接 BackfillEngine 的测试未模拟新的延期调度）。这些失败引导了上述测试适配，不作为最终验收结果。

本地日志、JUnit XML 和构建 provenance 在 `output/ccxt-integration/`；CI 上传自己的 JUnit 和 wheel 构建证明。旧分支 QA 文件保留原样：

- [源数据扩展及 fork 多语言证据](ISSUE113_CCXT_SOURCE_EXPANSION_20261029.md)
- [时间边界及 Pine 候选验收](ISSUE_117_BAR_BASIS_20261029.md)
- [公共准入设计与复现](../public-market-admission.md)
- [归档导入及清理](issue-124-archive-completion-20261029.md)、[原生回放恢复](issue-124-native-replay-recovery-20261029.md)

## 仍然保持草稿的原因

| 方向 | 当前可审查实现 | 尚未完成的验收或统一工作 |
| --- | --- | --- |
| Fork 部署与 provider 收敛 | 固定版本、wheel 哈希、四市场源字段及源修订路径 | 默认依赖仍是标准 ccxt，fork 默认关闭；尚未统一 primary/generic provider 架构，其他交易所和私有接口不因此获得资格 |
| 时间边界与 Pine | 显式边界和迁移已纳入，Pyne 继续保持退役 | 发布中的 Pine runtime 未包含日历能力；候选补丁需要正式版本发布及支持平台验收，OKX 历史 REST 真实环境验收仍有缺口 |
| 归档与准入 | 归档有进程级跨 loop HTTP gate；REST/WS 有预算 owner 的公共调度；各自合同纳入总检查 | 两套 gate 的正式 archive demand/permit 适配仍需收敛；没有证明跨多个后端进程的全局额度统一；真实双出口、OKX 归档在线合同、新来源生产资格未完成 |
| 生产运行与桌面 | 保留原分支的受控回归和历史 live/原生证据 | 本次未重新做四市场 live、原生发行包、长时高负载、冷网络 P95 或完整桌面验收；原生退出 sidecar deadline/冷启动性能仍待处理 |
| 邻接数据治理 | 源 revision 和持久归档回执已在同一分支 | #138 / #126 的持久提交 revision、#135 质量与修复归属、#112 恢复归属和 #132 全量能力模型另行跟踪 |

迁移仍有实际运行影响：首次初始化会备份并隔离未版本化 active K 线，需要额外磁盘空间和重新获取数据。`--legacy` 补证须对停止运行的离线 profile 显式执行，默认仅预览，写入需加 `--apply`。原始用户数据和历史 QA 均保留。
