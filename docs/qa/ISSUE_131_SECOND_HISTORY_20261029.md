# #131：1s 常规历史实施与验证

基线：`origin/main` / `b84b5e3d514e43fca556613fe107e29d12f7a329`。
分支：`codex/issue-131-second-history`；在独立 worktree 实施。

## 已实现的范围

- 1s 权威收盘与修订共用现有 durable delivery journal，写入成功后发布，失败保持可重试和可恢复。
- 普通历史查询和向前分页可以从 SQLite 读取 1s，并通过现有协调器回补缺口。
- 现有手动下载任务可保存 1s，复用下载集合和保护范围；没有新增下载或录制流程。
- 统一 SQLite 清理支持 `seconds` 档；默认值 86,400 **条/序列**，不是固定保存 24 小时。条数清理仍默认关闭，自动 GC 的原有启用条件保持不变。
- 设置预设的秒级条数：紧凑 3,600、标准 86,400、宽裕 604,800、不限 0。旧的不限设置迁移后秒级仍为不限。
- 1s 的独立内存容量继续生效，与持久化分开；冷缓存可以清除并从 SQLite 恢复。
- 交易所能力检查保持生效，不增加 Binance 合约 1s 路由。没有持续采集器或 1s 回放归档；回放目录仍排除 1s。
- 原有订阅所有权保持生效：全量自选订阅和自定义秒周期仍可能需要 1s；最后一个消费者释放后停止上游流。

## 自动验证

后端相关回归：**362 passed**，4 条现有 FastAPI lifespan 弃用提示。
覆盖权威/非权威收盘、修订、写入失败重试、进程退出后的 pending/committed 恢复、
新进程读回、历史分页/缺口、内存容量、统一清理及下载集合保护、最后消费者释放、
手动下载与不启用 1s 回放归档；同时保留 1m 回归。

运行范围：`test_second_history_lifecycle`、`test_interval_resolution`、
`test_bar_delivery_journal`、`test_bar_delivery_bridge`、`test_query_engine_paths`、
`test_replay_catalog`、`test_storage_retention_gc`、`test_data_manager_gc`、
`test_gc_execution_safety`、`test_gc_settings_validation`、`test_settings_api`、
`test_data_engine_phase1_boundaries` 和 `test_manual_history*`。

前端：设置与 API 测试 **37 passed**；`typecheck`、`check:i18n`（30 locales）、
`lint` 和生产 `build` 全部通过。构建仍有原有的大 chunk 提示。

测试使用隔离 SQLite。复用了本机 Python 测试解释器，只在 worktree 的
`output/issue-131/python-deps` 安装测试解释器缺少的两个、与 requirements 同版本的
代理依赖；未修改原 checkout 的环境。前端用 `npm ci --ignore-scripts` 安装独立依赖。

## Binance 现货真实链路

使用隔离配置与数据库，连接公开行情；直接装配生产 `TransportLayer`、
`BackfillEngine`、`BackfillCoordinator`、`ManualHistoryService`、`DataManager`
及 `ExchangeIngestionFactory`，没有替换行情数据、存储或下载执行器。

| 检查 | 结果 |
| --- | --- |
| BTCUSDT 1s，现有手动下载任务 | SUCCEEDED；60 条；连续范围验证通过 |
| 实时订阅写入 | 观察到 1 条 `data_manager_exchange_closed`；journal pending 0；无 delivery failure |
| 最后消费者释放 | stream 已停止；释放后 2 秒观察中行数未增长 |
| 独立新 Python 进程的普通历史查询 | 从 storage 读取 60 条；complete=true |
| SQLite 完整性 | quick_check=ok |

本地原始证据位于 worktree 的 `output/issue-131/`：
`live_smoke.py`、`live-result.json`、`live-smoke.log`、`backend-regression.log`、
`frontend-tests.log`、`typecheck.log`、`i18n.log`、`lint.log`、`build.log`。
这些文件与隔离数据库为本地验证产物，不作为应用数据发布。

## 验证边界

本次完成代码、集成回归和真实 Binance 后端链路验证；没有进行打包后的 macOS UI
验收、长时间多币种压力测试，或其他交易所的实际连接测试。短时实时样本和
两秒停流观察不代表长期吞吐、磁盘增长或断网稳定性结论。
