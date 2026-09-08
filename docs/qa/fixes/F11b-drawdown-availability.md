# F11b 最大回撤缺失原因与统计口径

问题：最大回撤为空时，卡片仍固定显示“按已实现结果统计”，未说明不可用原因，也不符合新版报告按权益采样计算回撤的口径。

核对：backend/app/backtest/reports.py 仅在 REPORT_SCHEMA_V2 时填充 performance；权益曲线可以独立存在。metrics_v2.py 的 _drawdowns 在不足两个权益采样点时返回空指标，风险指标 reason 为 INSUFFICIENT_EQUITY_SAMPLES。因此有曲线不代表报告已提供最大回撤，不能据此断言计算错误。

修复：分别说明报告未提供指标、权益采样不足、报告标记不可用；存在指标（包括真实零值）时说明按报告权益采样统计。九种语言同步，详情增加原生悬停提示，窄卡片截断时可以读取完整文本。不从图表采样另算指标，不改变报告或曲线算法。

验证：5 项结果视图测试通过，覆盖上述状态及既有视图行为；TypeScript、相关 ESLint、九语言检查、Production build、git diff --check 通过。电脑操控生产构建重新运行 SMA Cross，441 笔交易完成，最大回撤卡片显示“报告未提供该指标”，权益曲线仍显示。证据 output/user-audit-20260907/evidence/fix-F11b-result.png/.txt；测试、类型检查、构建日志均为 output/user-audit-20260907/fix-F11b-*.log。

范围：关闭原审计 F11 的缺失原因说明问题；没有把旧版报告升级为新版统计，也未声称独立验证回测金额或曲线计算。
