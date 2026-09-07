# F07c 最后有效盘口接收时间

问题：盘口失效会清空 book，界面无法告知最后一次有效数据何时到达。

修复：store 独立保存最后一次已展示有效盘口的 receivedAtMs，失效/重连保留，订阅身份或模式改变时清除；盘口头部下方显示本地日期和时分秒，使用语义 time 元素并保留 ISO 时间。未收到有效数据时不显示虚构时间。新增标签覆盖现有九种语言。

验证：

- 盘口/组件测试 11 项、TypeScript、相关 ESLint、Production build、git diff --check 通过。
- store 回归覆盖已展示的最后时间、被取消的待显示帧不覆盖时间、stale/reconnecting 保留时间及 reset 清空。
- 电脑操控发行版真实 OKX 盘口：从首次等待到有效数据，显示“最后有效接收 2026/9/7 19:53:37”；窄侧栏内日期时间可读。证据 output/user-audit-20260907/evidence/fix-F07c-timestamp.png/.txt。
- 日志：output/user-audit-20260907/fix-F07c-tests.log、fix-F07c-typecheck.log、fix-F07c-build.log。

这是数据接收时间，不等于交易所事件时间或精确端到端延迟。F07 的实际降级来源展示仍需后续检查。
