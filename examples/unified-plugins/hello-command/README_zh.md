# Hello Command 统一候选

旧 SDK 样例 `candlescope.hello-command` 的统一候选为 `0.2.0`，保留 `hello` 命令和原问候结果。选择 **Say hello**，修改 `name` 后运行。候选以完全信任的 Python sidecar 调用，需通过统一包的明确批准。旧协议的延迟调用、取消令牌和探针回执作为历史资料保留。

在仓库根目录使用安装了后端依赖的 Python 构建。

```sh
python backend/scripts/unified_plugin.py build examples/unified-plugins/hello-command /tmp/hello-command-unified.cspkg
```

包暂存、审批和调用使用统一生命周期。隔离配置的回归覆盖中文参数、无效输入后重试、停用及拒绝过期调用。已有本地安装可先停用旧版，再审阅候选摘要。迁移期如需回滚，先停用新版，再启用保留的旧版。旧批准和私有数据保留在原命名空间。
