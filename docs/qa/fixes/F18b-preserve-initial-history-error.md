# F18b 初始加载吞掉具体历史请求异常

原因：初次历史请求与重试的异常仅触发重试或 console.warn；安全超时最终总是生成通用 history unavailable，导致服务端说明无法传到 F18a 的诊断详情。

修复：每次初始加载保存最近一次历史请求异常，超时优先交给现有错误状态。后续有效历史响应会清除过期异常，没有请求异常时继续使用通用空历史提示。取消或停止重试后不再写入该异常或超时错误，状态仅属于当前加载闭包。

验证：22 项现有初始加载/修复重试策略测试通过，TypeScript、ESLint、生产构建、git diff --check 通过。独立生产预览 127.0.0.1:15175 对 K 线接口注入 503，诊断详情实际显示 `QA simulated failure: DataManager not initialized`；同样场景 F18a 时仅显示通用 history unavailable。解除注入后图表恢复，先恢复 500 根、随后 1500 根 K 线可见，原诊断错误消失。原后端未停止；测试标签页完成后关闭。

证据：`output/user-audit-20260907/evidence/fix-F18b-details`、`fix-F18b-recovered`；日志 `output/user-audit-20260907/F18b-*.log`，模拟脚本 `F18b-fault-preview.py`。

边界：22 项策略测试不直接模拟本次异常变量，具体异常保留和恢复依赖上述生产 GUI 故障注入验证。“有效空响应清除先前异常”已做代码检查，本轮未另造 GUI 空历史数据集；不声称空历史所有情况已通过。健康检查分项与复制诊断摘要仍待处理。
