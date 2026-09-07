# F04 搜索 Esc 穿透背景布局

问题：搜索仅在弹窗内部处理 Esc，右键操作使焦点离开后无法关闭；最大化图表的全局监听还会响应同一按键。

修复：搜索打开期间在 document 捕获阶段处理 Esc，不依赖输入焦点；有右键菜单时先关闭菜单，否则关闭搜索，并阻止事件继续传播。关闭搜索时解除监听。背景最大化监听忽略已处理的事件。

验证：

- 搜索相关测试 7 项通过，包含 Esc 消费、其他键不拦截、已处理事件不重复关闭及监听清理；TypeScript、相关文件 ESLint、Production build、git diff --check 通过。
- 电脑操控生产预览：最大化图表，打开搜索并右键结果；第一次 Esc 仅关闭菜单，第二次关闭搜索，图表仍最大化。再次打开搜索，输入框内 Esc 正常关闭；之后在背景按 Esc 正常恢复双图。
- 截图及 AX 证据：output/user-audit-20260907/evidence/fix-F04-context、fix-F04-escape-menu、fix-F04-escape-search、fix-F04-input-escape、fix-F04-background-escape（.png/.txt）。构建/测试日志位于 output/user-audit-20260907/fix-F04-*.log。

本提交针对交易对搜索的焦点路径，未声称完成其他弹窗的统一键盘层级改造。
