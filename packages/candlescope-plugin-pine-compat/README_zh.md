# CandleScope Pine Compatibility 插件

本包把独立发布的
[`pine-compat-runtime`](https://github.com/helenananaa/pine-compat-runtime) wheel
桥接到公开的 `candlescope.script-runtime/1` SDK。包内只有适配代码，不包含 Pine
引擎源码快照，也不导入 CandleScope 后端私有模块。

当前开发版 `0.3.0.dev1` 适配 `pine-compat-runtime==0.3.0rc1`，候选引擎来自
提交 `a481b4644c142badcf9e1bc5430bc3a5f7f2a733`。请使用
`release/release-lock.candidate.json` 中 SHA-256 锁定的 Windows wheel；相同版本号
不能区分不同候选构建。旧 `release-lock.json` 保留为公开 v0.2.0 的历史锁。

支持历史批计算，以及已确认历史末尾的一根 forming bar。WebSocket 订阅通过
`options.pineSessionId` 保留原生会话，支持替换、收盘确认和追加；传输仍返回完整
Render IR 快照。HTTP 计算保持独立。分析结果的 `meta.hostRequirements` 暴露
引擎的宿主需求清单，不代表这些外部能力已经接入。

每个 sidecar 最多保留 8 个最近使用的会话。历史窗口变化、源码或参数变化、
会话淘汰、进程重启会重新播算，并返回 `meta.sessionReset=true`。冷启动按盘中
接入处理，无法恢复此前的 tick/varip 状态。尚未提供跨进程会话恢复或无限历史保留。

`request.*` 数据供应、imports、策略以及未映射的原生绘图对象仍明确拒绝。
CandleScope 回测的 Pine 入口仅接受原样的 Long Flat 示例，任意 Pine 策略尚未接入；
修改示例不会再误执行固定阈值逻辑。

本地运行：

```powershell
python -m pip install --no-index --find-links <候选wheel目录> candlescope-plugin-pine-compat==0.3.0.dev1
python -m candlescope_plugin_pine_compat
```

构建器接受三个 wheel：本 bridge、SDK `0.2.0` 和锁定的 Pine 引擎 wheel。
构建候选包时传入 `--lock release/release-lock.candidate.json`，以及三次 `--wheel`
和一个 `--output`。候选包须通过安装器和真实 sidecar 验证后再启用。
