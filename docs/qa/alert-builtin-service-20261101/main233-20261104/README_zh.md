# 最新主线组合资格（2026-11-04）

接入 main 395007ac（#233）及秒线 #200 的 2cefc201。关停顺序保留独立交易/回放 facade 清理与数值指标服务关闭，不以容错 getattr 跳过正式生命周期。旧失败测试使用缺少 replay 方法的 SimpleNamespace，现改用真实 DataManagerCore；原失败日志保留。

最终 140 项后端测试通过，覆盖警报、canonical 数值查询、关停失败恢复、周期准入、calendar basis 与 replay manager。前端架构检查通过。后端架构仍有 10 项 history_worker 对 HTTP 依赖违规，与当前 main 去除行号偏移后完全相同；不声称整体架构通过。

旧原生 24503897 验收不升级为当前组合资格。当前头 CI、#200 依赖验收以及组合原生复验尚待完成，保持 Draft。共享 IP418 退避期间未运行 LIVE 候选。
