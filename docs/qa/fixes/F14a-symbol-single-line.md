# F14a 长合约代码撑高顶栏

问题：BTC-USDT-SWAP 在顶栏横向收缩时按连字符换行，代码分成三行，打乱工具栏高度。

修复：交易对名称强制单行并以省略号处理不足空间，完整代码保留原生 title 和按钮辅助功能名称；合约、交易所及快捷键标签不换行、不被压缩。选择器设置尺寸边界，代码承担弹性收缩。

验证：相关 ESLint、Production build、git diff --check 通过。电脑操控生产构建，在 994×768 截图窗口选择 OKX BTC-USDT-SWAP；加载标记/指数/基差后代码仍保持单行省略，标签与其他工具入口同一高度；辅助功能按钮名称仍为完整 BTC-USDT-SWAP。证据 output/user-audit-20260907/evidence/fix-F14-result.png、fix-F14-loaded.png/.txt；构建日志 output/user-audit-20260907/fix-F14-build.log。

边界：此项关闭长代码换行；原审计对整体顶栏信息密度及次要行情按空间折叠的建议未在本提交实施。F13 的历史加载后往返视野偏移仍待基线复核；已检查 axisTime.ts 使用源时间和 sourceOrdinal，并非直接依赖可变全局序号，尚无证据支持改写此处映射。
