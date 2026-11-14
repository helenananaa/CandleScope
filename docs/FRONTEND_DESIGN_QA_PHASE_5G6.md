# Frontend design refactor: Phase 5g6 QA (the strategy tester on the kit)

- Date: 2026-11-15
- Branch: `design/phase-5g6-strategy-tester`, based on `design/phase-5g5-local-data` (PR #423)
- Plan: [`frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md`](../frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md), the Phase 5 rows. Contract: [`DESIGN.md`](../DESIGN.md)
- **Intended visible change:** the strategy tester shared by the market page and the strategy page uses kit controls on tokens. That covers the dock and everything in its header bar for both strategy kinds (tabs, Run, Stop, Cancel, menus, notices), the CandleScope tester's start screen, editor side, settings and run states, the parameters and conditions editors, and the result views (context, overview, trades, trade explanation). What they do is unchanged.

The row was split when it started (my call, like 5f5/5f6): the strategy tester has about 150 raw controls. 5g6 is the dock, the CandleScope tester and the shared result views; **5g7** is the native Pine panel's own body and report (settings, history, comparison, replay controls, advanced inputs) and `nativeStrategy.css`.

## What changed

| Area | Change |
|---|---|
| Dock | Maximize, collapse and close are kit icon buttons (maximize shows as pressed). |
| Dock header | Both strategy kinds publish kit tabs that fill the bar's height; Run is the primary kit button with its play icon (Python without the trust confirmation shows it disabled); Stop observing, Resume, Cancel and Retry save are quiet kit buttons. The CandleScope tester's ⋯ is a kit icon button opening a kit menu (在独立研究中打开, 在高级研究中打开, 专注研究 with a check when on). |
| Notices | Auto-run paused, loading, unavailable results, data preparation, needs-data, run failure (with a jump-to-line action and technical details), engine unavailable and viewing an older run are kit alerts, each kept to one row under the bar. |
| CandleScope tester | 运行模式 is a compact kit field (it was an unstyled native select at the panel's edge). The start screen's template and recent rows keep their list look; 粘贴已有代码 and 在高级研究中打开 are kit buttons; a failed restore is an alert. Problems' 跳到第 N 行 is a quiet button. The run overview's 准备数据并运行 is primary; a backend error is a danger alert with the code in a disclosure. Settings: 自动运行 is a kit checkbox with its explanation as the description; 已解析的回测条件 is a kit disclosure. No trades yet is a kit empty state. |
| Editors | Parameters are kit number fields with the source name in mono. Conditions use kit fields, selects and inputs (date and fidelity at a readable width, the five execution figures in a grid), a kit checkbox for custom execution, the four hints as a short muted list, and invalid conditions as a danger alert. |
| Results | The context bar's 可信度详情, the comparison's 完整对比, 查看并定位这笔交易 and 在高级研究中打开 are quiet kit buttons or link-buttons; stale guidance is a warning alert; 可信度详情 is a kit disclosure; 上一笔 / 下一笔 are kit buttons. |
| Trade explanation | The kit dialog (title, 决策时证据 as its description, close icon, focus trap) instead of a hand-made popover. Before, the chart's 回到实时 button showed through its backdrop. |
| Kit | `IconButton` takes a `ref` (the ⋯ menu anchors to it). |
| Styles | `strategyDock.css` and `chartStrategyTester.css` drop the rules for the replaced controls (tabs, run and dock buttons, the ⋯ details menu, notices, the explanation popover, stale guidance, advanced links, the condition inputs) and their 4 `!important`s; their element and focus rules skip kit controls, as do `nativeStrategy.css`'s until 5g7. Two already-dead rules go too. |
| Copy | No string changes. |

## Screens

The base build (Phase 5g5, `f201c4472`) and this branch, 1440 px, `zh-CN` unless marked. Market page: the tester opened from 图表策略 on BTCUSDT 1h; the CandleScope tester on its Python SMA template. Runs and other strategy writes were blocked in the capture (none was attempted: the template's auto-run is off). Strategy page: the seeded Pine draft and its completed run (ETHUSDT 1m, 175 trades); the trade explanation uses a fixture added to the first trade (the parser marks it unavailable, so the dialog shows that state).

| | Before | After |
|---|---|---|
| Market page, native Pine (脚本) | ![](assets/frontend-design-phase-5g6/native--before--dark.jpg) | ![](assets/frontend-design-phase-5g6/native--after--dark.jpg) |
| Native Pine (light) | ![](assets/frontend-design-phase-5g6/native--before--light.jpg) | ![](assets/frontend-design-phase-5g6/native--after--light.jpg) |
| Strategy switcher | ![](assets/frontend-design-phase-5g6/switcher--before--dark.jpg) | ![](assets/frontend-design-phase-5g6/switcher--after--dark.jpg) |
| CandleScope tester, start | ![](assets/frontend-design-phase-5g6/start--before--dark.jpg) | ![](assets/frontend-design-phase-5g6/start--after--dark.jpg) |
| CandleScope tester, 脚本 | ![](assets/frontend-design-phase-5g6/editor--before--dark.jpg) | ![](assets/frontend-design-phase-5g6/editor--after--dark.jpg) |
| CandleScope tester (light) | ![](assets/frontend-design-phase-5g6/editor--before--light.jpg) | ![](assets/frontend-design-phase-5g6/editor--after--light.jpg) |
| CandleScope tester, English | ![](assets/frontend-design-phase-5g6/editor-en--before--dark.jpg) | ![](assets/frontend-design-phase-5g6/editor-en--after--dark.jpg) |
| CandleScope tester, 回测条件 | ![](assets/frontend-design-phase-5g6/settings--before--dark.jpg) | ![](assets/frontend-design-phase-5g6/settings--after--dark.jpg) |
| ⋯ menu | ![](assets/frontend-design-phase-5g6/more--before--dark.jpg) | ![](assets/frontend-design-phase-5g6/more--after--dark.jpg) |
| Strategy page result | ![](assets/frontend-design-phase-5g6/result--before--dark.jpg) | ![](assets/frontend-design-phase-5g6/result--after--dark.jpg) |
| Strategy page result (light) | ![](assets/frontend-design-phase-5g6/result--before--light.jpg) | ![](assets/frontend-design-phase-5g6/result--after--light.jpg) |
| Results · 交易 | ![](assets/frontend-design-phase-5g6/trades--before--dark.jpg) | ![](assets/frontend-design-phase-5g6/trades--after--dark.jpg) |
| Trade explanation | ![](assets/frontend-design-phase-5g6/explain--before--dark.jpg) | ![](assets/frontend-design-phase-5g6/explain--after--dark.jpg) |
| Trade explanation (light) | ![](assets/frontend-design-phase-5g6/explain--before--light.jpg) | ![](assets/frontend-design-phase-5g6/explain--after--light.jpg) |
| Strategy page, 回测条件 | ![](assets/frontend-design-phase-5g6/cond--before--dark.jpg) | ![](assets/frontend-design-phase-5g6/cond--after--dark.jpg) |

## Verification

**In the running app** (headless, 1440 px): on the market page the dock opened in native Pine mode, its tabs switched views, the switcher listed the strategies and switched to the CandleScope tester; its start screen attached the Python template; 脚本, 回测条件 and the ⋯ menu opened; the auto-run notice showed as one row. On the strategy page the run's overview and 交易 rendered, a trade row opened the explanation dialog, and the conditions editor showed its custom-execution fields. Nothing that changes data was run: no backtest, native run, preparation or comparison save.

**Tests:** the backtest (chart tester, native, research), strategy-research, research-data, kit, chart-workspace, app and app-control tests pass (804). No test needed changing: the tester keeps its hooks (`data-chart-strategy-panel`, `chart-strategy-run-button` on the kit Run button — now listed as a test hook in the style metrics — `chart-strategy-stop-observing`, `data-auto-run-pause`, `chart-strategy-run-overview`, `chart-strategy-quick-settings`, `trade-explanation-popover` inside the dialog, `chart-strategy-result-context`, `chart-strategy-trades`, `strategy-language`, `strategy-python-confirm`), and the tab tests read the kit tabs' `role="tab"` labels.

**Style metrics** (against 5g5): class names with no CSS rule 0 (unchanged), raw `<button>` 446 → 410, `<Button>` uses 311 → 338, button class families 39 → 34, `!important` 34 → 30.

**Full check:** `npm run check` passes: 5,165 frontend tests, 137 desktop tests, lint (one existing warning), the i18n, style and architecture checks, both typechecks and the build.

## Known gaps

- **5g7:** the native Pine panel's body and report (settings, history list, report sections, comparison, replay controls, advanced inputs, workbench account settings) still use their own raw controls and `nativeStrategy.css`.
- **The strategy switcher** keeps its own menu (strategies with a status dot and meta, then actions): the kit menu has no radio items or two-line rows.
- **Copy (Phase 6):** explanation states as codes (`UNAVAILABLE`, `FILLED`), "CandleScope 撮合 / 教学模板" as the strategy name, trade ids like `trade-1`.
- **Desktop app:** not tested.
