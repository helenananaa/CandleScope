# F05 SMA 无效周期进入计算层

原因：内置指标添加流程丢弃 paramSchema，已有指标进入没有范围约束的编辑分支；有 schema 的原输入控件也会直接提交不符合 HTML min/max 的值。

修复：添加内置指标时保留 schema；已有内置指标缺少 schema 时从已加载目录补取。数值输入保留编辑草稿，仅在失焦或 Enter 且通过浏览器 required/min/max/step 校验时提交。无效输入提供关联的错误提示，不更新有效参数和计算结果。

验证：

- 发行版电脑操控：SMA 周期 0、空值、1.5、501 分别显示最小值、必填、整数步长、最大值提示，均保留 MA(20)，无 deque 异常。有效值 21 正常得到 MA(21)，Enter 提交 20 正常恢复。
- TypeScript、相关文件 ESLint、Production build、git diff --check 通过；指标目录现有回归测试 6 项通过。输入约束和结果保留由上述真实浏览器交互验证。
- 证据位于 output/user-audit-20260907/evidence/fix-F05-zero-rejected、fix-F05-empty、fix-F05-fraction、fix-F05-upper、fix-F05-valid、fix-F05-final-20（.png/.txt）；同级上层 fix-F05-*.log 保存检查日志。早期 fix-F05-zero 为发现 schema 丢失时的失败证据，不作为通过证明。

范围：本次保护指标面板提交路径，没有改造后端 API 的参数校验。错误文案使用浏览器 validationMessage，语言由浏览器决定（本次 Chrome 为英文）。
