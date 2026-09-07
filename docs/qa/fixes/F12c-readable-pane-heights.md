# F12c 副图在小窗口中被压缩得不可读

原因：原有 80px 默认副图高度经 setStretchFactor 转成比例权重；父区域缩小后继续按比例压缩，实际可低至约 30px。只提高默认权重无法在空间不足时提供真实高度下限。

修复：图表外层增加纵向滚动视口，保持内层绘图坐标根。主图至少 180 CSS px，展开副图至少 80 CSS px，主动折叠仍保留 36px。内容高度不足时允许滚动；在实际像素预算内修正过小的保存比例，合理比例保持不变。滚动时更新窗格指针布局，清晰的 14px 滚动条避免误拖价格轴。

验证：17 项高度分配、窗格指针及绘图表面测试通过；TypeScript、相关 ESLint、Production build、git diff --check 通过。电脑操控生产构建验证双图、双图加策略面板、四图；下方 MACD/RSI 能经滚动到达并保持可读高度。滚动后十字光标读取对应时间的值；通过键盘聚焦并激活真实按钮验证 MACD 展开和退出全屏。关闭策略面板、恢复双图后所有副图可见。

导出实物已检查：整张图表 WebP 包含全部副图和既有矩形绘图，无滚动裁切遗漏。保存在 output/user-audit-20260907/evidence/fix-F12c-export.webp。

证据位于 output/user-audit-20260907/evidence：fix-F12c-bottom.png、fix-F12c-scrolled-crosshair.png、fix-F12c-exit-confirmed.png、fix-F12c-expand-confirmed.png、fix-F12c-four.png、fix-F12c-restored-two.png。测试、类型检查、构建日志为 output/user-audit-20260907/fix-F12c-*.log。

验证边界：未做滚动后新建/拖动绘图的专项手工测试；绘图覆盖依靠既有绘图表面测试及实际导出中的已有绘图。窄单元内导出弹窗裁切仍属于原审计 F15，此提交不处理。此前对隐藏悬停按钮的 AX 点击未触发，最终以键盘操作后的真实状态作为全屏/展开验证证据。
