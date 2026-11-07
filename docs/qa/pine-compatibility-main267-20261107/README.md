# Pine 图表兼容路径的切换与隔离验证

在 `b102f28015c01956dc91473246a7217998b21d9c` 上运行真实 HTTP、WebSocket、DataManager、SQLite、行情事件总线和固定 Pine core 0.3.3+cs.1。使用确定性的 Binance BTCUSDT 1m 测试输入。

- 增量会话先在同一根形成中 BAR 上处理两次观察，计数由 500 变为 502。调用 DELETE 后，写入连接收到 `INDICATOR_CALCULATION_CLOSED`。复用旧引用会收到 `INDICATOR_CALCULATION_NOT_FOUND`，且未调用运行时。
- 兼容客户端使用同一脚本和行情，先经 `/indicators/range/batch` 重建。500 个已确认计数点逐一一致。随后使用无 `calculation` 引用的订阅，第一条新盘中观察返回计数 501 的快照。切换明确重置此前盘中观察。
- 两条兼容连接同时使用相同图表 ID、标的和脚本，第二条连接从第一条的盘中状态继续执行。预期独立的计数为 503、501，实测为 503、504。兼容订阅的 `pineSessionOwner` 使用 `clientId`，两条连接在同一标的上得到相同的 sidecar 会话身份。启用兼容回滚前需保留合法重连语义，并隔离并发写入。

当前 renderer 直接根据 Pine 类型选择图表域。已有运行时路由配置选择 sidecar，兼容 HTTP/WS 仍可能协商 IPC 变化。因此上述验证只覆盖手动客户端切换。已安装应用的显式启动切换、跨平台发布和回滚仍需独立验收。

第一次实验等待兼容 WS 主动发送初始快照，但该入口先返回未播种的订阅确认，历史由 HTTP 获取。第二次实验纠正了顺序，第三次按批量 HTTP 的 `results[].payload` 读取并通过。原始尝试日志保留。

从仓库根目录使用已装固定 core 的 Python。设置隔离的 `DATA_DIR`、`CANDLE_DATA_DIR` 和 `CALCULATION_TRACE_DIR`，清除 `KLINES_DB_PATH`，并将 `backend`、插件 SDK、回测 SDK 的源码目录加入 `PYTHONPATH`。分别对本目录中的两个诊断文件运行 `python -B -m pytest -q <test-file>`。切换用例通过，隔离用例在本次源码上复现失败。

[证据指纹与结果](receipt.json)
