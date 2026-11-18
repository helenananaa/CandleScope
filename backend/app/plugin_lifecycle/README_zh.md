# 统一插件宿主

共同 owner 保存唯一的包期望配置，执行器消费同一份验证后的计划。
默认存储位于既有平台 root 的 `unified/`；可用
`CANDLESCOPE_PLUGIN_PLATFORM_V2_ROOT` 改平台 root。live/offline 均接入。
本指南覆盖 #349 的执行器和 #350 的可信接管。#351 负责迁移 Pine 及其余受支持的旧消费者，
迁移完成后删除旧注册表和旧协议。

## 构建与使用

从仓库根目录运行：

```sh
python backend/scripts/unified_plugin.py build examples/unified-plugins/workbench /tmp/workbench.cspkg
python backend/scripts/unified_plugin.py inspect /tmp/workbench.cspkg
```

在有可信本地管理会话的应用插件中心导入，核对完整摘要、版本和信任模式，
勾选批准后启用。支持停用、卸载、选择保留历史摘要进行升级或回滚；每次激活使用新 generation。
回滚不回滚用户数据。`private/<plugin-id>/` 与插件产生或修改的运行文件均予保留，
清理只移除仍与校验清单一致的执行文件。

CLI 的 `activate --root ...` 只提交隔离存储的期望配置，没有内置执行器。
元数据 inspector 也不验证完整归档或运行资格；不要把其回执当成应用实际状态。

## 入口契约

所有入口共用 `ActivationIdentity`（pluginId/version/packageSha256/generation），
每个入口实例另有随机 instanceId。依赖先启动、逆序停止；部分启动失败撤销同包其他入口，
未完成核心启动的输出不会对外发布。旧实例的调用、延迟结果、资源票据与状态报告会被拒绝。

| kind | 当前执行方式 | 生命周期接口 |
| --- | --- | --- |
| backend | 独立 Python 模块 namespace，full-trust | 必须 `activate(ctx)`；可返回清理函数；可选 `invoke(ctx, input)`、`deactivate(ctx)` |
| frontend | 当前窗口 ESM，full-trust | `activate(ctx)`，返回清理函数或用 `ctx.track`；可选无参 `deactivate()`；沿用受撤销检查的 UI/commands/events/services SDK |
| desktop | Electron 主进程 ESM，full-trust | 同 JS hook；ctx 含 electron/host、包身份、入口/实例、root/storage、track |
| sidecar | 既有进程监督与 JSON-RPC 传输，新统一协议 | 下述 activate/invoke；停止由宿主管理进程树 |
| sandbox-view | 唯一 opaque iframe 网关 | sandbox allow-scripts、无 same-origin、无宿主 SDK；资源可撤销；挂载前 ready，加载后 running |
| data | 有界 JSON 校验与读取 | ready。主题与布局可在可信扩展页选择 |

Python ctx 暴露 app、identity、entry_id、root、storage、ensure_current、publish、track、task。
`task` 的未处理异常会使包失败；track 资源逆序清理。
JS 插件应使用 SDK-owned 资源或显式 track；原始宿主能力仍属于完全信任应用代码。
异步加载/调用/清理有等待上限，超时撤销采用资格，迟到的清理函数仍会被调用。
同步阻塞或任意全信任副作用不能在进程内强制隔离或保证卸载，因此宿主代码变更需要重启。

sidecar 使用 `candlescope.unified-entry/1`，不是旧脚本协议或旧平台握手的别名。
JSONL 帧沿用 JSON-RPC id/generation；`activate` 参数含 protocol、identity（含 entryId/
instanceId）、storage，响应须精确回显 `{protocol, identity}`；`invoke` 参数另含 input。
stdout 只输出协议，日志写 stderr。示例 `workbench/worker.py` 可直接参考。

Python 模块与 Node 模块、Java JAR、native executable、wasmtime 的启动接线均存在；
本批只本地验证 Python worker，Node 实测的是桌面 ESM 执行器。其余运行时依赖宿主可用程序，
没有随包供应新运行时，也没有声称完成所有平台资格。restricted sidecar 复用既有强制隔离
profile，目前仅其支持的平台可准入；不支持时拒绝，绝不回退 full-trust。
统一 restricted capability 授权尚未接通，非空声明拒绝。

## 图表计算

统一前端入口通过 `ctx.charts.list()` 获取当前文档的图表身份。按选中的 scope 调用
`ctx.charts.invoke(scope, entryId, input)`，可将该图表的已揭示窗口交给同一激活的
后端或 sidecar。宿主可以通过同一管理入口显式选择执行实例；这要求现有可信管理会话，
且图表必须属于该窗口会话。受限 iframe 没有这些宿主句柄。该入口不增加任意历史查询权限。

`candlescope.unified-chart/1` scope 绑定文档、图表、图表实例、模式、运行、轨道、
序列、品种、粒度、数据修订和 `visibleThroughMs`。实时模式无运行和轨道，回放模式必填。
宿主从各图实际使用的行情投影读取最多 256 根 K 线，同时传 `openTimeMs`、已知截至时间
`observedThroughMs` 和 `closed`，禁止包含超出可见边界的行。回放形成中的最后一根
只能使用当前投影已经揭示的数据。切图、改数据版本、回退或关闭后撤销在途结果。
延迟调用方如要稍后采用回执，应再次调用 `ctx.charts.isCurrent(receipt.scope)`。

后端入口 `compute_chart(ctx, {scope, bars, input})` 和 sidecar 的 `chart.compute` 都返回
`{points: [{timeMs, value}]}`。返回点的时间必须是同次请求中的 K 线开盘时间。
后端计算不得将结果通过通用 `ctx.publish` 发布。图表调用返回活跃执行实例、包身份和
原 scope，调用方只采用身份仍然匹配的回执。示例见 workbench 的 `chart-probe`
命令和 Python worker。

## 桌面内置脚本指标

桌面包从锁定的 Pine 引擎、Python 指标执行器和 SDK 构建统一归档。随包的
`unified-pine.json` 和 `unified-python.json` 声明归档名称、摘要和字节数。
首次启动登记内置脚本运行时。后续桌面版本可以替换仍启用的上一个内置默认版本。
用户停用、卸载或挑选历史版本后，由用户决定何时再次激活。

图表指标服务通过 `candlescope.unified-entry/1` 的 Pine 入口发送完整输入窗口，继续使用
现有 Pine 主机数据输入和完整 Render IR。每次响应都检查激活身份，结果快照只属于当前
执行实例。受限 `chart.compute` 使用已揭示 K 线和 `{source, parameters}`，返回与
K 线对齐的单条曲线点序列。完整图形和跨市场输入走图表指标服务。

Python 图表指标走同一个宿主，沿用声明窗口、只计算已收盘窗口、每批新进程及 line/histogram
渲染契约。Python 策略的执行路径独立。

策略和策略回放从同一激活记录派生执行命令，沿用 Pine 策略、图形和账本接口。
启用新版本或停用 Pine 会撤销旧计算并结束该激活持有的策略进程。可执行策略回放
需要保存时的包摘要，同摘要重启后可以绑定到新的实例。旧运行的记录和输出保留，
需要重新执行旧运行时，可以用原脚本和相同输入在统一 Pine 中重跑。

Pine 观察日志保存在 `private/candlescope.pine-compat/observations-v1.sqlite3`。首次发现旧
日志时通过 SQLite 一致性备份复制，保留原日志。隔离桌面配置可用
`CANDLESCOPE_PINE_JOURNAL` 显式指定自己的迁移源。源码环境可以通过
`CANDLESCOPE_BUNDLED_UNIFIED_PINE` 和 `CANDLESCOPE_BUNDLED_UNIFIED_PYTHON`
指定随包描述符，或用统一管理入口安装对应制品。

应用启动和策略解析只读取统一激活记录。旧 `runtime-registry.json`、旧归档和已保存
脚本留在原地。普通桌面构建使用统一归档，旧的脚本安装命令和应用安装端点会提示更新。
源码中的历史资格构建仍可生成旧测试制品。

## 主题、布局和旧扩展

统一包通过保留 ID 为 `theme` 或 `layout` 的 `data` 入口贡献外观。
主题声明 `candlescope.theme/1`、基础色系和允许的视图 token。布局声明
`candlescope.layout/1` 和完整的宿主槽位顺序，需要完全信任。选择与启用记录同事务保存。
停用、卸载或换成无该贡献的版本会清除对应选择。恢复模式使用默认外观。

可信扩展页列出历史安装供核对。纯外观包可以从原摘要生成待审核的统一数据包，
确认后重新选择外观。含代码的扩展需要更新版统一归档。旧制品、记录及被扩展写入的
文件保留。旧加载 API 返回更新提示。

## 管理、状态与恢复

`/api/v2/plugins/manage/unified` 的目录、stage/review/change/invoke 使用既有
LocalManagementGuard；realm/report/check 使用同一会话、Origin/CSRF 的后台授权。
资源使用短期、实例绑定的 bearer 票据，禁用缓存并验证摘要。不要记录或分享资源 URL。

目录分别展示期望版本与各入口实际状态。停用先 pending-stop，JS 清理后仍报告 pending-restart；
后端版本变更同样等待进程重启。断联客户端到期显示 unavailable，不伪装为已停止。
多窗口各有独立实例。核心 owner 持有进程生命周期锁，防止同一 root 被重复执行。

完全信任入口可以在清单声明 `startup` 目标。后端入口的 `prepare(ctx)` 必须调用
`ctx.wrap_factory(target, wrapper)` 注册每个目标，应用随后执行 `wrapper(default, ...)`。
统一期望配置事务拒绝重复目标。宿主在服务构建前拒绝与已加载的旧工厂冲突。
支持的目标是 `data-engine`、`replay`、`alert-delivery`、`indicator-range`、
`market-storage`（市场存储初始化）和 `local-data`（live 的本地数据运行时）。
各目标仍受相应运行模式和功能开关控制。退出先停止消费者，再清理已经注入的资源。
运行中停用立即撤销插件实例的调用和结果，已构建服务持有的依赖要退出后才释放。

窗口入口声明 `startup: ["shell"]`，在首次 React 渲染前调用
`ctx.ui.replaceSlot("shell", Component)`。首次渲染之后新启用的根布局要重开窗口。
恢复通知位于可替换布局之外。示例见 [startup-takeover](../../../examples/unified-plugins/startup-takeover/)。

独立恢复可在完全退出应用后使用原生启动参数。例如 macOS 安装在默认路径时：

```sh
open -na /Applications/CandleScope.app --args --extensions-safe-mode
open -na /Applications/CandleScope.app --args --disable-unified-plugin=example.startup-takeover
```

Windows 将参数传给同一份 CandleScope 安装程序目录里的 `CandleScope.exe`。
`--disable-unified-plugin=ID` 按原子事务停用明确指定的包及它的已启用依赖者，
同时以安全模式启动。完全退出后按常规方式重开。包、脚本和私有数据保留。
后端 startup marker 绑定摘要与 generation，阻止自动重试同一失败激活；通过恢复禁用，
或者明确重新批准后使用新 generation。恢复流程可用于无法进入正常窗口的情况。
完全信任代码含任意进程级副作用，安装版的恢复验收独立于源码与组件检查。

Pyne 已退役：显式拒绝其旧归档和入口，不转成 Pine/Python，不删除原始文件或历史证据。
