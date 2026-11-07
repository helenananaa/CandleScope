# #218 在 #223 合入后的验收

源码 `2bcd57c1985478b486ebf5e9ddcacd8647fdc83e`，main `5f6b4a3edb4198963c1e868bad299ca1c76ddfc2`。架构、TypeScript、后端组合 1,064 项和前端重点 87 项通过。一项 Windows 专属用例跳过。

实际 Binance BTCUSDT USD-M 5m OI。保存图表后两次正常完整退出，重启一次。独立冷态 SQLite 检查确认请求窗口内 48 条完整记录、覆盖回执和重启后绘制值逐点一致。实测源时间均对齐 5 分钟。

附带的 x64 JUnit 记录证明此前超时的跨进程账户恢复用例在 #223 的打包环境实际通过。本 PR 当前提交的打包 CI 独立记录。

原生证据来自本地签名 macOS arm64 候选。发布安装包 CI 和 Windows 桌面验证独立验收。

[精确命令与证据指纹](receipt.json)
