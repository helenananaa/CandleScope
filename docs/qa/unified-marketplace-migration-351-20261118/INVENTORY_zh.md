# 旧市场包重发清单

随桌面构建分发的[官方信任根](../../../backend/app/official-marketplace-roots.json)目前为空。本清单从仓库的市场签名用例和可构建插件清单提取，覆盖可识别的参考包和自有包。实际部署的市场还需核对其配置的信任根、签名索引及已安装版本。

| 插件 | 仓库内的依据 | 旧入口、权限及数据 | 重发所需工作 |
| --- | --- | --- | --- |
| `candlescope.aho-corasick` | Phase 10 签名参考包，参考发布者 `candlescope-contributors`。[清单](../../../examples/plugins/aho-corasick-adapter/manifest.json) | Windows x86_64 原生 sidecar，按命令启动。权限集合为空，清单未声明 Host 私有存储。保留已存在的沙箱数据。 | 先移植 adapter 的握手和调用协议，复用同一搜索算法和 UTF-8 字节偏移回执。需要统一命令入口支持，随后重建并由实际发布者重新签名。 |
| `candlescope.ta4j-elliott` | Phase 10 签名参考包，参考发布者 `candlescope`。[清单](../../../examples/plugins/ta4j-elliott-adapter/manifest.json) | Java sidecar，按命令启动。需要有界的 Binance Spot BTCUSDT 1h 历史读取，要求 point-in-time，最多 5,000 根。清单未声明 Host 私有存储。 | 补受管 Java 绑定和命令入口；按同一行情输入复核形态和输出。现有 `chart.compute/1` 仍只接收当前图中已揭示的数据。 |
| `candlescope.market-scanner` | 仓库自有 Python 包。[清单](../../../packages/candlescope-plugin-market-scanner/src/candlescope_plugin_market_scanner/manifest.json) | 命令、设置、结果视图、摘要和图层。读取插件设置、限定市场目录与行情，声明 1 MiB Host 私有存储及受限图层发布。 | 先明确新版如何读取旧设置和存储导出，再接齐新权限和视图、图层调用。验证同一市场及扫描样本的输出一致。 |
| `candlescope.node-hello`、`candlescope.wasm-reference` | 仓库运行时参考包。[Node 清单](../../../examples/plugin-platform-node-typescript/manifest.json) [WASM 清单](../../../examples/plugin-platform-wasm-rust/manifest.json) | 受管 Node 或 Wasmtime，按命令启动，无声明权限或 Host 私有存储。 | 需要在统一 v2 签名制品中支持相应的受管运行时和命令入口，再重跑参考协议及 Windows 隔离验收。 |

Phase 10 [参考签名脚本](../../../backend/scripts/plugin_platform_multi_runtime_phase10.py)生成的是本地核对用索引。实际重发需要在部署索引上确认现有 ID、签名发布者、当前激活及授权记录。第三方包的清单、签名和数据读取合同由对应发布者提供，原包及私有数据应保留至回滚验收结束。

本目录的生成器提供可重复构建的受限纯数据主题候选，覆盖首次安装、健康升级、坏升级和旧安装接管。它用于桌面验收。上表的命令、行情权限和运行时仍各有自己的重发条件。
