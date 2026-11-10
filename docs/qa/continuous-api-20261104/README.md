# 连续策略 HTTP / WebSocket 接入

基于 Draft #252。应用、请求契约与新增测试的组合 SHA256：`ff3c174fb0038c0e224b73deef81562c2469c99e41166d7a00e2880f768e81df`。

## 使用流程

所有访问经过已存在的 DataManagerCore.strategy 所有者；路由不会新建或接管执行账户。API 前缀为 `/api/v1/backtests/continuous`。

1. `GET /capabilities` 返回当前配置模式、实际执行资格、SDK Python 作者契约、UTC 1m/V1 账户和容量限制。LOCAL_OFFLINE 仅查看已有结果。
2. `POST /runs` 携带一个稳定的 `Idempotency-Key`、完整市场身份、当前代码/参数及执行设置；返回 202 创建回执。两种连续模式不创建用户策略版本或伪造 smoke。Python 编辑器沿用已有本地应用 Origin 授权。
3. `GET /runs/{id}/initial` 等待初始化截止点，经 HTTP 返回首个有界结果页。按照 `more/next_cursor` 用 `POST /runs/{id}/results/query` 拉取剩余页面，每页携带完整 `expected` identity。分页期间身份变化应丢弃尚未完成的视图，再重新加载。
4. HTTP 初始结果整组封存后，连接 `/runs/{id}/stream?protocol=continuous.v1&after=<URL 编码完整 identity>`。交接间新增数据由同一后端账户追赶；前端不得重新创建或回算账户。`begin/complete` 封存分块；reset 丢弃未完成组。检查点过期或代际/来源变化显式要求完整 snapshot。心跳不读取账户历史。
5. `GET /requests/{request_key}` 恢复丢失的创建回执；控制通过 `POST /requests/{request_key}/control`，校验创建 revision 和已观察账户 identity。WebSocket 只接受 ping。断开 HTTP/WS 只释放视图，不停止后端执行。

请求流、JSON 深度/节点、字符串、有限数值、重复字段、分页和响应体均有界；字段校验错误不回显源代码。已处理历史修订后保留原结果并立即返回 `stale=true / REPAIR_REQUIRED`。修复操作仍未提供，capabilities 明确返回 `repair_available=false`。

初始等待者纳入请求容量和应用关闭流程；关闭前取消并排空视图，避免在 SQLite 关闭时留下等待者。重连身份只读取检查点元数据，不解码完整恢复状态。

## 验证

`api-full.log.gz`：**426 passed，5 既有 warnings，0 skipped**。覆盖连续来源/Provider/Controller/结果/Manager/API、账户清算、源前缀、执行器、数据管理及完整离线应用生命周期。这不是全仓检查。

新增 18 个真实 ASGI HTTP/WS 场景，仅替换公开市场传输租约，真实使用 Manager、策略 Provider、SQLite 和账户：builtin/SDK Python × 两种连续模式；HTTP→WS 交接注入新 K 线；分页全量与财务检查点逐项核对；丢失回执恢复；Origin 与非法/过大/非有限/重复字段拒绝；真实 http.disconnect 后准备继续；关闭时释放初始视图；WS ping 与非法控制；过期/超前 cursor；已处理历史修订标旧；LOCAL_OFFLINE 保存结果只读。固定历史版本与 smoke 创建入口被替换为失败断言，确保连续执行没有暗中创建版本。

首次 API 聚焦运行 9 通过、1 失败：Content-Length 的 413 被 ValueError 捕获改成 400，原因是 BacktestError 继承 ValueError。分离数值解析与尺寸检查后 10、16、51 项分组回归均通过，最终集合通过。原失败日志保留。

架构检查仍返回既有 10 条，与 main 基线逐字节一致。前端本轮未改；三种模式界面、授权修复和原生完整退出/重启验收待继续。本轮未启动公开行情或原生包；不把这些结果作为 LIVE/Windows 产品资格。

CI 后台运行；合并 main 前核对最终 head 的 CI。
