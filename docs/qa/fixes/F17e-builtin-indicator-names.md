# F17e 指标库和已添加列表主要显示英文指标全名

修复：七种内置指标 MA/SMA、EMA、BOLL、RSI、MACD、ATR、VOL 在指标库和已添加列表使用本地化名称，保留金融缩写。显示映射依据 engineName，未知引擎及自定义指标保留原名称，不修改持久化名称、引擎身份或计算配置。搜索同时匹配本地化名称和原名称。九种语言补齐文案。

验证：单元测试覆盖引擎身份映射、自定义同名指标不被改名、未知引擎回退及语言切换；TypeScript、ESLint、生产构建、git diff --check 通过。电脑操控生产版检查 MA、MACD、RSI 已添加列表，中文长名称换行且操作按钮可见；使用“相对强弱”和“Relative Strength”均找到 RSI，随后清空筛选。证据 `output/user-audit-20260907/evidence/fix-F17e-active`、`fix-F17e-search-zh`、`fix-F17e-search-en`，日志 `output/user-audit-20260907/F17e-*.log`。

边界：GUI 本轮验证中文和上述三个已添加指标；其他语言及映射通过静态/单元检查。图表曲线简称、代码编辑器、导出及其他页面的指标名称未纳入本次面板修复；F17 的其他术语与图标风格仍待处理。
