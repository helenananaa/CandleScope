# Pine 0.3.1 宿主升级（2026-10-07）

Pine 适配器和引擎均更新为 `0.3.1`，SDK 保持 `0.2.0`。上游官方
`v0.3.1`（`14a2ab89c08a85a76d769e9fbe2f13f9c958342d`）补齐了
`Program.run_external` 和 `Program.historical_session`，解决上一轮官方
稳定包无法替换原生回测扩展构建的问题。分析/输出/增量 schema 仍为 6/9/4。
渐变填充仍明确拒绝，资源预算诊断仍保留。

当前锁包含三个 wheel 的精确版本、大小、来源和 SHA-256；上游 manifest
及 SHA256SUMS 均已验证。上一轮发布锁原样归档为 `release-lock.0.3.0.json`。
新 CSPKG 为 `candlescope-pine-compat-0.3.1-cp312-win_amd64.cspkg`，
目标环境是 Windows AMD64 / CPython 3.12。

指标与原生回测分开注册。指标 CSPKG 经 `PluginInstaller` 安装；原生回测使用：

```powershell
python backend/scripts/install_native_strategy_plugins.py `
  --wheelhouse <本轮三个已核验wheel所在目录> --runtime pine --activate
```

`--runtime pine` 只替换 Pine 原生注册项，保留 Pyne 注册项。宿主撮合模式仍由
CandleScope 提供权威账户反馈，Pine 仅产生订单意图；原生 broker 模式的成交
及账本仍归 Pine 引擎负责。历史结果和状态身份不改写，新会话重新计算。

回滚通过指标安装器 activation history 和原生安装目录内的
`previous-native-registry.json` 进行；不要复用不兼容的旧会话状态。
原始产物、安装收据和 JUnit 位于 `output/pine-upgrade-031-20261007/`。
没有新增完整浏览器 UI、长时资源或其他 OS/Python 的宿主验收。

## 验收

- Pine 适配器源码 21 项、禁用源码 pythonpath 的已安装 wheel 12 项通过。
- 正式下载目录和 bootstrap 12 项通过。
- 未修改、未跳过的完整 native/external/replay 套件 107 项通过，使用干净安装的
  官方 Pine 0.3.1 wheel 和原 Pyne 0.4.1 安装。上一轮的 40 项 Pine 接口失败已消除。
- 三 wheel 的 CSPKG 经干净 managed venv 离线安装，check、pip check、导入来源、
  真实指标计算、forming 替换和确认、订阅隔离与进程重启重建均通过。

可移植收据见 [验收摘要](evidence/pine-upgrade-0.3.1-20261007.json)。
