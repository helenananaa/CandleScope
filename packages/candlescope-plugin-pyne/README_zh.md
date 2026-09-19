# CandleScope Pyne Runtime 插件

`candlescope-plugin-pyne` 是 CandleScope 与独立发布的 `pyne-runtime` 引擎之间的
公开协议桥。它不导入 CandleScope backend 私有包，也不复制 Pyne 源码；CandleScope
通过 `candlescope.script-runtime/1` 在独立 managed venv 中启动它。

## 源码候选兼容性锁

- 插件：`candlescope-plugin-pyne==0.3.0.dev1`
- SDK：`candlescope-plugin-sdk==0.2.0`
- 引擎：`pyne-runtime==0.4.0`
- Python：`>=3.11,<3.14`
- Runtime ID：`candlescope.pyne`

未发布的适配器候选由 `release/release-lock.candidate.json` 固定到官方 Pyne 0.4.0
wheel 和已验证 SHA-256。`release/release-lock.json` 保留已发布 0.2.0 桥与 0.2.0rc1
引擎的历史记录；版本或内容不匹配会拒绝安装。

## 宿主策略与升级

适配器默认使用 safe 导入策略、插件进程内 inline 执行、5 秒协作式期限、50,000 根
输入、20 条输出序列、1,000,000 个输出点、10,000 根保留历史及 50,000 根回放记录。
集合、绘图和状态预算在 `host_policy.py` 中明确指定。`PYNE_*` 环境配置可显式覆盖
默认值，包括 none/unlimited；请求 securityMode 只覆盖导入模式。直接策略执行固定
使用 safe。独立 Pyne 的默认值不变。safe 不是操作系统沙箱，硬终止仍由外围宿主负责。

0.4.0 的计算语义版本为 5。升级时重启插件，从权威 OHLCV 重新 seed；不能修改旧快照
版本冒充兼容。适配器重连快照是进程内结果视图，不是可移植计算状态。策略 provider
恢复时重放保存的 bars。依赖盘中 preview 的状态需要原始事件历史，只有 OHLCV 无法
还原其访问顺序。

## 已发布开发包

第一份公开开发 bundle 为
[`candlescope-plugin-pyne-v0.2.0-dev.1`](https://github.com/helenananaa/CandleScope/releases/tag/candlescope-plugin-pyne-v0.2.0-dev.1)：

- asset：`candlescope-pyne-0.2.0-cp312-win_amd64.cspkg`；
- target：Windows AMD64、CPython 3.12；
- 大小：`13,006,218` bytes；
- SHA-256：`a1812e0e2b43670e75858b5f57d59f71a403350360ea58bf2822efba7d34a216`。

Python package 本身支持更宽的解释器范围，但这一个 bundle 内含 CPython 3.12 的
NumPy wheel，禁止安装到其他 ABI。CandleScope 官方 bootstrap 会同时固定上述四项；
社区安装仍可使用同一公共 `.cspkg` 安装器与自己可信的 Release artifact，通用安装器
不执行任何网络访问。

插件 sidecar 本身已经是 CandleScope 管理的进程边界，因此桥内固定使用 Pyne
`executor_mode="inline"`。宿主请求超时后可终止并重启整个 sidecar，不需要再嵌套一层
Pyne worker，Windows 下也不会引入额外 spawn 状态。

## Render IR 覆盖范围

0.2.0 通过 `render.histogram-series/1` 与 `render.structured-output/1` 映射
Pyne output-schema v1 的输出：line、histogram、marker、hline、fill、背景、K 线着色、signal、
legacy label、strategy report 与 drawing objects。映射只使用 SDK 的 JSON-only
`RenderCollections`，未知集合 fail closed，不夹带 Pyne Python 对象或 CandleScope
私有 transport。output-schema v2 新增集合在这条旧 Render v1 路径上会明确拒绝，
不会静默丢失。

Phase 0 的 HTTP compute、range 和 WebSocket golden 已能由 sidecar 原样重建。真正
有状态的 realtime session 仍不属于协议 v1；sidecar 路径按每次已确认 bars 做 batch
执行，不能宣称是 incremental session。

## 新增会话与数据代理契约

开发版另外导出 `candlescope.pyne-session/2` 和
`candlescope.pyne-data-broker/1`，供独立 Pyne 工作台适配器使用。会话服务支持
有上限的 TTL/LRU 增量会话、预览/确认 K 线、断线重连快照、滚动保留和显式关闭。
数据代理不会把 CandleScope 数据库或网络对象交给 Pyne；Pyne 只返回精确的
symbol/timeframe/start/end 请求，并只接受 Host 关联校验过的 OHLCV 页面。
v2 消费方还能取得不经冻结 Render v1 缩窄的原生 Pyne 输出；独立的
[`candlescope-plugin-pyne-workbench`](../candlescope-plugin-pyne-workbench/README.md)
负责把其中可表达的部分显式投影到 chart-layer/2。

现有 `candlescope.pyne` 继续保留冻结的 `candlescope.script-runtime/1`
`executeBatch` 路径。v1 仍是无状态执行，不自动获得会话或数据代理权限；未启用
新版工作台协议时，行为与原来一致。

## 本地开发

```powershell
cd packages\candlescope-plugin-pyne
python -m pytest -q
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python -m build
```

构建 `.cspkg` 时需要四个 wheel：本插件、SDK、官方 Pyne Runtime，以及和目标
Python/操作系统匹配的 NumPy。`scripts/build_bundle.py` 会读取 wheel metadata、核对
精确版本、校验官方 Pyne wheel SHA，再调用通用 `.cspkg` builder。生成的 bundle 是
平台/ABI 相关产物，外层 SHA-256 必须和 bundle 一起发布。

从本目录执行一条完整的 Windows CPython 目标构建链：

```powershell
$wheelhouse = 'C:\release\candlescope-pyne\wheelhouse'
New-Item -ItemType Directory -Force $wheelhouse | Out-Null

python -m build --wheel --outdir $wheelhouse .
python -m build --wheel --outdir $wheelhouse ..\candlescope-plugin-sdk
Invoke-WebRequest `
  -Uri 'https://github.com/helenananaa/pyne-runtime/releases/download/v0.4.0/pyne_runtime-0.4.0-py3-none-any.whl' `
  -OutFile "$wheelhouse\pyne_runtime-0.4.0-py3-none-any.whl"
python -m pip download --only-binary=:all: --no-deps `
  --dest $wheelhouse numpy==2.3.3

$bridge = (Get-ChildItem "$wheelhouse\candlescope_plugin_pyne-0.3.0.dev1-*.whl").FullName
$sdk = (Get-ChildItem "$wheelhouse\candlescope_plugin_sdk-0.2.0-*.whl").FullName
$pyne = (Get-ChildItem "$wheelhouse\pyne_runtime-0.4.0-*.whl").FullName
$numpy = (Get-ChildItem "$wheelhouse\numpy-2.3.3-*.whl").FullName

python scripts\build_bundle.py `
  --lock release\release-lock.candidate.json `
  --wheel $bridge --wheel $sdk --wheel $pyne --wheel $numpy `
  --output C:\release\candlescope-pyne\candlescope-pyne-0.3.0.dev1.cspkg `
  --json
```

builder 输出的 `.cspkg` SHA-256 应进入同一次可信 Release。安装方仍应使用通用
`candlescope-plugin install <bundle> --sha256 <published digest>`，不能临时对未知 bundle
自行计算摘要后当作信任来源。插件升级时同时升级 package version、release lock 与
probe hash，禁止覆盖同版本 artifact。
