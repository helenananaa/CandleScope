# F22b Mac 快捷键提示写死 Ctrl

修复：新增共用平台修饰键函数，Mac/iOS 键盘环境显示 ⌘，Windows/Linux 显示 Ctrl。搜索按钮键帽、悬浮提示、搜索框占位提示、工作区撤销/重做以及关于页共用此规则。九种语言的搜索提示改用 modifier 插值，不改变实际按键处理逻辑。

验证：4 项快捷键测试通过，覆盖平台映射、Mac/Windows 历史键位、输入/不可用状态、搜索 Escape 隔离。TypeScript、ESLint、生产构建、git diff --check 通过。电脑操控生产版 Mac 检查搜索按钮 ⌘K；使用 ⌘K 打开搜索，搜索框也显示 ⌘K；工作区面板显示撤销 ⌘Z、重做 ⌘ShiftZ。证据 `output/user-audit-20260907/evidence/fix-F22b-search-ready`、`fix-F22b-workspace`；日志 `F22b-*.log`。

边界：Windows/Linux 显示通过函数测试验证，未使用对应系统 GUI。工作区当时无可撤销历史，按钮禁用；本轮验证提示，没有为此制造新布局历史。关于页复用函数通过类型检查，未重复 GUI 操作。
