# 周期切换后 K 线永久加载：已退役批量连接回调

2026-09-29。生产现场：Windows 包 `production-20260929-e6e0170c-fixed`，BTCUSDT spot 的 30m/4h 已有 1501 根数据仍显示加载遮罩；切走再切回可恢复。

## 根因与修复

最后一个逻辑订阅退出后，BatchKlineStreamCoordinator 将物理 socket 置空并关闭。新订阅可立即创建替代 socket，但旧 socket 的异步 onclose 仍遍历当前 subscriptions，将新订阅标记断线。KlineConsumerRecovery.capture 随后递增新周期 epoch，使正在运行的 initial-history HTTP 结果失效。初始加载交出所有权后没有新加载接管，后台轮询虽补齐数据，遮罩仍在。

诊断构建在 futures 也复现：30m 初始请求 expected epoch=1，旧 socket 的 onClose 经 capture 将 epoch 改为 2；500 根响应被判 stale=true。跟踪保存于 output/interval-loading-debug/trace.jsonl。临时埋点已全部移除。

修复只允许当前物理 socket 的 open/message/error/close 回调生效，隔离退役连接的所有延迟事件，保留当前连接真实断开的恢复行为。

## 验证与边界

- 两个新增回归覆盖最后订阅关闭、closeAll 后重建，使用真实 SeriesDataFeed + KlineConsumerRecovery 和延迟 HTTP 响应。修复前 2 失败，修复后通过。
- 相关 115 项测试通过；两个 TypeScript 项目、定向 ESLint、架构检查、生产构建通过。
- 本地生产构建连接正在运行的后端，实际切换 30m → 4h → 1d → 30m → 1h → 30m 均完成加载；4h/1d 各显示 1501 根。图像：output/interval-loading-debug/fixed-30m.png。
- 当前原生旧窗口保留，并恢复到 30m。桌面诊断程序启动命令被执行策略拒绝，没有通过其他启动方式绕过。新原生包仍需用户启动复测；浏览器生产构建验证不等同于原生新包启动通过。
- 新包路径：frontend/desktop-dist/production-20260929-interval-fix/win-unpacked/CandleScope.exe。
- 保留已有未提交发布修复；未提交、未推送。
