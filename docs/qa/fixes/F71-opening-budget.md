# F71 / QA-61：满比例开仓漏计手续费和滑点

2026-10-14，P1，第64版修复中。

原生第62版`QA-RISK-HEDGE-v62`，100 USDT、100x、SOLUSDT，100%给出91.18263882 SOL。市价开空成功，成交均价109.659033、费用4.9995，按标记价109.67估值后权益约94.0005、可用约-5.9995。证据`evidence/QA59-v62-open-short.png/txt`。后续独立tracks快照在标记109.63时，权益97.64780555286106、可用-2.31572138713894，见`qa59-v62-risk-progress.json`。后续行情波动造成负可用与入场时漏计成本须区别。

根因：broker和全局共享账户均只按可用权益×杠杆/价格计算开仓容量，委托准入也仅预留保证金。候选统一费用、价格步长引起的逆向滑点和保证金预算，用同一口径限制最大数量与直接委托，平仓不受此开仓限制。挂单触发后的跳空及多商品/逐仓资金约束需要单独回归，未完成前不判关闭。

候选测试与生产复验进行中，不把旧包中开仓成功写为风控通过。

候选加入成交触发时的实际现金复核，跳空导致保证金加费用超过资金时拒绝新增风险，降低已有风险及强平执行保持独立。94项风险/多商品/复盘/确定性回归通过（`qa61-budget64-trigger.log`，58.51秒）；更广泛挂单、双向保证金及账户输入回归正在执行。挂单预算现在同时预留费用，旧测试的6000保证金预留调整为6009（180×100/3 + 180×100×5bps），可用资金3991；保留拒单及财务断言。

扩大回归162项通过（`qa61-budget64-broader-fixed.log`，71.06秒），前端480项通过，30语言4695键检查通过。订单预览标签改为预留金额（含费用），金额尺寸模式中的保证金名称保持原义。第64版构建中；原生满比例开仓、跨商品跳空触发的共享资金边界、完整重启仍待复验。

第64版原生样本`QA-BUDGET-HEDGE-v64`，run `fd389bc64aec4d3da3560bd4a9110a92`，与原故障同为SOLUSDT/03:57/100USDT/100x/HEDGE_HYBRID。100%参考86.01283722，预留显示100USDT。实际开空后费用4.71604228，浮盈-0.94330278579174，保证金94.33027858，权益94.34065493420826，可用0.01037635420826。独立Decimal按数量、成交价、5bps、固定mark109.67及100x重算全部相等，见`qa61-v64-native-budget-short.json`、`evidence/QA61-v64-full-budget-preview.*`、`QA61-v64-full-short-open.*`。随后原生全平成功，零容量正确、权益/可用约88.68；继续验证开多与重启。

第64版随后原生100%开多76.27649932成功：累计费用13.61606798，已实现-1.88660557158348，浮盈-0.83652436804244，保证金83.65243681，权益83.66080208037408，可用0.00836527037408。独立Decimal一致，见`qa61-v64-native-budget-long.json`和`evidence/QA61-v64-full-long-open.*`。返回大厅成功（下一次观察距点击56.116秒，无法由该观察确定精确保存时长），正常Cmd+Q退出。

补发现：在先前SELL容量76.28441487下选择100%后点击开多，第一次新报价BUY上限76.27649932，旧数量超出而未提交；第二次点击成功。不能称为静默失败，先前过滤后的AX没有完整保留瞬时错误提示。第65版候选让显式百分比使用目标方向新容量，并确保预览和最终提交用同一数量；手动输入和风险计划尺寸保持各自语义。使用整数小数运算按数量步长向下取整，覆盖小数/整数/科学记数步长；同时修复旧数量格式化在整数步长时错误删除整数末尾0。前端481项通过，类型检查和针对性lint通过；原生单击切换方向待验证。

第65版原生交叉方向复验通过：平多后BUY方向100%报价59.98542116，单击开空实际59.99164609；全平空后SELL方向100%报价53.20010693，单击开多实际53.19458673。两次均只点击一次目标开仓按钮，新的目标方向数量已进入真实模拟持仓。最终权益约58.34、可用约0.01（该训练多次满仓来回支付手续费，现金下降符合测试操作）。证据`evidence/QA61-v65-buy-quote-sell-submit.*`、`QA61-v65-sell-quote-buy-submit.*`和`qa61-v65-cross-side-final.json`。第64版持多76.27649932/权益83.66080208037408在第65版完整重启后已正确恢复。跨商品跳空触发共享资金边界仍保留专项验证。

## 2026-10-15 独立 PR 提取验证

F67/F71 从快照 `dc3d0544` 提取到 `2947ae1d` 基线，保留同一预算函数用于 broker 容量、准入和共享账户预留；`training/service.py` 只携带修改委托与仓位意图所需的方向、仓位腿和杠杆字段。没有带入 HEDGE 输入迁移、分支恢复、推进优化或指标链路改动。历史测试仅调整预算增加导致的预留金额及可用权益期望值，拒单与财务断言保留。

当前提取版本验证：

- 在 `backend` 运行 `python -m pytest -q tests/test_replay_risk.py tests/test_replay_orders.py tests/test_replay_order_workflows.py tests/test_replay_v2_training_phase5.py tests/test_replay_v2_training_hedge_phase9.py`：77 项通过，12.58 秒。覆盖单向/双向、买卖方向、满比例费用与滑点、直接越额委托、后续跳空拒单、共享资金和已有强平路径。
- 在 `frontend` 运行 `node --import ./scripts/monaco-esm-loader.mjs --import tsx --test src/features/replay/__tests__/replayOrderSizing.test.ts src/features/replay/__tests__/replayOrderAdvisoryScheduler.test.ts src/features/replay/__tests__/replayOrderCtaState.test.ts src/features/replay/__tests__/replayTrainingWorkspace.test.tsx`：51 项通过。
- `npm run typecheck`、`npm run check:i18n` 和 `npx eslint src/features/replay/replayOrderSizing.ts src/features/replay/components/ReplayRightRail.tsx src/features/replay/__tests__/replayOrderSizing.test.ts src/i18n/catalogs/*.ts` 通过。

第64/65版的原生结果保留为历史证据；本次未为提取后的提交重跑桌面包和完整重启。跨商品跳空触发的共享资金边界、逐仓边界和更多挂单组合仍需生产专项验收，不能由当前77项自动测试推定全部通过。
