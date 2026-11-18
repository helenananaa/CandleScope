# 统一插件宿主（第 3 批）

共同 owner 保存唯一的包期望配置，执行器消费同一份验证后的计划。
默认存储位于既有平台 root 的 `unified/`；可用
`CANDLESCOPE_PLUGIN_PLATFORM_V2_ROOT` 改平台 root。live/offline 均接入。
本指南对应 #349 的执行器批次；#350 构建前依赖接管、独立恢复，#351 Pine/
旧消费者迁移和旧协议退役仍未交付。旧注册表暂时服务其既有消费者，统一包不会绕到旧执行器。

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
| data | 有界 JSON 校验与读取 | ready；尚不自动应用为主题或布局 |

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

## 管理、状态与恢复

`/api/v2/plugins/manage/unified` 的目录、stage/review/change/invoke 使用既有
LocalManagementGuard；realm/report/check 使用同一会话、Origin/CSRF 的后台授权。
资源使用短期、实例绑定的 bearer 票据，禁用缓存并验证摘要。不要记录或分享资源 URL。

目录分别展示期望版本与各入口实际状态。停用先 pending-stop，JS 清理后仍报告 pending-restart；
后端版本变更同样等待进程重启。断联客户端到期显示 unavailable，不伪装为已停止。
多窗口各有独立实例。核心 owner 持有进程生命周期锁，防止同一 root 被重复执行。

`--extensions-safe-mode` / `CANDLESCOPE_EXTENSIONS_SAFE_MODE=1` 跳过统一代码执行，
保留管理恢复；现有外层恢复通知也展示统一执行错误。独立原生恢复、崩溃 marker 与启动前
依赖替换的完整证明属于 #350，不能用本批源码测试替代。

Pyne 已退役：显式拒绝其旧归档和入口，不转成 Pine/Python，不删除原始文件或历史证据。
