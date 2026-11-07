# Pine 运行时尾段拒绝后的原点恢复

产品源 `e9af2a6b` 基于实际 main `b442555d`。Pine runtime 回报局部尾段发生重置时，owner 仍拒绝发布该尾段。HTTP 和 WebSocket 持有原图表身份，在同一命令内只尝试一次从 canonical 原点重新构建。真实历史修订继续使用其已有恢复路径。界面区分历史变化和运行时重建，两者都会明确提示盘中状态已清除。

受控反例使用实际 ASGI、真实事件总线、SQLite 和 Pine sidecar，释放 worker 的执行状态与输出，图表源、身份和订阅仍保留。旧实现返回 `INDICATOR_CALCULATION_ORIGIN_REQUIRED` 并终止 writer。修复后的 WebSocket 在保留的 writer 发布完整 501 结果，generation 和 sequence 各增加一次，下一观测推进至 502。HTTP 同样从原点发布完整 501。旧尾段无发布，缓存快照仍可读取重建提示。此反例独立于此前公开行情偶发的晚到错误。

架构检查通过。后端组合 1107 项通过、1 项 Windows CRT 专属跳过。完整前端常规 4908 项、性能 1 项、桌面 130 项通过，生产构建通过。以当前 backend、SDK、ASAR 及前端构建重新签名本地候选，复用已核对的 Pine 引擎和插件；1073 个源码/SDK 指纹、164 构建文件、9 插件资产和 76 插件源码一致。

## macOS 签名候选

独立 HOME 和资料库留存原生 Pine 日志。真实 Binance BTCUSDT spot 1m 使用单根受控来源修订验证新 generation 和界面提示，然后保存源码、完整退出并重启。重启观察到 74 个一致的盘中结果。三次提前到达的最终 BAR 在本机边界后 47、35、36 ms 收到指标回执，保持同一 generation，序列分别 16→17、44→45、71→72。两次正常完整退出 2365、2128 ms，sidecar 退出码 0，无信号或强制终止，独立确认应用拥有的进程已退出。

运行时状态丢失的故障注入证据来自受控真实 sidecar，公开行情原生轮验证保存、退出和收盘稳定性。原晚到错误本轮未复现。完整 #152 的故障矩阵和长历史性能、Windows 主机及独立发行安装包继续分别验证。PR 保留 Draft。

[命令与证据指纹](receipt.json) · [真实收盘对齐](evidence/native-boundaries.json.gz) · [重启界面](evidence/native-restored-pine-output-ranges.png)
