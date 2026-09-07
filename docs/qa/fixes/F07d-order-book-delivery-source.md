# F07d 实际盘口来源与标签不符

原因：后端盘口记录保留 source（http/websocket），但界面只按交易所的静态 snapshot_mode 展示投递标签。HTTP 数据可能被标为实时快照。

修复：已有快照的实际 source 优先决定“轮询快照”或“实时快照”；首包未到或未知来源时沿用能力信息。连续深度仍保留其严格连续语义，不按快照规则改名。

验证：

- 盘口/展示测试 12 项通过，覆盖实际 HTTP/WebSocket 覆盖相反能力配置、无数据回退及连续模式；相关 ESLint、Production build、git diff --check 通过。
- 电脑操控发行版真实 OKX 盘口显示“轮询快照”，盘口及最后有效接收时间正常更新。证据 output/user-audit-20260907/evidence/fix-F07d-live.png/.txt。
- 日志 output/user-audit-20260907/fix-F07d-tests.log、fix-F07d-build.log。

F07 已确认的首包无限等待、具体原因未展示、最后有效时间缺失、实际来源标签不符分别由 F07a–d 处理。交易所间歇性断流本身未被证明由客户端引起，不能声称已消除；后续继续观察。全局连接标签及成交健康状态属于 F08。
