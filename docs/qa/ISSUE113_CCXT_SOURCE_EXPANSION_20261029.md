# Issue #113：Binance / OKX 源数据扩展、补证与多语言验证

本轮继续在 `codex/issue-113-ccxt-fork` 实施。范围按用户确认限定为 Binance 现货、USD-M，以及 OKX 现货、线性永续；未进行桌面应用验收。

## 固定版本与交付

- 上游版本仍为 **4.5.60**，上游提交 `72fd71026c8cfc0d9a470a834fcc7ad611be5765`。
- 自维护 fork 新提交 `43f7d748b22757873e1b81776e150ca67b67da07`，已推送到 [维护分支](https://github.com/helenananaa/ccxt/tree/codex/candlescope-4.5.60)。两个提交分别扩展 Binance 现货和 OKX。
- Python wheel 两次从同一提交独立构建，SHA-256 均为 `8520ad4b0f9004f6340da3da49ec7f455fc7579d85cb375d145741f3806f625c`。锁文件、安装脚本、当前工作树虚拟环境已同步。
- 源码只维护 TypeScript；生成的 JS/Python/PHP/C#/Go/Java 没有作为手工补丁提交。没有向 npm、PyPI、NuGet、Maven Central 发布包。

## 实现

1. 四条市场的 K 线都保留完整原始行/WS 帧、原始小数字符串、市场身份、闭合依据和源版本。Binance 现货保留交易笔数、报价量、主动买量等完整字段；OKX 保留原始合约张数、基础币量、计价币量和 `confirm`。OKX 不提供的交易笔数/主动买量保持缺失，不制造零值。
2. OKX 没有 K 线事件时间戳；不同的已闭合 WS 值会触发 REST 校验，不伪造时间戳推断先后。沿用数据库读取水位、版本围栏、持久交付和重放链路。
3. 公共 REST 在 CCXT 标准化前截获完整解码响应，使用请求级 ContextVar 隔离并发请求。WS 原生帧通过既有有界队列落库；统一接口的计算结果继续用于消费者。新增公共源日志保存完整 JSON、时间、通道、SHA-256 和实际 fork 构建来源。HTTP 头、认证信息和签名查询串不进入日志。这里的“完整”指解码后的交易所 JSON，不是 TLS/压缩线上的字节流。
4. 历史补证服务及 `backend/scripts/enrich_ccxt_sources.py`：先持久保存旧行，再按连续时间段批量补抓，每请求最多 300 行；时间缺口不冒充连续数据。记录 `historical_refetch`、抓取时间、差异和源 observation ID。修订经过交付层、聚合器和持久存储确认；离线 CLI 不启动实时补洞，历史时间缺口不会阻塞后续选中行。失败可重试，已证实的行不会重复覆盖。补抓证据不声称是当年的原始报文。
5. 自动源日志维护接入 DataManager 的 30 分钟维护循环。默认将 30 天前的非当前源版本/公共报文压缩归档；在同一 SQLite 事务中写入 gzip、校验哈希和往返内容后清掉热 JSON。当前 K 线 head（包括待交付版本）保持热存储；历史 ID、去重哈希和修订链保留。查询自动恢复归档，损坏校验失败会明确报错。**这是可恢复的热日志清理，不是永久销毁原始证据；冷归档仍占空间，SQLite 空闲页可复用，不承诺立即缩小文件。**
6. 真实网络发现并修复了共享客户端退出时 REST 会话未关闭、迟到目录任务重新打开已关闭客户端的问题。市场目录按实际产品加载；OKX 合约的指数通道保留必需的现货目录，避免加载无关交割/期权目录。
7. 固定 CCXT 版本原来连接 OKX 8443，会收到 `64010` 退役通知并重连。CandleScope 的 OKX 连接配置已改用 443。交易所公告规定公网 8443 于 **2026-10-31** 退役，主机和路径不变。[OKX 官方公告](https://www.okx.com/en-eu/help/okx-websocket-port-8443-discontinuation-announcement)

字段依据：[Binance 现货行情文档](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market)、[OKX API 文档](https://www.okx.com/docs-v5/)。

## 验收结果

[综合机器可读结果](ccxt-source-matrix-20261029/summary.json) 汇总各修复后案例；失败尝试保留，不能把整个目录中的早期失败当成最终通过。

- **四条 K 线链路全部通过**：REST → 实时形成/闭合 → REST 对账 → SQLite → WS 重连，最终待交付源版本为 0。Binance 见 run-06；OKX 现货见 run-05，合约见 run-07。
- **28 个非 K 线通道案例、51 个 REST/WS 路径通过**。包括成交、ticker、深度、Binance 聚合成交/全深度/mini ticker，以及合约标记价、指数、资金费率、持仓量等公共数据。全深度案例检查原生报文保存，完整订单簿重建仍由现有订单簿链路负责。
- 4 个接口组合不受支持：Binance 强平 REST、Binance 持仓量 WS、Binance premium-index WS、OKX 持仓量 WS。使用各自支持的传输方式；不把不支持项计为通过。
- Binance 强平 WS 在 20 秒观察窗口内没有新事件，保留 `no_event_in_window`，不声称已经验证真实强平数据。
- OKX 标记价/指数最终验证见 run-08；[源帧证明](ccxt-source-matrix-20261029/run-08/summary-source-proof.json) 单独核对实际 `mark-price` / `index-tickers` 帧及构建来源。
- **旧库抽样 9 行**：以只读方式读取本机旧库并复制到隔离库；7 行匹配，2 行差异已保留并修订。原库没有写入；本轮没有全量改写生产历史。[旧值及补证审计](ccxt-source-matrix-20261029/legacy-source-audit.json)
- 离线补证 CLI 另用真实 REST 处理两根跨时间缺口的 OKX 旧行，两根均匹配；第二次独立运行跳过已补证行，待交付为 0。[CLI 结果](ccxt-source-matrix-20261029/offline-cli-sparse.json)
- **压缩归档与重启恢复通过**：例如 run-06 将 126 条热日志的 63,499,917 字节 JSON 转成 1,009,963 字节压缩证据；新 Python 进程恢复校验 137 条记录，待交付为 0。通过注入未来维护时钟验证 30 天策略，并没有等待真实 30 天。
- 后端相关集成回归 **485 passed**；末轮市场目录修复后的相关回归另有 **52 passed**，最终离线补证及源修订回归 **32 passed**。包含事务回滚、损坏归档拒绝、补证失败重试、精度/单位、源版本修订和原有存储/回放等检查。日志见 qualification 目录。

网络边界：最初直连 OKX DNS 失败；后续使用本机已有 HTTP 代理，TLS 校验保持启用。代理出口一度被 Binance 返回 418，期间保留失败记录并停止该次验收，冷却时间结束后才重跑。最终不是靠跳过校验或替换为模拟数据通过。

## 多语言与发布包验证

| 运行时 | 新增源字段契约 | Binance / OKX 静态请求响应 | 包/构建 |
|---|---|---|---|
| JS/TS | 通过 | 578 项 | tsc、CJS、浏览器两种 bundle、npm tarball 安装后调用通过 |
| Python 同步/异步 | 两种均通过 | 各 578 项 | 锁定 wheel 安装与两次独立构建哈希相同 |
| PHP 同步/异步 | 两种均通过 | 各 578 项 | Composer 安装、清单验证通过（有上游版本约束提示） |
| C# | 通过 | 578 项 | netstandard2.0 / 2.1 均编译，NuGet 包内 DLL 与编译物一致 |
| Go | 通过 | 578 项 | 全模块生成/编译、模块校验、测试可执行程序通过 |
| Java | 通过 | 578 项 | JDK 21 编译、JAR/源码 JAR、从实际 JAR 调用契约通过 |

共 8 种运行方式的 4,624 项静态请求响应检查，另有各运行方式的 broker ID 检查。契约检查实际比较小数字符串、单位、缺失字段和完整原始 JSON；不只检查构建退出码。范围是上述受维护语言及 Binance/OKX 扩展，不宣称覆盖其他交易所的 live 行为、私有交易接口或实验性 Rust。

[包哈希](ccxt-source-matrix-20261029/qualification/artifact-hashes.json)、[构建来源](ccxt-source-matrix-20261029/qualification/build.json) 和各语言输出保留在 qualification。Go 有新方法参数类型，必须生成完整 REST 包（`npm run transpileGORest -- --noTests`）后编译；只生成两个交易所会覆盖共享参数类型或缺失新方法 Options，因此不能当发布验证。

## 使用

仍为显式启用：`INGESTION_CCXT_FORK_KLINE_ENABLED=1`。`INGESTION_SOURCE_LOG_RETENTION_DAYS=30` 控制自动归档年龄；设 0 停止自动归档。

安装锁定 fork：

```sh
.venv/bin/python backend/scripts/install_ccxt_fork.py
```

补证使用已完成当前数据库模式升级的离线 profile，先停用该 profile 的后端。默认只列出候选范围，加 `--apply` 才执行；返回 `next_start_ms` 可分批继续。不会自动扫描或批改所有用户 profile。

```sh
.venv/bin/python backend/scripts/enrich_ccxt_sources.py \
  --data-dir /absolute/offline-profile --exchange okx --market futures \
  --symbol BTC-USDT-SWAP --interval 1m --start START_MS --end END_MS --limit 300
# 确认范围后用相同参数加 --apply 执行。
```

真实验收工具 `validate_ccxt_source_matrix.py` 要求全新 `CANDLE_DATA_DIR`，支持按交易所/市场/通道筛选；`--legacy-db` 始终只读原库。`--http-proxy` 只对验收进程生效。
