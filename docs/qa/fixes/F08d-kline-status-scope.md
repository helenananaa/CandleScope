# F08d 底部连接状态范围不明

核对：StatusBarModel 的 wsStatus 来自 marketView；市场数据运行时使用 KlineWebSocketStatus。底部并未汇总独立盘口及成交流状态。

修复：连接提示和 WebSocket/回退提示均增加“K 线”标记，悬浮说明指出仅代表活动图表 K 线，盘口、成交看各自面板。覆盖九种语言。

验证：check:i18n、相关 ESLint、Production build、git diff --check 通过。电脑操控发行版中底部显示“K 线 已连接 OKX”“K 线 实时（WebSocket）”，同时盘口独立显示连接中、成交显示 60 秒无新成交；AX 包含完整范围说明，当前窄窗口无新增遮挡。证据 output/user-audit-20260907/evidence/fix-F08d-scope.png/.txt；日志 fix-F08d-i18n.log、fix-F08d-build.log 位于其上级目录。

F08 已确认的空快照误报、旧数据无提示、观测连续性措辞、底部状态范围分别由 F08a–d 处理。本轮修复没有证明交易所成交流本身的迟滞已被消除，仍需持续区分产品展示问题和数据链路故障。
