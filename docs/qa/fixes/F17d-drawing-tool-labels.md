# F17d 绘图工具栏混用英文提示

复现：中文生产界面的橡皮擦、文字注释、斐波那契回撤按钮仍显示 Eraser、Text note、Fibonacci retracement；截图与 AX 为 `output/user-audit-20260907/evidence/fix-F17d-before`。

修复：三个硬编码工具提示接入现有语言系统，九种语言补齐文案。斐波那契提示保留右键/双击打开设置的说明；禁用时仍显示原来的不可用原因。不修改绘图行为。

验证：TypeScript、ESLint、生产构建、git diff --check 通过。电脑操控生产版验证三个按钮的中文可访问名称，右键斐波那契按钮能打开级别设置，随后使用面板关闭按钮关闭。证据 `fix-F17d-labels`、`fix-F17d-fibonacci-settings`，日志 `output/user-audit-20260907/F17d-*.log`。纯文案替换未新增镜像单元测试。

边界：未实际擦除或新增绘图，也未复测双击动作与其他语言界面；不据此宣称绘图引擎完整通过。F17 其他术语、指标名称和图标风格仍待处理。
