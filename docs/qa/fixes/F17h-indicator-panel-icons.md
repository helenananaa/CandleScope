# F17h：指标面板标题和分类图标混用 Emoji

原 F17 图标一致性问题的另一处可复现场景：实时/回放共享指标面板中，标题及趋势、震荡、波动率、成交量等分类使用彩色 Emoji，与顶部及侧栏线条图标混用。

标题复用共享 ProfileRailIcon；新增 IndicatorCategoryIcon，为归一化后的 trend、momentum、oscillator、volatility、volume、contract-data、custom 提供 18px、1.8 线宽的 SVG，未知分类使用同规格通用图标。颜色继承 currentColor，图形 aria-hidden，继续由原有翻译文字描述分类。分组键、列表顺序、指标添加和能力判断不变。

验证：指标目录与回放工作区现有测试共 36 项通过；TypeScript、针对性 ESLint、production build、diff check 通过。电脑操控 production 预览分别打开回放与实时指标面板，确认标题及趋势/震荡/波动率/成交量图标可见且一致，实时已有指标标记、回放不可用指标状态保留。面板关闭后恢复工作区。

证据：`output/user-audit-20260907/evidence/F17h-{before,replay-after,live-after}.{png,txt}` 及 `F17h-{tests,typecheck,eslint,build}.log`。

本次不宣称全产品图标或所有分类均已 GUI 验收；contract-data/custom/未知分类通过相同组件路径提供图形，本轮截图只覆盖上述四个常见分类。未改主题配色、参数及计算实现，也未进行 Windows 原生包验证。
