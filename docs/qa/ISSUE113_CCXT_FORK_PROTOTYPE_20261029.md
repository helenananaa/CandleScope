# Issue #113：固定版本 CCXT fork 原型

## 结论与固定基线

可以长期固定在一个上游版本上维护自己的补丁，不必跟随 latest。此次已建立
[helenananaa/ccxt](https://github.com/helenananaa/ccxt)，在独立 CandleScope worktree
实现了可选择开启的 Binance USD-M K 线接入原型。当前只完成离线原型验证，默认关闭。

| 项目 | 固定值 |
| --- | --- |
| CandleScope 起点 | `b84b5e3d514e43fca556613fe107e29d12f7a329` |
| CandleScope 分支 | `codex/issue-113-ccxt-fork` |
| CCXT 上游 | `v4.5.60` / `72fd71026c8cfc0d9a470a834fcc7ad611be5765` |
| fork 维护分支 | `codex/candlescope-4.5.60` |
| fork 固定提交 | `cc319944cdbab79070965f361bb8a69015c25263` |
| 扩展契约 | `candlescope.binance.usdm.kline.v1` |
| wheel SHA-256 | `d6bf360bfef5601b02cc13ed6709a1564b0a919137ee40cccdd94d133bf9d0d2` |

消费者锁定见 `backend/ccxt-fork.lock.json`，使用提交 SHA 和 wheel 内容哈希，不依赖
可移动的分支名。上游版本号保留 `4.5.60`，fork 的身份另由构建元数据与扩展契约校验。
没有配置自动同步上游；协议变化、安全修复或明确需要的新能力出现时，才升级基线并重新验证。

## 本次实现

- fork 修改 TypeScript 源码，新增 `fetchCandlescopeKlines`、REST/WS 完整 K 线解析器和契约标识。
  标准 `fetchOHLCV` 的六元素返回值保持原样。
- 首个适配范围为 Binance USD-M linear swap 的交易 K 线。REST 一页支持 1500 条，携带
  `since/until` 边界，不经过标准方法的 1000 条截断。分页仍由 CandleScope 负责。
- 新接口保留源 `closeTime`、成交额、成交笔数、主动买入量/额、单位，以及序列化的完整源响应。
  价格与数量先保留十进制字符串。`raw` 是已解码对象的 JSON 表示，不是原始网络字节。
- WS 使用现有 CCXT Pro 订阅和同步 raw hook，把 frame 交给 fork 解析器；没有第二路采集，
  没有新增 `watch` 缓存，也没有按六个 OHLCV 值过滤增强字段变化。
- CandleScope 验证标的、周期、单位、有限值、价格/成交量范围，并交叉检查命名字段与源响应。
  缺失增强字段不会被补成零。WS 收盘状态只接受 `k.x`；REST 使用源收盘时间与消息接收时间比较，
  同时标明这是时间推断。月线没有被换算成固定 30 天。
- 开启试验时校验安装包的来源提交和 schema。版本、方法或构建身份不符直接报错。
  开关不同的 WS runtime 分开复用，避免试验实例混入原有运行时。

## 构建和复现

CCXT 的 Python 实现由 TypeScript 生成。fork 提交只维护源码、测试和文档，生成文件不提交。
因此，直接 `pip install git+...#subdirectory=python` **不会得到本次扩展**。
安装脚本会从锁定提交新建临时 checkout，按 npm lock 安装依赖、编译、生成 Python、运行新增
JS 契约测试，再用固定 setuptools/wheel 构建 wheel。哈希不等于锁定值时拒绝安装。

在本 worktree 根目录、独立虚拟环境中执行：

```bash
uv venv .venv --python 3.12 --seed
cd backend
uv pip install --python ../.venv/bin/python -r requirements.txt -r requirements-test.txt
../.venv/bin/python scripts/install_ccxt_fork.py
CANDLE_DATA_DIR=/tmp/candlescope-fork-qualification CANDLESCOPE_REQUIRE_CCXT_FORK=1 \
  ../.venv/bin/python -m pytest tests/test_ccxt_fork_kline.py -q
```

该脚本要求 Git、Node/npm 和 Python；本机验证环境为 Node `24.22.1`、Python `3.12.15`、
macOS arm64。其他构建环境若得到不同哈希，应先检查差异并重新审核，不要直接更新锁值。
本 worktree 的 `.venv` 已安装生成的 fork wheel，wheel 和安装锁保存在
`backend/.cache/ccxt-fork/<source_commit>/`。

启用环境变量是 `INGESTION_CCXT_FORK_KLINE_ENABLED=1`，也可在隔离测试中显式设置
`IngestionConfig(ccxt_fork_kline_enabled=True)`。启动后端时应同时设置独立 `CANDLE_DATA_DIR`。
关闭开关即可恢复原有接入路径；若回到上游包，在该虚拟环境中执行
`python -m pip install --no-deps --force-reinstall ccxt==4.5.60`。之后再次开启试验会因缺少
fork 契约而被拒绝，必须重新运行安装脚本。默认依赖文件仍保留上游固定版本。

## 验证记录

详细日志和机器可读结论在 [ccxt-fork-20261029](ccxt-fork-20261029/qualification.json)。

- 两次独立 GitHub checkout 构建得到相同 wheel SHA-256；第二次构建启用了锁定哈希验证。
- 新增 JS 契约测试 3 项通过；TypeScript 编译和 Binance 文件 ESLint 通过。
- CandleScope 相关回归 136 项通过，其中新增 fork 契约测试 23 项。覆盖分页、并发响应关联、
  精度证据、月线边界、坏数据拒绝、元数据变化、收盘标记、来源校验、SQLite 数值字段回读；
  既有运行时回归包含取消、重连、溢出、共享连接、共享市场目录、关闭和恢复行为。
- CCXT 原有 Binance 静态测试在 JS、Python sync、Python async 下分别通过 336 请求测试和
  52 响应测试。Python 上游测试使用生成后的本地源码；CandleScope 测试使用安装的 wheel。
- Python、PHP、C#、Go、Java 的单交易所转译全部完成。PHP/C#/Go 本机没有执行工具链；
  Java 构建在当前 JDK `25.0.5` 与 Gradle `8.12` 环境下进入编译前失败，不能声明这些语言已通过。

## 尚未解决的边界

1. 完整 `source_candle` 和 `close_evidence` 目前附在 MarketEvent 上。现有数据库只持久化已有
   数值字段，仍按原有浮点类型保存；完整十进制字符串和原始证据没有持久化。
2. raw hook 和 normalizer 保留已收盘 K 线的新版本，但现有 `MarketEvent.dedup_key` 对闭合
   K 线按 open_time 去重，后续闭合修订仍可能在 ContinuityLayer 被丢弃；BarAggregator 也有
   自己的修订规则。本次没有把接入层保真描述成端到端历史修订完成。
3. 未做真实交易所 REST/WS 冒烟、原生应用体验、重启恢复或完整多语言发布验收。CCXT 仓库的
   验收顺序要求先通过多语言离线测试，再做 live smoke；本次环境尚未满足前置条件。
4. 尚未迁移其他交易所/行情通道，也未完成 Issue #113 的所有架构工作。该原型证明固定版本
   fork 的源码维护、构建锁定和严格数据接入路径可行；生产切换仍需上述边界的专项验证。

原工作区的修改和本机正在使用的数据未参与这次实施。未创建 PR、合并或修改 Issue。
