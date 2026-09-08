# F30：EMA 首次有效实时值缺失

日期：2026-09-08。

已有 period-1 根确认数据，下一根形成时已足够计算初始简单平均，但实时路径因 _ema 尚未创建而返回空值；period=1 的首根也受影响。

修复实时预览的初始平均边界，不修改确认状态，未到边界仍为空，随后指数递推保持不变。

测试周期 1/2/20/500，修复前 4 组全部失败；独立初始平均与下一根加权值对照、重复预览不污染状态、收盘及全量计算一致，连同相关指标/API 回归共 102 项通过。production dist 未变，后端修复重新打包 Mac arm64 成功。

证据：output/user-audit-20260908/ema-preview-before.log、ema-preview-tests.log、ema-preview-package.log。计算生命周期验证未依赖 GUI 等待市场自然满足预热边界。
