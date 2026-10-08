# Pine / Pyne 稳定版宿主升级（2026-10-07）

此页保留 Pine 0.3.0 的历史交付证据。后续 Pine 0.3.1 已补齐两个回测接口，
当前升级与安装边界见 [Pine 0.3.1 升级记录](pine-upgrade-0.3.1-20261007.md)。

本轮将指标适配器升级到 `0.3.0`，使用官方 Pine `0.3.0` 和 Pyne `0.4.1`
wheel；Pyne Workbench 更新到 `0.1.2`。SDK 保持 `0.2.0`，宿主协议不变。
每个发布锁记录全部 wheel 的版本、来源、内容哈希和安装探针；旧 `0.2.0`
发布锁原样保存在两个适配包的 `release/release-lock.0.2.0.json`。

## 实际升级范围

| 路径 | 升级后的引擎 | 验证及边界 |
| --- | --- | --- |
| Pine 指标 sidecar | 官方 `0.3.0` | 分析/输出/增量 schema 为 6/9/4；形成、替换、确认、独立订阅和重启重建 |
| Pyne 指标及 V2 会话 | 官方 `0.4.1` | 宿主 safe/inline 与资源预算继续显式设置；会话、broker 和渲染测试 |
| Pyne 原生/宿主撮合回测 | 官方 `0.4.1` | 原始报告等价、净值观察、固定历史回放、跳转、订单与账户反馈 |
| Pine 原生/宿主撮合回测 | 保留此前安装的 `0.3.0rc1` 扩展构建 | 官方 `0.3.0` 的 Python `Program` 缺少 `run_external` 和 `historical_session`，不能直接替换 |

上述 Pine 回测构建是独立的已安装内容身份，不能描述成官方稳定 release。
尝试全部替换的原始结果保留在 `output/runtime-upgrade-20261007/native-external.xml`：
67 通过、40 失败，失败均来自 Pine 的两项缺失 API。保留原 Pine 回测环境并升级
Pyne 后，同一组 107 项 native/external/replay 测试全部通过，没有放宽断言或跳过失败项。

Pine 图表的渐变填充无法通过既有 Render IR v1 表达，本轮明确返回
`PINE_HOST_CAPABILITY_UNSUPPORTED`，不会静默丢失颜色信息。纯色填充继续支持。
`E_RESOURCE_BUDGET` 从引擎的 ValueError 转为明确运行时诊断；预算仍由官方 wheel
决定，不能把每柱逻辑分配额度当作整个进程的内存上限。

## 状态与结果身份

Pyne `0.4.0` 的计算语义为 5，新版为 42。已用实际安装的旧引擎生成 portable
snapshot，并确认新引擎拒绝恢复，错误为 `PYNE_SNAPSHOT_SEMANTICS_MISMATCH`。
升级须重启并从权威 OHLCV 重建会话，不能更改旧快照身份。盘中 varip 等状态仍
需要原始事件历史，OHLCV 不足以重建过去的 preview 访问。

历史回测记录继续保留其原引擎版本和 code hash；本轮不改写数据库或历史结果。

## 验证

本轮宿主验收环境为 Windows AMD64 / CPython 3.12：

- Pyne 适配包源码：41 项通过；Pine 适配包源码：21 项通过；Workbench：38 项通过。
- 禁用源码 pythonpath 注入后的已安装 Pyne/Workbench：67 项通过；Pine：12 项通过。
- 后端策略、订阅和运行时路由：42 项通过；正式下载目录/bootstrap：12 项通过。
- 新 Pyne 与保留 Pine 的真实回测、账户反馈、请求数据、回放：107 项通过。
- 两个 CSPKG 经干净 managed venv 离线安装和 `check()`，实际 sidecar 探针、重启、
  导入来源及 `pip check` 通过。源码测试环境可使用共享测试依赖，不将其 pip check
  当作干净安装凭证。
- 实际旧 Pyne 快照在新版下拒绝恢复。保留失败收据和成功收据。
- 改动无新增 Ruff 诊断；已有 native 观察代码保留 3 个历史诊断。

这些计数来自不同验证路径，包含重复执行，不是互不重叠的总用例数量。
没有进行浏览器完整 UI、长时资源或其他 OS/Python 矩阵验收。

## 构建、安装与回滚

Pyne 离线包由 bridge、SDK、官方引擎、NumPy `2.3.3` 和 tzdata `2026.2` 共五个
wheel 组成；Pine 指标包由 bridge、SDK 和官方引擎三个 wheel 组成。两个包的
`scripts/build_bundle.py` 默认使用当前 `release-lock.json`，每个 wheel 都有内容锁。
构建后必须核对发布的外层 CSPKG 摘要，不可覆盖同版本资产。

原生回测安装通过以下命令仅升级 Pyne，保留已有 Pine 注册项：

```powershell
python backend/scripts/install_native_strategy_plugins.py `
  --wheelhouse <本轮已核验wheel目录> --runtime pyne --activate
```

默认同时安装的路径会探测引擎能力，不能用缺少 API 的 Pine wheel 替换已有回测。
指标注册表 `runtime-registry.json` 与回测注册表 `native-strategy-registry.json` 独立。
Pyne 安装器保存 `previous-native-registry.json`；指标安装器保留每个插件的 activation
history，支持 `PluginInstaller.rollback(runtime_id)`。恢复注册表后重启相关 sidecar，
不要恢复不兼容的 Pyne 计算状态。

本轮原始产物、安装收据、日志和 JUnit 位于 `output/runtime-upgrade-20261007/`；
可移植摘要见 [验收记录](evidence/runtime-upgrade-20261007.json)。正式默认下载目录为
`backend/app/official-plugin-releases.json`，资产、URL、大小及外层摘要须作为同一交付更新。

## 本轮交付

两个适配器的 `0.3.0` release 已公开：
[Pyne](https://github.com/helenananaa/CandleScope/releases/tag/candlescope-plugin-pyne-v0.3.0)、
[Pine](https://github.com/helenananaa/CandleScope/releases/tag/candlescope-plugin-pine-compat-v0.3.0)。
发布前核验了全部远端资产的大小和摘要；发布后重新下载两个 CSPKG，与正式下载目录
匹配后安装到本机默认插件目录。两个指标 sidecar 的引擎版本和 SMA 实际计算通过，
默认 bootstrap 返回 `ready`。本机 Pyne 原生回测已升级到 `0.4.1`，原 Pine 回测
注册项逐字段保持一致。收据为 `output/runtime-upgrade-20261007/production-verification.json`。

发布源码身份为 `f7b0729cde68d3cdbfbc74ed79ddb6cb22bf1688`。独立 Git checkout 重建的
wheel 与交付 wheel 存在既有 CRLF/LF 差异；除自动生成的 RECORD 外，各成员在换行
归一化后相同。这是源码一致性核验，不是字节级可重复构建证明。

改动及交付记录在 [草稿 PR #7](https://github.com/helenananaa/CandleScope/pull/7)，尚未合并。
主工作区已有的无关本地提交没有推送到远端 main。上述激活验收使用实际插件进程，
仍不代表浏览器完整 UI 或长时运行验收。
