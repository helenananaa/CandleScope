# 原生Gate图表错误捕获

同一5bb01926产品字节，QA脚本固定历史区间和MA目标收盘时间，等待自然传播，保持OHLCV逐项精确比较。四来源最终历史与可见MA5独立数学核对均已通过。随后第二次历史核对时，Gate固定区间图表100行、最终数据103行，23次只读观测仍未补入3行；约20秒后Gate图表卸载。

console实际捕获ErrorBoundary caught: Error: Value is null，栈落到LWC Candlestick barStyle 的ensureNotNull(findBar(barIndex))，经SeriesPaneViewBase._updateOptions与hitTest访问。尚未证明具体生产调用点；不得仅据此调整真实历史或屏蔽异常。完整退出15255ms、0未捕获pageerror（React边界捕获另有原始console），退出后源/SDK/前端/插件与严格签名仍一致；无新418。保存/重启验收未通过。

原先MA单帧检查的缺失点8783在失败采集时已到达，说明单帧比较有异步时序误报；新driver用固定截止时间等待完整数学一致，不移除任何目标来源或数值。driver-source及SHA保留。

真实已捕获Gate行与当前真实LWC/投影adapter的单次离线回放已执行（output/gate-renderer-repro），该一次回放未复现异常，因此尚无前端修复。需要继续查多series时间轴重排、可见范围/样式更新和hitTest的交互，不能声称改用setData即可修复。
