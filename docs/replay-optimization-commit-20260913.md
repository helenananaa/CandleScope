# 大周期回放优化候选提交整理

本次按用户要求将已有回放优化整理为本地提交。提交不代表性能验收通过或正式启用，
`REPLAY_MULTI_BAR_INTERVAL_ENABLED` 继续默认 `0`，SQLite `synchronous=FULL` 不变。

范围包含前期尚未提交的控制器准备、不可变价格块、空闲 WAL 检查点、低点与终点
分阶段原子提交、按需组合曲线及导出，以及本轮阶段投影、周线批量估值、尾步原子
提交和恢复修复。配套 API、界面、翻译、测试和设计约束一并提交。
插件升级、Pine 适配及指标订阅身份相关改动留在工作区。

## 性能证据边界

- [阶段投影报告](replay-phase-projection-20260913.md)：限定八持仓场景日线
  100 次主图更新 P95 为 179.6ms；这不是最终周线候选的完整重新验收。
- [周线估值报告](replay-weekly-valuation-20260913.md)：组合计算降至约 1ms，
  仍保留精确整数越界回退和完整同时间事件批次语义。
- [尾步提交报告](replay-terminal-cohort-20260913.md)：末次推进事务从 11 降至 3，
  财务等价、回滚及提交后进程退出恢复通过；浏览器候选尾步约 298–329ms，
  近期旧版对照约 239ms，尚未证明端到端收益。

周线 100 次验收未完成，物理像素呈现未测量。后续应先固定环境进行前后对照，
确认候选收益再做启用验收。此次整理不重跑长时间性能测试，也不改写历史测量结论。
原始数据库和浏览器诊断保留于各报告指向的本地 `output/`，不纳入 Git 提交。

## 提交前复查

- 后端 59 项通过（267.66 秒）：`test_replay_multi_interval_service.py`、
  `test_replay_multi_phase.py`、`test_replay_phase_projection.py`、
  `test_replay_portfolio_batch.py`、`test_replay_portfolio_export.py`、
  `test_replay_prepared_controls_and_prices.py`、`test_replay_terminal_cohort.py`、
  `test_replay_idle_checkpoint.py`。覆盖财务等价、提交屏障、取消、回滚和进程退出恢复。
- 前端 `npm run test:replay` 403 项通过；`npm run typecheck`、
  `npm run check:i18n` 和涉及回放组件/API 的 ESLint 通过。
- 本轮投影、估值、尾步模块及其相关测试 Ruff 通过，暂存区 `git diff --check` 通过。
- 验证在当前工作区运行，提交范围内源码与暂存区一致；无关改动未清理。
  本次没有声称全仓库测试通过。历史既存只读快照测试失败仍见阶段投影报告。

本次测试 XML 和前端检查日志位于 `output/replay-terminal-20260913/commit-*`。
