# Binance Spot深度请求共享权重

main45022e4e实际原生诊断（PR200源码127ba4f4）记录/api/v3/depth落入binance_spot_legacy，cost1、独立legacy桶；因此没有与exchangeInfo/klines共同按IP权重预算及反馈。触发本轮418的是后台/fapi/v1/exchangeInfo，不能据此说Spot深度就是远端已有封禁原因。

为Spot /api/v3/depth添加header_weight规则，沿用现有spot IP桶、容量、安全系数、并发及退避。按Binance官方Spot REST文档（2026-11-04读取）限制1–100/101–500/501–1000/1001–5000分别消耗5/25/50/250；未给limit按100，超过5000的服务端截断仍取最高权重。来源：https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md#order-book 。Futures已有独立深度规则保持原状，未知端点fallback保留。

新增10个外部规则边界及真实本机HTTP→CCXT物理请求用例，修复前11项均复现cost1，修复后连同公共准入、回环传输、429/418/探测释放及共享market等96通过，7条既有提示。实际query limit1000只发出一次本机/depth，按50进入共享spot桶并接收同一权重反馈；未发送公网请求。新增回归加入macOS包内Python门禁。

本修复不清除或缩短共享IP circuit。当前LIVE验收继续受2026-11-04T15:42:40.340Z截止约束；实际网上重新资格留待冷却后，不用回环替代。完整失败和修复日志保留。

后端架构与main原有10条逐字节一致。
