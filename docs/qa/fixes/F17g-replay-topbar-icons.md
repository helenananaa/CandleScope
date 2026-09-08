# F17g：回放顶部图标与实时页不一致

原 F17 审计记录彩色 Emoji 与线条图标混用。实时顶部 F17f 已统一，但本次回放页面基线仍显示 📊 和 🔔，与左侧工具栏、右侧功能栏不一致。

此次仅将 ReplayTrainingPageShell 的指标与警报按钮改为共享 ProfileRailIcon / AlertRailIcon，与实时页同样使用 18px、1.8 线宽和 currentColor；图形 aria-hidden，按钮有指标数量与警报名。指标开关、计数、active、复盘禁用条件、警报禁用和现有能力原因保留。

验证：30 项现有 replayTrainingWorkspace 测试、TypeScript、针对性 ESLint、production build、diff check 通过。生产构建电脑操控打开 QA-F20c 存档，确认两个图标为一致线条样式；AX 显示“指标 0”及禁用“警报”，原 UNSUPPORTED_NO_PROVIDER 原因保留。指标面板点击打开、再次点击关闭通过，回放仍暂停。

证据：`output/user-audit-20260907/evidence/F17g-{before,after,panel-open}.{png,txt}`，测试和构建日志为 `F17g-*.log`。

边界：本次没有统一指标面板内分类装饰和其他页面图标，也未扩展不支持的回放警报。复盘状态未单独进入做 GUI 验证，其原禁用条件没有变化；不能据此宣称全部回放功能验收完成。浏览器 production 预览不等同于 Windows 原生包测试。
