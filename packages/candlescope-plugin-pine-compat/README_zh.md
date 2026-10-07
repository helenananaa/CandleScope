# CandleScope Pine Compatibility 插件

本包把独立发布的
[`pine-compat-runtime`](https://github.com/helenananaa/pine-compat-runtime) wheel
桥接到公开的 `candlescope.script-runtime/1` SDK。包内只有适配代码，不包含 Pine
引擎源码快照，也不导入 CandleScope 后端私有模块。

适配器 `0.3.1` 使用官方 `pine-compat-runtime==0.3.1` Windows wheel；
`release/release-lock.json` 锁定引擎、SDK 和 bridge 的内容哈希，旧发布锁
保存在 `release-lock.0.2.0.json` 和 `release-lock.0.3.0.json`。分析/输出/增量协议为 6/9/4。
渐变填充因 Render IR v1 无法表达而明确拒绝；纯色填充继续支持。资源超限
以 `E_RESOURCE_BUDGET` 诊断返回。

支持历史批计算，以及已确认历史末尾的一根 forming bar。WebSocket 订阅通过
`options.pineSessionId` 保留原生会话，支持替换、收盘确认和追加；传输仍返回完整
Render IR 快照。HTTP 计算保持独立。分析结果的 `meta.hostRequirements` 暴露
引擎的宿主需求清单，不代表这些外部能力已经接入。

每个 sidecar 最多保留 8 个最近使用的会话。历史窗口变化、源码或参数变化、
会话淘汰、进程重启会重新播算，并返回 `meta.sessionReset=true`。冷启动按盘中
接入处理，无法恢复此前的 tick/varip 状态。尚未提供跨进程会话恢复或无限历史保留。

`request.*` 数据供应、imports、策略以及未映射的原生绘图对象仍明确拒绝。
策略通过独立原生或宿主撮合入口执行，使用单独的注册表。

本地运行：

```powershell
python -m pip install --no-index --find-links <候选wheel目录> candlescope-plugin-pine-compat==0.3.1
python -m candlescope_plugin_pine_compat
```

构建器接受三个 wheel：本 bridge、SDK `0.2.0` 和锁定的 Pine 引擎 wheel。
构建候选包时传入 `--lock release/release-lock.candidate.json`，以及三次 `--wheel`
和一个 `--output`。候选包须通过安装器和真实 sidecar 验证后再启用。

## 回测安装边界

官方 0.3.1 wheel 已补齐 `Program.run_external` 和 `Program.historical_session`，
解决 0.3.0 的回测升级阻塞。冻结 bridge、SDK 和引擎 wheel 并验收后，通过
`install_native_strategy_plugins.py --runtime pine --activate` 仅升级 Pine 回测，
保留 Pyne 注册项。安装指标 CSPKG 不会自动注册原生策略回测。
