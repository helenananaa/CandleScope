# Pine 图表增量传输与两处确认丢失

源码 `519944f7a4e9786c01045dfa83fc9e4ea22a4579`，main `b442555d582dc0bb473bad92ac5e699efdaa78d5`。Apple M1、macOS arm64、Python 3.12 和固定的 Pine core 0.3.3+cs.1。实验使用真实 FastAPI HTTP/WS、DataManager 查询和路由事件总线、进程间 JSON-RPC 与 Pine worker。标准 1m BAR 输入来自确定性测试源。

## 故障恢复

- worker 已持久化一条盘中观察，成功回包在宿主读取后被丢弃。宿主通过 I/O 错误收束旧进程。下一次 HTTP 读取从原点重建新一代，只返回已确认前缀。同一形成中 BAR 的下一次观察从该前缀推进一次。
- 宿主已接纳但 WebSocket 发送失败。重连读取同一代、同一序号的投影，无额外 worker 请求。新观察恰好推进一次。
- 两项注入与相邻回归共 40 项通过。首轮测试对自动重建的预期有误，原始日志保留。

## 传输与序列化

每组同一 varip 计数器在一根形成中 BAR 上接受 24 次观察，前 4 次不计入统计。对照组仅清空 IPC 输出基线，保留输入增量，走当前 worker 的全量结果和当前宿主的全量 WS 快照。两模式最终投影指纹一致，每次观察均检查计数、序号及代际。表内成对数值依次为增量和全量。

| 历史 BAR | IPC 响应中位字节 | WS 消息中位字节 | 增量宿主序列化中位 ms | 发布至 ASGI 客户端 P95 ms |
| ---: | ---: | ---: | ---: | ---: |
| 1,000 | 2,748 / 68,555 | 3,449 / 99,741 | 0.23 | 14.17 / 21.66 |
| 10,000 | 2,754 / 680,561 | 3,452 / 990,749 | 1.47 | 19.99 / 142.61 |
| 40,000 | 2,754 / 2,780,561 | 3,452 / 4,050,749 | 5.48 | 27.96 / 387.31 |

增量路径每次只发送 1 根 BAR，单次查询覆盖相邻两个开盘时间。宿主范围替换仍先序列化 1,001、10,001 和 40,001 个保留点。首次订阅、冷 seed 以及每项 P50/P95/P99 的原始数据见回执。40,000 根用例在默认 DataManager 10,000 根查询上限下被报告为范围未就绪，表中该行只在把测试实例上限提高到 50,000 后取得。

此对照使用相同候选源码的全量回包模式。历史发布版端到端比较、浏览器绘制、CPU/RSS、修正与冷恢复耗时、100,000 根、更多脚本类型、真实持续行情和 Windows 仍需独立验证。

## 复跑

从仓库根目录启动。使用已安装指定 core 的测试 Python，数据目录和报告目录设为独立临时路径。

```sh
export PYTHONPATH=packages/candlescope-plugin-pine-compat/src:packages/candlescope-plugin-sdk/src:packages/candlescope-backtest-sdk/src:backend
export PYTHONDONTWRITEBYTECODE=1
export PINE_MATRIX_OUT=/absolute/path/to/isolated/report
export DATA_DIR=/absolute/path/to/isolated/data
export CANDLE_DATA_DIR="$DATA_DIR"
unset KLINES_DB_PATH
mkdir -p "$PINE_MATRIX_OUT" "$DATA_DIR"
for mode in delta full; do
  PINE_MATRIX_RESPONSE_MODE="$mode" python -B -m pytest -q docs/qa/pine-wire-matrix-main267-20261107/test_pine_wire_matrix.py
done
python -B -m pytest -q backend/tests/test_chart_calculation_ack_loss.py
```

[指标、环境和证据指纹](receipt.json)
