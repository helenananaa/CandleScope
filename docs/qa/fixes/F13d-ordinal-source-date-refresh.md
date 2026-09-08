# F13d：合成图补历史后横轴保留旧日期

日期：2026-09-08。原生 Mac arm64 production 包，Binance BTCUSDT 1h，点数图。

## 复现与定位

以传统固定箱格 500、反转 3 排除 ATR 进入时重算的变量。滚轮缩小触发源历史 2001→2501，图形位置稳定，但横轴日期落后于新数据；切出再返回时图形基本不动，日期却从七月变成六月。证据 viewport-fixed-prepend.png 与 viewport-fixed-returned.png。这至少解释了原“往返视野偏移”观察中的日期误导，不能把 ATR 重算造成的结构变化也视为同一缺陷。

两层原因：标签缓存按 ordinal order 键复用；Lightweight Charts 的共享 time point 也按 order 复用，即使新列的 sourceTime 已改变仍保留旧日期。只改标签缓存的第一轮修复通过单元测试，但原生复测仍失败，证据 axis-label-fixed-before-roundtrip.png 与 axis-label-fixed-returned-first-attempt.png；该不完整版本未提交。

## 最终修复

- 格式化缓存改用 sourceTime，布局/排序仍用 ordinal order。
- 只在已有 ordinal 位置改绑源时间时刷新共享时间点；普通价格更新和纯尾部新增无需刷新。
- 快照所有序列，清空共享时间点后首先恢复主图、再恢复辅助序列，保留可见逻辑范围。即使某次写入异常也继续尝试恢复其他序列并向既有错误恢复路径报告。
- 刷新代价随当前序列数据量增长，限定在坐标日期重写的结构更新；没有以每 tick 全量重绘修复。

## 验证

新增日期缓存复用回归在修复前明确失败（六月被格式化成七月）；共享多序列时间点测试覆盖旧时间元数据、主图优先、数据和视野保留、普通尾部更新不刷新。最终 426 项适配器/表示测试、45 项组件/绘图表面测试、TypeScript、相关 ESLint、production build、Mac arm64 打包通过。

最终 Computer Use：固定 500 箱格的原生点数图 1501→2001，补载后日期正确；普通 K 线→点数图往返，图形位置、日期一致。证据 axis-label-final-{initial,prepend,candles,returned}.txt/png；最终日志 axis-label-final-{tests,typecheck,lint,build,package}.log、axis-label-component-tests.log。全部位于 output/user-audit-20260908/。

边界：手工补载走当前图表数据通道，未新增 HTTP intent=viewport 日志，不能伪称抓到了这一参数的新请求；根数增长和图形扩展由原生 GUI 记录确认。ATR 自动模式按现有界面说明在重新进入时解析箱格，实时数据改变会影响结果；本项未改变这一产品约定。尚未声称穷尽所有合成算法、插件层和长时性能场景。
