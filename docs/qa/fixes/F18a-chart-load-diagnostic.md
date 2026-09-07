# F18a 加载失败隐藏错误且建议开发热重载

问题：主图获得 error 字符串后只显示通用加载失败，并提示运行 uvicorn --reload。用户无法查看当前图表记录的错误，发行版排障还被引导到开发模式。

修复：提取 ChartLoadError，保留重试入口；增加默认折叠的“诊断详情”，以可选择、可换行的纯文本展示 chart.error。使用 React 文本转义，避免把错误内容当 HTML。九种语言将热重载命令改为重试、本地服务状态与启动日志的排查提示，明确网络连通不代表数据引擎就绪。

验证：

- 单元测试验证诊断文本可见于详情、HTML 转义、移除 --reload、保留重试按钮。TypeScript、ESLint、生产构建、git diff --check 通过。
- 用同一份 dist 在独立地址 127.0.0.1:15174 提供测试预览，仅对 K 线接口模拟 HTTP 503，其余 HTTP 请求转到既有 18080 后端；没有停止或修改原后端。
- 实际错误页显示新排查提示，展开详情显示 `K-line history unavailable for BTCUSDT@1h`。点击重试进入“正在加载 BTCUSDT 1h K 线…”并发起新的请求。
- 解除模拟失败后，原有自动恢复机制恢复到 1500 根 K 线。恢复发生在点击前，因此不将其宣称为“点击后恢复成功”。另一次模拟失败专门验证了重试按钮。

证据：`output/user-audit-20260907/evidence/fix-F18a-fault`、`fix-F18a-details`、`fix-F18a-retry`、`fix-F18a-recovery`；日志 `output/user-audit-20260907/F18a-*.log`，模拟代理脚本 `F18a-fault-preview.py`。测试标签页完成后关闭。

边界：代理未实现 WebSocket，旁侧盘口重连不计产品故障。GUI 仅验证模拟的历史数据失败及中文界面。上游 useChartInitialLoad 当前将接口失败归为通用 history unavailable，未将服务端 DataManager 细节传到 chart.error；此处仅展示已有图表错误，不声称已完成真实根因诊断。F18 的健康检查分项、错误原因保留与复制诊断摘要仍待后续处理。
