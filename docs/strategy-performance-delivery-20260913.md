# 策略执行性能优化提交汇总

本次将 `codex/strategy-replay-performance` 在 `daa1be34` 之后连续几轮相互依赖的优化合并为一个本地提交。各阶段文档中的“未提交”描述是当时的工作状态；本文件汇总最终交付范围。未推送、未部署，前端分页接入不在本次提交内。

## 提交范围

- 同一 worker 内的逐根 Python/图表策略输入、输出和成交反馈优化；保留对象隔离、V1 回执、异常及兼容回退。
- 可选 CPython 原生扩展源码及 wheel 构建、安装验证脚本；标准 SDK 输出布局声明、短 Decimal 缓存，以及显式选择的批量 SMA 协议和示例。
- 紧凑 worker 事件传输、成本敏感性计算共享、报告复制减少、增量检查点和报告分块持久化。
- BAR 每任务检查点策略、报告摘要和分页 API；旧完整报告及导出格式保持兼容。
- 相关回归测试、实际 worker 基准脚本及各阶段验证文档。

编译产生的 `.pyd`、wheel、临时数据库及原始大体积输出不纳入 Git。原生扩展在没有安装或不兼容时回退；新 checkout 要按 [构建说明](../backend/native/README.md) 安装并验证实际加载路径，才能复现原生加速。

## 最终状态与证据

数据库 schema 为 **9**。原生入口、SDK 字段直读、增量检查点、反馈直传、报告复制优化及分块报告默认开启；未证明稳定收益的专用 BAR 循环默认关闭。任意策略不会被自动切换到批量 SMA 协议。

10 万根最终三对样本的普通组中位耗时：SMA 5.865 → 4.965 秒，FEEDBACK 5.664 → 5.119 秒，ORDERS 6.073 → 5.331 秒。密集成交组 15.173 → 15.819 秒，波动较大，不宣称稳定提速；33,186,350 字节的报告已能完成保存、重读与哈希校验。完整范围、逐对回退样本、API 限制和离线回退步骤见 [最终策略优化记录](strategy-policy-optimization-20260913.md)。

提交附带 `performance-evidence-20260913/policy-pairs-summary.json`，保存最终成对样本耗时和读取统计；`validation.json` 保存本次提交前复跑的测试结果与原生模块校验值。它们是本地验证证据，不代表生产部署资格。

提交前复跑：后端相关回归 **320 passed**，SDK 全部测试 **48 passed**，均无失败或跳过。后端有 4 条既有警告；`git diff --check` 通过。本次仅整理交付和文档，没有重新进行性能实验。

旧阶段的细节分别见 [原生适配](generic-python-native-performance-20260913.md)、[输出与进程传输](strategy-output-spawn-performance-20260913.md)、[Host 热路径](strategy-host-hotpath-performance-20260913.md)、[四项后续优化](strategy-four-paths-performance-20260913.md)。历史绝对耗时不可跨轮相除推断收益。
