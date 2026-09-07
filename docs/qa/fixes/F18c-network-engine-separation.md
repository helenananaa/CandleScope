# F18c 交易所网络成功未区分本地数据引擎

原因：网络检测仅访问三个交易所 ping/time 接口，其成功与 DataManager 启动无关。原页面没有展示本地引擎状态。

修复：同一检测响应追加 data_engine 生命周期状态，独立于网络 success；通过 DataManager 的小型内存健康快照判断 started。界面明确区分“交易所网络”和“本地数据引擎”，未初始化/未启动显示未就绪，快照异常显示检查失败，字段缺失/无法判定显示未知，只有 started=true 才显示已启动。附注说明网络可达与指定品种历史可用并非同一判断。九种语言补齐文案。

验证：

- 22 项后端设置/引擎状态测试通过，其中模拟三个交易所均成功、DataManager 未初始化，确认 success=true 同时 data_engine=not_initialized；覆盖 started true/false、未知快照、快照异常。
- 前端渲染测试验证网络成功同时引擎未知或未初始化时不会显示“Started”。TypeScript、ESLint、生产构建、git diff --check 通过。
- 电脑操控生产版对旧后端实际检测：3/3 网络成功、引擎未知；加载新后端后再次实际检测：3/3 网络成功、引擎已启动。截图和 AX 为 `output/user-audit-20260907/evidence/fix-F18c-old-service`、`fix-F18c-started`；日志 `F18c-*.log`。

运行记录：本次重启测试后端以加载 Python 修复。旧进程收到 SIGTERM 后停止监听，但约两分钟仍停在 Uvicorn “Waiting for connections to close”；随后发送 SIGINT，确认进程退出后才启动新实例。新实例无 --reload，使用原 18080 端口，启动日志 `output/user-audit-20260907/backend-F18c.log`；图表请求和 WebSocket 恢复。该关闭等待保留为待复核观察，未在本提交修复。

边界：未在 GUI 人为卸载依赖或破坏真实 DataManager；未初始化状态通过接口和渲染测试覆盖。这里检测生命周期启动，不是逐交易对历史完整性或整个插件系统健康。复制诊断摘要仍待处理。
