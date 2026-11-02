# 交易复盘数据读取与步长边界

应用源码为 `de8f3782ab387249a8876773f8477f884ff001e9`。本批覆盖交易记录入口：经工作区 MarketDataManager 读取兼容历史、独立复制已载入数据、隔离请求取消，以及切换细粒度步长时按请求身份隔离旧 K 线。未增加任意图表回放入口，也不宣称多页读取构成后端原子快照。

真实 Chromium 中运行实际 QuickReplayOverlay 和图表，历史传输由受控异步响应提供。先载入 5m，再切到尚未返回的 1m 并推进一分钟：修复前图表读到了旧 5m 的 high=999、close=998；修复后未显示该形成中 K 线，1m 返回后才显示 high=102。见 `step-before.json`、`step-after.json`；中间一次组件通过但运行器误执行编辑器检查的失败也保留。

44 项针对性检查、4,712 项完整前端测试、1 项独立性能检查、127 项桌面测试、架构、插件、30 语言、两套类型检查、lint 和生产构建通过。上一轮完整测试中，一项绘图竞态测试受真实耗时影响产生额外分片；现使用固定时钟测试实体数分片，未改变生产性能阈值。计数、来源哈希、日志捕获限制见 `checks.json`。

此证据属于开发验证。最终主线集成、对应提交 CI、安装包完整退出和重启，以及一般图表游标持久化、更新提示和更广泛指标/笔记验收尚未完成。

浏览器复现：在 frontend 执行 `CANDLESCOPE_TEST_BROWSER_START_TIMEOUT_MS=120000 node scripts/frontend-script-integration.mjs --quick-replay-step --out ../output/your-unique-directory`。
