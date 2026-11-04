# SessionCalendar尾部规划：不枚举十年分钟

#245最终8952f5b0的macOS x64 CI（workflow41811076870/job126510177253）在原有test_latest_session_tail_planning_is_bounded_for_large_limit[1m]失败：请求实际1000根、花费1.2726秒，原1秒门槛未满足；其余1565项通过、3项跳过，arm64 job成功。Klines API与calendar源码相对main b75fb1ac未变化；本批独立修复该共享规划开销，不把失败忽略或放宽门槛。原CI片段保留。

SessionCalendar.last_expected_open原先遍历expected_opens整个十年候选期，只取最后时间。现在对内置子日网格按合并session段的UTC起点、间距与闭合右边界算最后open；按最近段回看，跨午休、跨夜、合并重叠、DST与覆盖日仍沿用原session段/锚点。日/周/月仍复用原coarse候选规则。覆盖expected_opens的自定义calendar继续原有迭代语义，不把它们强套到内置网格。没有改策略执行或跳过金融事件。

改前结构用例记录十年1,017,900个minute open，改后不枚举这些历史时间点。完整calendar+Klines API149通过、1条既有提示；最终结构/边界与原有1秒CI用例再跑69通过（原门槛未改）。覆盖7种周期、3种时区/DST窗口、3个边界偏移，以及午休、跨夜、重叠、假期/覆盖、空范围和自定义策略。

固定相同clock/配置/输入的5轮本机带调用计数对照：规划仍返回完全相同的1000根范围；发出的规划open 2,040,872→1,951（保留近期窗口需要的枚举），中位220.35→10.07ms。计数包装本身有开销，此为本地规划成本证据，不是无计数生产时延、交易所/原生性能或SLO。所有样本和脚本可重跑，源码基线a5c289a5。

后端架构与main原有10条逐字节一致。macOS bundled-Python门禁添加calendar语义/结构用例，既有1秒用例继续保留。分支基于#244，CI后台运行；合main前核对最终head，#245仍待修复整合后的新head资格。
