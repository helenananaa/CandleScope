# Frontend design refactor: Phase 5g7 QA (the native Pine panel on the kit)

- Date: 2026-11-15
- Branch: `design/phase-5g7-native-panel`, based on `design/phase-5g6-strategy-tester` (PR #425)
- Plan: [`frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md`](../frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md), the Phase 5 rows. Contract: [`DESIGN.md`](../DESIGN.md)
- **Intended visible change:** the native Pine panel's own body uses kit controls on tokens, in the market page's strategy dock and on the strategy page: the code view's language and inputs, the backtest settings for both engines, run history, the report (metrics, performance chart, trades and orders, details), the incremental replay controls and the strategy comparison. What they do is unchanged. This finishes the strategy tester (5g6 did the dock, its header and the CandleScope tester).

## What changed

| Area | Change |
|---|---|
| Code view | Pine / Python is a kit segmented control (Python still opens the CandleScope tester); 输入参数（JSON）is a kit field with a mono text area. |
| Settings | The two engines stay choice cards, now on tokens with an accent edge for the chosen one. Dates, fees, fidelity, execution origin, account model, leverage, funding and participation rate are kit fields; uploads (execution data, account data) are kit file drops with their help as the hint; 清除 is a quiet button; 成交后执行策略, 按 BAR 成交量限制成交 and 运行独立成本情景 are kit checkboxes with their explanation as the description; 高级设置 and 自动准备的请求上下文 are kit disclosures, and each context is a bordered group of kit fields with 移除 and 添加 as buttons. |
| Run history | 显示全部运行 is a kit checkbox with the ownership note as its description; each run's state is a toned badge; no runs is a kit empty state; the source is a kit disclosure. |
| Report | 交互回放 / 返回分析报告 is a quiet toggle button (pressed while replaying); the performance chart's 累计收益 / 账户权益 / 回撤 and 交易记录 / 订单记录 are kit segmented controls, 买入并持有 a kit checkbox; 上一笔, 跳转 and 下一笔 and the page arrows are kit buttons with a kit number field; 价格, 报告详情, 回测方式, 诊断 and 原始输出 are kit disclosures; the export is a kit link-button. |
| Replay | 创建回放 is primary; 前进一步, 播放, 暂停, 快照, the target and 跳转 are kit controls; restore and resume are quiet buttons; errors are alerts. |
| Comparison | The group name is a kit field; candidates are kit checkboxes; 更新比较结果, 查看准确运行, 打开当前 and 移除 are kit buttons; 收益率 / 回撤 is a segmented control; the conditions table is in a kit disclosure; errors are alerts. |
| Strategy page | The panel's close is a kit icon button; a storage error is an alert. |
| Styles | `nativeStrategy.css` is rewritten on tokens (the element rules for raw buttons, inputs and selects are gone with them); the dock stylesheet drops the retired settings-check and segmented rules. The two class names left without a rule by 5g6's notice fix are removed. |
| Copy | No string changes. |

## Screens

The base build (Phase 5g6, `cd1734aa4`) and this branch, 1440 px, `zh-CN` unless marked. Market page, BTCUSDT 1h, the strategy dock maximized. No native run exists locally, so the report, trades and replay use a fixture run (8 trades, 16 orders, 160 hourly bars) served for the history's GET requests and opened from 运行记录 with 显示全部运行; every write was blocked in the capture and none was attempted.

| | Before | After |
|---|---|---|
| Report (概览) | ![](assets/frontend-design-phase-5g7/overview--before--dark.jpg) | ![](assets/frontend-design-phase-5g7/overview--after--dark.jpg) |
| Report (light) | ![](assets/frontend-design-phase-5g7/overview--before--light.jpg) | ![](assets/frontend-design-phase-5g7/overview--after--light.jpg) |
| 交易 | ![](assets/frontend-design-phase-5g7/trades--before--dark.jpg) | ![](assets/frontend-design-phase-5g7/trades--after--dark.jpg) |
| 运行记录 | ![](assets/frontend-design-phase-5g7/history--before--dark.jpg) | ![](assets/frontend-design-phase-5g7/history--after--dark.jpg) |
| 回测条件, native engine | ![](assets/frontend-design-phase-5g7/settings--before--dark.jpg) | ![](assets/frontend-design-phase-5g7/settings--after--dark.jpg) |
| 回测条件, CandleScope engine | ![](assets/frontend-design-phase-5g7/settings-host--before--dark.jpg) | ![](assets/frontend-design-phase-5g7/settings-host--after--dark.jpg) |
| CandleScope engine (light) | ![](assets/frontend-design-phase-5g7/settings-host--before--light.jpg) | ![](assets/frontend-design-phase-5g7/settings-host--after--light.jpg) |
| CandleScope engine, English | ![](assets/frontend-design-phase-5g7/settings-en--before--dark.jpg) | ![](assets/frontend-design-phase-5g7/settings-en--after--dark.jpg) |
| 高级设置 | ![](assets/frontend-design-phase-5g7/settings-adv--before--dark.jpg) | ![](assets/frontend-design-phase-5g7/settings-adv--after--dark.jpg) |
| Incremental replay | ![](assets/frontend-design-phase-5g7/replay--before--dark.jpg) | ![](assets/frontend-design-phase-5g7/replay--after--dark.jpg) |
| Strategy comparison | ![](assets/frontend-design-phase-5g7/compare--before--dark.jpg) | ![](assets/frontend-design-phase-5g7/compare--after--dark.jpg) |
| Strategy page, native panel | ![](assets/frontend-design-phase-5g7/strategy--before--dark.jpg) | ![](assets/frontend-design-phase-5g7/strategy--after--dark.jpg) |

## Verification

**In the running app** (headless, 1440 px): on the market page the dock's 运行记录 listed the fixture run, which opened its report (metrics, performance chart with its switch and benchmark checkbox) and its 交易 table with a selected row; 回测条件 showed both engines (switching to CandleScope revealed fees, fidelity, account and cost options) and the advanced disclosure; the replay toggle showed the replay controls; the switcher's 策略比较 opened the comparison. On the strategy page the panel rendered with its close button. Nothing that changes data was run: no run, replay, preparation, upload or comparison save.

**Tests:** the backtest, strategy-research, research-data, kit, chart-workspace, app, app-control and data-preparation tests pass (818). `NativeStrategyReport.test` now matches the disabled submit by `type="submit"[^>]*disabled=""` (the kit button puts its class between the two); the other hooks are kept (`native-replay-controls` with `0 / 200 · PAUSED`, `native-report-toolbar`, `native-trade-pages`, `name="trade"` with its bounds, `data-selected`, the stale alert's `data-tone="warning"`).

**Style metrics** (against 5g6): class names with no CSS rule 2 → 0, raw `<button>` 410 → 376, `<Button>` uses 338 → 364.

**Full check:** `npm run check` passes: 5,165 frontend tests, 137 desktop tests, lint (one existing warning), the i18n, style and architecture checks, both typechecks and the build.

## Known gaps

- **Three raw buttons stay on purpose:** the dock bar's result readout, the two engine choice cards, and the history rows (each a two- or three-part row).
- **The report's own SVG charts** (price curve, drawings, series) keep their fixed marker colours.
- **Copy (Phase 6):** fidelity options as codes (`BAR_APPROX`, `TRADE_TAPE`…), run states and engine names (`pine-compat-runtime`) as codes, "撮合数据精度" repeated as both the section heading and the field label.
- **Desktop app:** not tested.
