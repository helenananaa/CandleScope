# F32：均线第一组完整窗口的实时值缺失

日期：2026-09-08。

MA 已有 period-1 根确认 K 线时，实时路径仍要求确认窗口长度达到 period，导致首个完整窗口无法预览。修复允许当前 K 线补足窗口；仅原窗口已满时移除最旧值，避免提前丢掉第一根。

独立手算等差价格均值，覆盖周期 1/2/20/500，重复预览不提交、首根确认及下一组滚动均值。修复前 4 组失败；修复后相关回归共 110 项通过，Mac arm64 原生重新打包成功，production 前端未变。

证据：output/user-audit-20260908/ma-preview-before.log、ma-preview-tests.log、ma-preview-package.log。数值验证使用确定性生命周期测试。
