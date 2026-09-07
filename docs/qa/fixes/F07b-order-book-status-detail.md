# F07b 盘口断流原因被通用提示遮蔽

原因：盘口 store 已保存 message/error，但视图只传递 supportMessage；状态文本函数对 stale/reconnecting/error 也忽略传入的具体原因。

修复：空状态正文和状态悬浮提示优先读取当前 message、error，再使用能力提示；有具体原因时显示该原因，否则保留通用文本。重试入口不变。

验证：

- 盘口与组件回归测试 11 项通过。新增测试从真实 store 渲染完整 OrderBookDock，验证 stale/reconnecting/error 的具体原因同时出现在正文及 title，保留重试按钮，并覆盖 error 字段回退。
- 相关 ESLint、Production build、git diff --check 通过。
- 电脑操控发行版刷新后正常从等待进入实时盘口。截图 output/user-audit-20260907/evidence/fix-F07b-reload.png、fix-F07b-status.png。本轮未现场触发序列缺口等特定故障，其展示通过上述组件测试验证。
- 日志：output/user-audit-20260907/fix-F07b-tests.log、fix-F07b-build.log。

本提交仅修复已存在原因的展示。最后有效时间及实际降级来源仍需后续处理，F07 尚未全部关闭。
