# Issue #113：源快照持久化、闭合修订与真实 REST/WS 验收

## 结果

在 `codex/issue-113-ccxt-fork` 原有独立 worktree 上完成后端实现。
Binance USD-M 原生 K 线完整源记录现在先写入 SQLite，再进入规范化、连续性、恢复、聚合、
持久交付、缓存和事件总线。已收盘 K 线可按源修订更新，写入失败可重试，启动可回放未交付源记录。
最终真实验收包含公共 REST、实际 CCXT Pro WS、形成中到收盘、收盘后对账修订、WS 停止重连、
数据库与缓存一致性、新 Python 进程回读。按本次要求未做桌面应用验收。

CCXT 仍固定在上游 `v4.5.60`，fork 提交仍为
`cc319944cdbab79070965f361bb8a69015c25263`；本次无需修改 fork 源码或重新发布 wheel。
依赖锁、默认关闭的功能开关和原工作区保持原状。

## 持久化与修订规则

- `kline_source_observations` 保存完整 envelope、解码源对象的 JSON、原始十进制字符串、
  单位、WS event time、接收时间、收盘证据、fork 来源提交、REST 请求前数据库水位和交易所时间。
  同一个源观察去重；语义相同但元数据不同的观察仍保留。`raw` 不代表原始网络字节。
- `kline_source_heads` 为每个交易所/市场/标的/周期/open_time 记录选定观察、单调修订号和已交付修订号。
  语义哈希不受 Decimal 默认 28 位精度舍入影响；浮点投影相同的更细小源变化也会产生新修订。
- 形成中快照不能覆盖已收盘记录。过旧 WS event time 被拒绝；同时间戳但内容冲突，以及 REST
  选定后出现内容不同的旧闭合 WS，触发 REST 对账。拒绝和冲突观察仍可审计。
- REST 在物理请求前获取数据库水位和 Binance USD-M 服务器时间。请求期间同一 K 线被推进时，
  旧响应不能覆盖新版本；整页最多重试 3 次，持续冲突显式报错，不通过缩短页面伪装完整返回。
  收盘时间判断使用服务器时间，避免本机时钟偏差。
- 新的有效闭合修订通过 Continuity、Recovery、Router 和 BarState。原生快照完整替换 OHLCV、
  成交额、笔数、主动买入量/额；可修正向下的极值/数量，不再额外舍入到 8 位小数。
  数值投影仍是现有浮点列，精确证据由源日志保存。
- 聚合产物携带组件源修订。SQLite 在写入事务内验证引用和原生数值，拒绝旧任务覆盖新 head。
  实测覆盖原生 1m、派生 2m 的修订传播；聚合器重建后会从源日志恢复同桶的其他闭合组件。
- 下游回调/持久收据写入失败会传播到源交付层；Publisher 保留待重试事件，CCXT delivery loop
  重试当前消息并报告 unhealthy。源交付成功后才确认修订，旧确认不能确认新修订。
  最终投影沿用持久 bar delivery outbox；源确认表示已交给下游持久交付链，可能仍有 outbox 待处理。
- 工厂先注册消费者，再回放未确认源记录，然后启动 WS，避免恢复事件在消费者就绪前被确认。

源日志的观察顺序与交易所数据的最终一致性是两件事。REST 请求后取得的快照按该请求选为当前版本，
仍可能在交易所收盘后的短时间内落后于 WS。日志保留这些版本及其证据，后续对账继续修订；
没有把“收盘”解释为“以后永远不变”。

## 真实交易所验收

最终机器可读记录：[run-05/result.json](ccxt-source-live-20261029/run-05/result.json)。
验收运行约 50.3 秒，使用单独的 `/tmp/candlescope-fork-live-acceptance-05`，无账户密钥。

| 检查 | 实测结果 |
| --- | --- |
| 首次 REST 与启动回放 | 3 条源快照先落库，消费者注册后回放 |
| 真实 WS | 54 条被接纳的更新，观察到同一根 K 线从 `x=false` 到 `x=true` |
| 收盘 K 线 open_time | `1793240460000`（毫秒） |
| REST 收盘后复查 | 6 次，最后两次相同；请求前服务器时间至少晚于 closeTime 15 秒；全部对账字段与 WS 收盘一致 |
| 闭合后的源修订 | revision `53 → 55`；中间不同快照经真实管道写库并发布修订 |
| SQL / BarCache | OHLCV、成交额、笔数、主动买入量/额逐字段与选定 REST 快照一致 |
| WS 停止重连 | 重新建立流后又接到 2 条更新 |
| 新进程回读 | 完整源 head、原始 JSON、最终数值行均一致 |
| 收尾 | source pending = 0；bar delivery pending = 0；degraded = false |

观察明细见 [source-observations.json](ccxt-source-live-20261029/run-05/source-observations.json)、
[rest-samples.json](ccxt-source-live-20261029/run-05/rest-samples.json)、
[events.json](ccxt-source-live-20261029/run-05/events.json) 和
[restart-readback.json](ccxt-source-live-20261029/run-05/restart-readback.json)。
最后源 JSON 的 SHA-256 为 `22f3d30a56a3fd9a3a1d34680447c8348cbbda484839273014c4e9d14e3b4e0b`。

### 验收中发现并保留的差异

1. run-01 收到 WS 收盘后，本机接收时间仍略早于该 K 线 closeTime，REST 判为未收盘并被防回退逻辑拒绝。
   后端已改为在请求前获取交易所时间。
2. run-02 验收脚本误用了事件枚举的字符串拼写，断言失败；后端数据已写入。脚本已修正。
3. run-03 完成一轮收敛验收。run-04 补测了真实重连，但当时“两次 REST 相同”的判据过弱：
   REST 成交额 `10958833.30900` 仍少于 WS 的 `10988643.55760`，其原结果明确记录
   `ws_rest_values_equal=false`，不能算作 REST/WS 对账通过。
   [延后 REST 观察](ccxt-source-live-20261029/run-04/delayed-rest-followup.json) 返回
   `10988643.55760`，通过新建后端管道回放后更新到 revision 102，
   [投影读回](ccxt-source-live-20261029/run-04/delayed-rest-projection.json) 确认无待交付源。
4. 最终 run-05 使用更严格判据：最多 15 次复查、连续相同、交易所时间越过上述边界、且与 WS
   显式收盘数据一致；持续不一致会使验收失败。15 秒是本次验收的观察下限，不是交易所最终一致性的保证。

这里观测到的是收盘边界上不同传输快照的差异和收敛，不等同于证明交易所一定会推送任意久远历史的修订。

## 回归与复现

[相关后端回归日志](ccxt-source-live-20261029/regression.log)：**469 passed**，14 条依赖弃用警告。
覆盖 CCXT 运行时/恢复/取消/关闭、Ingestion、BarAggregator、DataManager、SQLite、bar delivery。
新增用例包含源精度、批量事务回滚、旧 REST/WS 拒绝、同时间戳对账、闭合修订、冷启动派生重建、
回调失败、持久收据失败、消费者注册顺序，以及 WS delivery 重试。
首次从仓库根目录运行时有两个既有 subprocess 用例找不到 `app`；从项目标准 `backend` 目录运行全部通过。

新增模块/脚本通过 Ruff，compileall 与 `git diff --check` 通过。
全改动文件 Ruff 扫描仍有 4 个基线已有的未使用导入提示，已用 `git show HEAD:<path>` 复核，
详见 [existing-lint-findings.log](ccxt-source-live-20261029/existing-lint-findings.log)。

从 worktree 的 `backend` 目录执行；需先按原型文档安装锁定 fork wheel：

```bash
CANDLE_DATA_DIR=/tmp/candlescope-source-regression CANDLESCOPE_REQUIRE_CCXT_FORK=1 \
  ../.venv/bin/python -m pytest tests/test_bar_aggregator*.py tests/test_ingestion*.py \
  tests/test_ccxt*.py tests/test_data_manager*.py tests/test_storage*.py \
  tests/test_bar_delivery*.py tests/test_kline*.py tests/test_source_revision*.py -q

CANDLE_DATA_DIR=/tmp/candlescope-source-live-new \
  ../.venv/bin/python scripts/validate_ccxt_source_live.py --output /tmp/candlescope-source-evidence
```

live 脚本拒绝复用已存在的数据库，调用真实生产工厂和公共 API，输出完整 JSON 证据。
生产入口的试验开关仍为 `INGESTION_CCXT_FORK_KLINE_ENABLED=1`。

## 范围

当前覆盖 Binance USD-M linear swap 原生 K 线，真实验收标的是 BTCUSDT 1m。
派生 2m 与失败/崩溃边界使用受控回归验证；没有把它们写成真实交易所故障演练。
源快照日志从启用后开始积累，现有老数据不会凭空得到原始证据；暂未添加源日志保留期或自动清理。
对于没有完整源组件的既有派生历史、其他交易所/数据通道和全部多语言发布，仍需各自专项覆盖。
本次没有进行桌面应用验收、生产环境切换、PR 创建或合并。
