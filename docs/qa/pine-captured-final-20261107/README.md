# Pine 盘中观测与同根最终 BAR 并发

产品源 `723e905e`。有序 writer 消费已捕获的 forming 观测时，SQLite 证明覆盖其历史前缀至该根开盘前。当前盘中值由事件自身提供，当前根的最终数据落盘可以和这次执行并发。真实历史修订、最终 BAR 的 canonical 匹配、已有本机关闭边界和修复后的 generation 规则继续生效。

诊断签名候选在公开 BTCUSDT spot 1m 中捕获两次 `PrefixAcquisitionChanged`，一次发生在查询证明，另一次发生在提交证明。两次待处理输入均为 forming。受控 ASGI、总线、SQLite 和 Pine worker 反例在旧实现返回来源变化。修复后，已捕获的盘中价格 103 和最终价格 102 按序发布，计数从 500 推到 501、502，generation 一致。46 项专项通过。最终 84 套件组合通过 1104 项，1 项 Windows CRT 专属跳过，5 项警告。

## macOS 签名候选

从已核对的本机边界候选物理复制，仅覆盖和编译两份后端生产模块。1072 个源码/SDK 指纹、164 个构建文件、9 个插件资产和 76 个插件源码一致，严格签名通过。实际应用使用公开 Binance 行情。单根受控修订仍发布新一代结果并显示状态重置提示。保存 Pine 源码、正常退出和同资料库重启后，观察到 71 个一致的盘中结果。

| 重启后的收盘 | Binance 最终 BAR 到达相对本机边界 | 指标回执相对本机边界 | generation | 序列 |
| --- | ---: | ---: | --- | --- |
| 第一根 | -219 ms | +30 ms | 1 | 13→14 |
| 第二根 | -204 ms | +34 ms | 1 | 41→42 |
| 第三根 | -194 ms | +37 ms | 1 | 68→69 |

三个收盘均保留 generation，边界附近无来源屏障。两次完整退出分别耗时 2514、2278 ms，sidecar 退出码 0，无信号或强制终止，核对 20 条应用拥有的进程记录均已退出。诊断轮结束时 checkout 已切至产品修复，原验证器报告三处源比对差异，另以诊断提交的 Git 内容与包内文件逐一核对通过。正式候选的前后核验均直接通过。

先前晚到的 `INDICATOR_CALCULATION_ORIGIN_REQUIRED` 未复现，其原始证据保留。PR 仍为 Draft。Windows 主机、发布安装包及当前提交的 CI 分开核对。

[证据索引](receipt.json) · [真实收盘对齐](evidence/fixed-boundaries.json.gz) · [重启界面](evidence/fixed-restored-pine-output-ranges.png)
