# OKX 采样盘口回测

`BOOK_SAMPLED` 是独立的 CandleScope 宿主撮合模式。Pine/Pyne 负责策略逻辑，CandleScope 是成交和账户状态的唯一来源。原生回测和 `BOOK_DEPTH` 的输入要求不变。

## 已准备的数据与使用步骤

本机配套样本位于 `output/native-v9/okx-10m/`，覆盖 2026-06-01 00:01–00:11 UTC，10 根一分钟 K 线、3439 个盘口/成交事件。

1. 在本地资料库导入 `bars.csv`，品种 `BTCUSDT`、周期 `1m`、时间戳单位 `ms`。
2. 打开数据集，在“Pine / Pyne 完整策略”中选择“CandleScope 撮合反馈”。
3. 撮合精度选择“采样盘口（有限深度）”，上传配套 `execution.json`。
4. 选择语言并粘贴完整源码。可直接使用 `examples/strategies/okx_sampled.pine` 或 `examples/strategies/okx_sampled.py`：第一柱决策开仓，第六柱决策平仓，数量 0.001。
5. 运行后，报告必须标明 `BOOK_SAMPLED`、`SAMPLED_L2_VISIBLE_TAKER_ONLY_V1` 和 CandleScope 账户权威。完整导出包含数据来源、原始归档哈希和撮合假设。

两个示例用于验收执行链路，不是收益策略。普通执行和成交回调均已用已安装引擎通过 HTTP 运行/导出验收，四种组合账户成交一致，各组合重复运行完整报告一致。

## 准备其他窗口

在仓库根目录执行，Python 使用项目后端环境，下载需要 `curl`：

```powershell
python backend/scripts/prepare_okx_sampled_backtest.py --archive-dir output/okx-archives --output output/okx-window --start 2026-06-01T00:01:00Z --minutes 10 --download
```

已有本次下载的原件时可直接复用：

```powershell
python backend/scripts/prepare_okx_sampled_backtest.py --archive-dir output/native-v8 --output output/okx-window --start 2026-06-01T00:01:00Z --minutes 10
```

只使用公开现货 BTC-USDT 数据，不需要 API 密钥。一天的订单簿按 UTC 切分，逐笔成交归档按 UTC+8 切分；脚本自动选择两份成交文件，按原始毫秒时间和真实 trade ID 合并，不拼接当地时间字符串。默认窗口为 10 分钟，必须在同一个 UTC 订单簿日内。窗口之前需要一条不超过 2 秒的盘口记录，因此当天第一分钟可能无法使用；不会把后续快照提前到窗口开头。

输出为 `bars.csv`、`execution.json`、`manifest.json`。OHLCV 由同一批成交用十进制聚合，运行前再次校验与主图一致。成交 ID 缺口、重复和时间倒退会拒绝转换。初始盘口通过窗口前快照与增量重建，保留真实 `sample_time_ms`；同毫秒先成交、后更新盘口。`sample_index` 只表示导出记录顺序，不冒充交易所序列。

归档已存在时复用；HTTP 限流作有限重试；下载先写 `.part`，成功后更名。每个下载默认限 512 MiB。执行 JSON 限 48 MiB 和 500000 个事件，为宿主 64 MiB 总输入预算留余量，超限时需要缩短窗口。部分下载不会成为可用归档。

本机曾出现系统 DNS 失败；脚本支持追加 `--resolve 域名:443:IP` 使用经核实的 DNS 地址，HTTPS 证书校验仍然启用。不要把旧 IP 当作长期固定配置。

## 成交模型

- 只使用已到达的采样盘口；下一秒数据不会提前生效。新盘口与成交同毫秒时，成交使用上一条盘口。
- 主动单、可成交限价单逐档消耗剩余可见数量。超出深度部分保持未成交，到运行末尾按现有订单结束策略取消；不虚构额外深度。
- 相同快照不会补回已被本方假设成交消耗的流动性，只有观察到的数量变化可以改变剩余容量。
- 不推断被动挂单的排队成交。挂单只有在后续变为可主动成交时才可能执行，不产生“精确 FIFO”结果。
- 盘口超过 2000 毫秒不成交，报告记录过期成交事件数。止损和跟踪状态仍观察成交价格，恢复新鲜盘口后才允许成交。
- 继续使用 CandleScope 现有单向账户、费用和滑点设置，不宣称复刻 OKX 全套现货交易规则。5000 档约每秒采样的公开归档不能证明完整市场深度或秒内连续事件。

## 连续采集

已提供独立、有时间上限的采集命令，依赖后端已有 `websockets>=15.0.1`：

```powershell
python backend/scripts/collect_okx_l2.py --output output/okx-live-session --seconds 3600
```

订阅公开 `books`（400 档、100ms）及 `trades-all`（逐笔、带主动方向），保存原始消息、接收时间、交易所序列和文件 SHA256。输出目录必须是新的采集段，避免覆盖旧证据。可选 `--resolve-ip` 仅覆盖连接地址，TLS 主机名校验保持开启。

盘口必须从快照开始，后续 `prevSeqId` 必须连接上一条 `seqId`；成交 trade ID 也检查连续性。断流、序列重置或不完整输入将该段标记为 `INCOMPLETE`，不会跨断口拼出合格区间。命令结束自动断开；本轮只做短时实采，没有安装常驻服务。

OKX 从 2026-06-23 起将这些频道的 checksum 固定为 0，当前采集按官方要求使用 `seqId/prevSeqId`，不再把零校验和当作有效 CRC。[官方变更公告](https://www.okx.com/zh-hans/help/okx-order-book-channels-checksum-field-deprecation)

此采集仅证明已订阅消息流的连续性，仍是有限档位、100ms 更新；两条连接的接收顺序不等于交易所跨流顺序。因此 `book_depth_admissible` 仍为 false。它提供后续数据研究的原始归档，不会直接绕过 `BOOK_DEPTH` 的完整输入要求。

## 验收

```powershell
python backend/scripts/qualify_okx_sampled_backtest.py --directory output/native-v9/okx-10m --output output/okx-qualified.json
```

命令使用当前已安装的 Pine/Pyne 插件和独立临时数据库，覆盖两种语言、普通/成交回调模式、重复报告一致性、HTTP 导出和统一宿主账本。[本轮验收记录](evidence/native-strategy/2026-09-20-native-v9-qualification.json)
