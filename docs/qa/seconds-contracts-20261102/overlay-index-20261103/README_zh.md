# Gate补历史与共享时间轴命中测试

旧产品5bb01926的四来源真实历史、独立MA5、新收盘、保存/完全退出/重启曾完整通过；两次正常退出15427/15227ms，截图已目视查看。该一次通过不能覆盖反例：同一产品重开后的真实鼠标悬停，第115帧Gate图表卸载，ErrorBoundary捕获Value is null。raw50帧栈精确落到applyLineSeriesData的indicator setData -> LWC updateTimeScale -> offset compensation -> recalculateAllPanes -> crosshair hitTest -> cached candle style lookup。旧SDK源与签名均未变，无新418。

离线使用当前实际LWC5.1.0与真实已保存Gate行：只有历史视口+悬停/合成联动光标+待应用蜡烛样式+指标补入历史时间点组合稳定失败。其余3个控制组合通过。单次原始rows回放、180轮非历史视口重放及单独稀疏/whitespace更新未复现，均保留output证据，不将其误写为修复。

因果：LWC在将新全局时间索引应用到所有series pane cache之前，先对旧视口补偿；该同步过程刷新十字光标并命中旧样式缓存，旧索引已没有对应蜡烛。修复复用已有owner-render-snapshot索引重放机制：仅在指标整窗替换改变时间点集合前，按系列去重重放当前已提交的主图及指标渲染快照，令LWC在过渡中重建pane cache。没有清除光标、移动视口、伪造空秒、修改指标数学或放宽D126/数据完整性。普通尾部实时update及同时间点纯数值修正不触发新增全量重放。结构修正会增加一次各可见系列快照重放，不能宣称此路径性能改善。

实际LWC和生产helper的8组合对照：旧调用1失败，修复4组合全通过；市场OHLCV、视口logical range和十字光标与无待处理样式的正常控制完全一致。实际鼠标及公开API合成光标都覆盖。64项既有chartData/seriesLifecycle/projection单测和TypeScript通过。新增真实LWC回归已挂入现有indicator-flow browser入口，13项生产压缩浏览器检查通过，0未捕获异常/0残留worker。第一次新测试按JSON属性顺序比较语义相同的OHLCV而失败，已改为字段值元组；原失败日志保留。

新源原生重打包、完整四来源与持续鼠标复验仍待执行，不能把上述组件结果扩成安装包验收或完整#200完成。旧warm诊断曾因路径/控制连接路径错误在测试前中止，以及Upbit MA0等待超时；三次原始失败分别保存，不作产品成功证明。
