# F27：先关闭原生窗口，再等待后端退出

日期：2026-09-08。

## 复现

原生应用打开实时行情、盘口和警报 SSE 后按 Cmd+Q。before-quit 阻止窗口关闭并等待后端停止，窗口仍保持 HTTP 长连接；Uvicorn 一直停在 Waiting for connections to close，最终由桌面壳 15 秒超时强制结束，缺少 Application shutdown complete。两次原生退出观察相同，见 output/user-audit-20260908/native-exit-before.log。

## 修复

before-quit 仅批准窗口关闭，将后端和静态资源服务器的异步停止移至 will-quit。后者在窗口关闭后触发，渲染器持有的连接能够先断开。保留防重复清理和原有超时保护。

事件顺序依据：[Electron app 官方文档](https://www.electronjs.org/docs/latest/api/app#event-will-quit)。

## 验证

- 39 项桌面测试通过，原生 arm64 重新打包成功；production dist 与前项一致。
- 两次 Computer Use 原生 Cmd+Q 复测，均观察到 Application shutdown complete 与 Finished server process，正常退出。
- 第二次由外部父进程记录按键发起到原生进程结束为 982 ms、exit code 0；这是一组本机样本，不是性能分位数或跨平台保证。
- 首次 287 ms 数据仅是监听端口消失，不能当作后端进程完全退出耗时；完整结束以日志及第二次父进程证据为准。
- 证据：native-exit-tests.log、native-exit-package.log、native-exit-after.log、native-exit-ready.txt、native-exit-repeat-result.json，均位于 output/user-audit-20260908/。

边界：本项解决原生壳的退出顺序，不代表在浏览器保持长连接时直接给独立 Uvicorn 发送 SIGINT 也会立即结束；服务端优雅退出等待活动请求与此场景应区分。
