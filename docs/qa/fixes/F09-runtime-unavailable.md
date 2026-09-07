# F09 不可用运行时被误判非法目录

证据：当前接口返回 pyne/pine 的 available=false，runtimeId 指向尚未安装的第一方插件，runtimes 为空。前端把这类明确不可用路由当成 unknown runtime id，整份目录失败。

修复：缺失运行时描述符仅在语言明确 unavailable 时允许；声明 available 却缺失运行时仍拒绝。编辑器显示插件管理检查路径，要求已安装、启用且平台兼容，说明内置指标仍可使用。不可用语言不能运行或保存。

验证：7 项运行时目录测试、TypeScript、相关 ESLint、九语言检查、Production build、git diff --check 通过。真实 Mac 发行版打开自定义指标，原协议异常消失，提示正确，AX 确认运行和保存按钮 disabled。证据 output/user-audit-20260907/evidence/fix-F09-editor.png/.txt；同级上层 fix-F09-*.log。

未尝试让 Windows 插件在 Mac 运行，也不声称自定义脚本执行可用。报告 F09 提到的顶部按钮逐字换行仍存在，须作为独立布局问题继续处理。
