# F15 导出弹窗受图格裁切，保存和预览难以访问

原因：导出面板绝对定位于当前图格，用图格宽高限制自身；双图及底部策略面板使可用空间极小。保存按钮还在设置滚动区末端。

修复：通过 portal 挂载到 document.body，并用原生 dialog.showModal 进入浏览器顶层，按视口宽高布局。桌面窗口保留设置/预览双列，仅小于 700 CSS px 时改为单列。保存/关闭按钮移到对话框固定底栏。原生模态提供焦点约束和 Escape 关闭；键盘事件不传给背景图表。

验证：7 项导出服务及冻结页面测试通过；相关 ESLint、TypeScript、Production build、git diff --check 通过。电脑操控生产构建验证双图、双图加策略面板：设置、预览和保存按钮同屏可见；页面预览生成、实际保存、Escape 关闭均成功，关闭后双图布局未变化。

实物 output/user-audit-20260907/evidence/fix-F15-page.webp 已检查，2400×1616，包含页面图表与侧栏，无导出弹窗及模态遮罩。截图 fix-F15-open.png、fix-F15-page-ready.png、fix-F15-escape.png、fix-F15-short-cell-dialog.png；测试/构建/类型日志 output/user-audit-20260907/fix-F15-*.log。

边界：本轮验证桌面 994×768 截图窗口，未另测小于 700 CSS px 的窄屏单列模式。没有改变导出计算、格式或活动图表身份。
