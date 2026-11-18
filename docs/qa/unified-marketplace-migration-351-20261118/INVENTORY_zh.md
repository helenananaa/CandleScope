# 旧市场包重发清单

随桌面构建分发的[官方信任根](../../../backend/app/official-marketplace-roots.json)目前为空。本清单从仓库的市场签名用例和可构建插件清单提取，覆盖可识别的参考包和自有包。实际部署的市场还需核对其配置的信任根、签名索引及已安装版本。

| 插件 | 仓库内的依据 | 旧入口、权限及数据 | 重发所需工作 |
| --- | --- | --- | --- |
| `candlescope.aho-corasick` | Phase 10 签名参考包，参考发布者 `candlescope-contributors`。[清单](../../../examples/plugins/aho-corasick-adapter/manifest.json) | Windows x86_64 原生 sidecar，按命令启动。权限集合为空，清单未声明 Host 私有存储。保留已存在的沙箱数据。 | [0.2.1 统一格式候选](../../../examples/unified-plugins/aho-corasick/README_zh.md)已接入统一命令面板，并通过 macOS 本地包校验、Host 调用和旧搜索回执对照。市场重发还需 Windows 原生隔离和旧安装回滚验收，再由实际发布者签名。 |
| `candlescope.hello-command` | SDK 的 [Platform v2 命令示例](../../../packages/candlescope-plugin-sdk/examples/platform-v2/hello-command.manifest.json) | 本地信任的 Python sidecar，权限集合为空。 | [0.2.0 统一格式候选](../../../examples/unified-plugins/hello-command/README_zh.md)保留 `hello` 命令。旧安装停用后明确批准新包，旧命名空间仍可用于迁移期回滚。 |
| `candlescope.ta4j-elliott` | Phase 10 签名参考包，参考发布者 `candlescope`。[清单](../../../examples/plugins/ta4j-elliott-adapter/manifest.json) | Java sidecar，按命令启动。需要有界的 Binance Spot BTCUSDT 1h 历史读取，要求 point-in-time，最多 5,000 根。清单未声明 Host 私有存储。 | 补受管 Java 绑定和命令入口；按同一行情输入复核形态和输出。现有 `chart.compute/1` 仍只接收当前图中已揭示的数据。 |
| `candlescope.market-scanner` | 仓库自有 Python 包。[清单](../../../packages/candlescope-plugin-market-scanner/src/candlescope_plugin_market_scanner/manifest.json) | 命令、设置、结果视图、摘要和图层。读取插件设置、限定市场目录与行情，声明 1 MiB Host 私有存储及受限图层发布。 | 先明确新版如何读取旧设置和存储导出，再接齐新权限和视图、图层调用。验证同一市场及扫描样本的输出一致。 |
| `candlescope.node-hello`、`candlescope.wasm-reference` | 仓库运行时参考包。[Node 清单](../../../examples/plugin-platform-node-typescript/manifest.json) [WASM 清单](../../../examples/plugin-platform-wasm-rust/manifest.json) | 受管 Node 或 Wasmtime，按命令启动，无声明权限或 Host 私有存储。 | 需要在统一 v2 签名制品中支持相应的受管运行时和命令入口，再重跑参考协议及 Windows 隔离验收。 |

Phase 10 [参考签名脚本](../../../backend/scripts/plugin_platform_multi_runtime_phase10.py)生成的是本地核对用索引。实际重发需要在部署索引上确认现有 ID、签名发布者、当前激活及授权记录。第三方包的清单、签名和数据读取合同由对应发布者提供，原包及私有数据应保留至回滚验收结束。

本目录的生成器提供可重复构建的受限纯数据主题候选，覆盖首次安装、健康升级、坏升级和旧安装接管。它用于桌面验收。上表的命令、行情权限和运行时仍各有自己的重发条件。

## 安装收口

插件中心工具栏和本地导入使用同一份统一包审批。旧本地安装接口和市场旧格式候选返回更新提示，旧缓存和记录保留。市场同一发布者重发仍按签名、审批和健康检查接管。

本地同 ID 切换需先停用旧安装，再明确批准新摘要。统一插件启用或正在清理时，旧实例无法重新启用。迁移期回滚可先停用统一插件，再从保留的旧安装恢复。旧设置、私有存储与批准保留在原命名空间，新包按自身权限开始运行。
