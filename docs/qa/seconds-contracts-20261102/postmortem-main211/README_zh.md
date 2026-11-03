# 原生 main211 失败后时间线复核

只读打开已退出候选 native-after-main211/profile/data/candlescope.db（mode=ro&immutable=1），结合原始 pending-debug.json 和 indicator-diagnostics.json。没有启动旧应用、改动原数据库或请求公开端点。

原始诊断保留20个pending缺口，Gate19个、Binance7s 1个。最终数据库对应21根实际bar中，仅1根的created_at不晚于诊断时间；大多是在后续后台修补时才写入。最终ledger的filled是退出后的状态，不能倒推原生失败当时已补齐。gap-timeline.json保留每项范围、原诊断时间、最终row时间及重叠ledger回执。当前源码的共享指标bridge使用严格wildcard订阅，恢复时会暂时暂停所有新指标准入；其全局恢复等待不是某个市场已经恢复的证明。

形成中范围等待修复的本地测试已通过，但本次静态/只读时间线仍不证明它已解决原先四图共享owner恢复和Upbit MA0的问题。继续要求原生四图各自MA数值、自然收线、保存/完全退出/重启，不取消该断言、不将严格订阅放宽为gap-aware来通过。
