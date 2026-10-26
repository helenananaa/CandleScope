# 指标运行时路由

默认仅启用 `pine=sidecar,candlescope.pine-compat`。内置指标继续由本地指标引擎计算，社区脚本语言可通过显式路由配置接入。

应用启动时验证配置中的运行时是否已安装并就绪；缺失的必需运行时会导致启动失败。HTTP、批量计算和 WebSocket 共用同一路由服务。`GET /api/v1/indicators/runtimes` 返回可用语言与公开描述符。

Pyne 已移除，不再支持它的脚本、路由配置、策略提供器和安全策略端点，也不会把旧脚本转换成 Pine。请从显式路由文件中移除旧条目。`docs/evidence` 中的历史记录仅描述当时版本，不代表当前能力。

详见 [英文路由文档](RUNTIME_ROUTING.md)。
