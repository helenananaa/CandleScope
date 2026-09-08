# F03 布局撤销快捷键作用范围

问题：全局 Cmd/Ctrl+Z 会撤销工作区布局。用户在图表中选中绘图后按撤销，会意外改变布局。

修复：移除窗口级布局撤销监听，将布局撤销/重做限定为工作区面板内的键盘事件。输入框、可编辑内容、已处理的事件、锁定布局和没有可用历史的情况不拦截。保留面板按钮及 Mac/Windows 快捷键。本次不新增绘图历史，图表内撤销不会删除绘图。

验证：

- 快捷键回归与工作区面板测试共 4 项通过；TypeScript 检查、相关文件 ESLint、Production build 和 git diff --check 通过。
- 使用电脑操控在生产预览中切换双图/四图，在工作区面板内按 Cmd+Z 恢复双图，Cmd+Shift+Z 恢复四图。
- 关闭面板、最大化主图，绘制并选中矩形（八个控制点可见）后按 Cmd+Z，矩形与布局保持不变；面板外重做也不再改变布局。
- 证据：output/user-audit-20260907/evidence/fix-F03-panel-undo.txt、fix-F03-panel-redo.txt、fix-F03-drawing-focused.png、fix-F03-drawing-undo.png，以及同目录其他 fix-F03 截图。测试与构建日志位于 output/user-audit-20260907/fix-F03-*.log。
