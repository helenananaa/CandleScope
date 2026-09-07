# F13a 合成图说明条与行情头重叠

原因：合成图说明绝对定位在图表顶部，固定 right:232px 和极窄最大宽度；双图中长说明被挤成纵列，覆盖行情头及副图。

修复：说明移到图表滚动视口内的独立文档流行，采用原生 details/summary，默认折叠，仅显示当前合成图标题；展开详情时占用自己的高度，不覆盖图形。图表类型切换重置折叠状态，保留原有合成数据及映射说明。说明支持键盘和辅助功能语义，不更改合成算法或默认时间范围。

验证：相关 ESLint、TypeScript、Production build、git diff --check 通过。电脑操控生产构建在双图中验证砖形图默认折叠、点击展开、切换点数图自动折叠；展开说明正常横向换行，行情头位于下方。证据 output/user-audit-20260907/evidence/fix-F13a-before.png、fix-F13a-collapsed.png、fix-F13a-expanded.png、fix-F13a-point-figure.png（同名辅助功能文本）；日志 output/user-audit-20260907/fix-F13a-build.log、fix-F13a-typecheck.log。

边界：F13 的默认视野空白观察仍需单独复核；本次不声称修复合成公式或视野算法。
