# candlescope-backtest-sdk

`candlescope.python-strategy/1` 的作者类型。策略只返回 `SIGNAL`、
`TARGET_POSITION` 或 `ORDER_INTENT`。数据、watermark、撮合、费用、资金费、
风控、账户、ledger、报告、Study 和审计始终由 CandleScope Host 拥有。

本包不含后端、数据库、网络或 Plugin Platform 客户端。

官方首批模板在 `templates/`。本地 10 分钟路径见
`docs/BACKTEST_PYTHON_LOCAL_BETA_GUIDE_zh.md`。

版本化纯行情批量接口原型见 [sma_cross_batch](templates/sma_cross_batch/README.md)。
该接口须显式选择，当前宿主只开放给认证的官方 SMA，不改变原逐根脚本协议。
