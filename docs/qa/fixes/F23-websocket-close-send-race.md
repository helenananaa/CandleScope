# F23：行情连接关闭后发送产生 ASGI 异常

## 证据与复现

F20c 发行版电脑操控测试刷新行情页面时，`backend-F20c.log:211–272` 捕获 `stream_market._forward` → `send_json_with_timeout` → Uvicorn 的异常：

`RuntimeError: Unexpected ASGI message 'websocket.send', after sending 'websocket.close' or response already completed.`

接收协程和转发协程并发运行。传输层观察到关闭时，Starlette 的接收任务可能还没收到 disconnect；此时发送不是抛出 WebSocketDisconnect，而是上述 RuntimeError，越过正常断连处理成为 ASGI 异常。原有 finally 会执行，不能据这条堆栈断言已有订阅泄漏。

新增确定性测试让传输层在 update 发送时先关闭，并让接收任务继续等待。修复前 3 项失败、1 项通过，失败与现场异常一致；既有业务 RuntimeError 仍可观测。

## 修改

共享 JSON/text 发送边界将两个框架明确的已关闭消息（Uvicorn ASGI 已关闭，以及 Starlette 本地已 close）转换为 WebSocketDisconnect(1006)，由各流现有断连路径清理。1006 是本地异常信号，不向已关闭连接发送 close 帧。

不吞掉其他 RuntimeError，不改变超时和一般错误的指标记录；不通过单次检查 application_state 假装消除检查与发送之间的竞态。已知正常断连不再计入普通发送错误。

## 验证

- 83 项相关测试通过：新增传输关闭测试、行情、K 线、批量 K 线、盘口、完整盘口、成交、清算、回放流测试。
- JSON 和 pong 两种发送路径、两种明确关闭错误均转为断连；无关 RuntimeError 保持抛出。
- 确定性行情集成测试确认释放一次已取得租约，活跃订阅归零，无残留 market-ws 读写任务。
- 前端 `npm run build` 成功，后端无 reload 重启后使用生产预览 `127.0.0.1:15173`，电脑操控刷新三次并检查行情重新连接。测试记录 `F23-refresh-{1,2,3}`。
- `git diff --check` 通过。没有改动前端业务代码。

日志：`output/user-audit-20260907/F23-before-tests.log`、`F23-tests.log`、`F23-build.log`、`backend-F23.log`。截图/AX 在同目录的 `evidence/`。

## 边界

现场问题是并发时序，不以有限次 GUI 刷新无异常代替确定性测试。当前适配依据本机已安装 Starlette/Uvicorn 的明确消息，框架升级后不同错误形态仍会正常上报。没有把此修复声明为修复全部连接错误、服务关闭等待或性能热点；生产预览仍不等同于 Windows 原生发行包测试。
