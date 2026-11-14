# Frontend design refactor: Phase 5g4 QA (the strategy page on the kit)

- Date: 2026-11-15
- Branch: `design/phase-5g4-strategy-page`, based on `design/phase-5g3-research-tools` (PR #421)
- Plan: [`frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md`](../frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md) §6.1 and the Phase 5 rows. Contract: [`DESIGN.md`](../DESIGN.md#pages-with-modes)
- **Intended visible change:** the strategy page's own pieces (快速测试) use kit controls on tokens: first open, the script panel, results, run history and comparison, batch sources, the result replay, and the dialog that hands a research run back to a market chart. What they do is unchanged.

## What changed

| Area | Change |
|---|---|
| First open | A plain heading and lead instead of a cyan eyebrow over a 28 px title. The two templates are cards on tokens (language in mono, the chosen one with an accent edge). 前往行情图表 and 打开本地资料库 sit together as buttons on the right, beside the sentence that explains them. |
| Script rail | Pine 完整策略 / CandleScope 撮合 is a kit segmented control. The script panel has a heading, the recent scripts as a kit select, the templates as full-width buttons, 策略参数 / 脚本 / 回测条件 as kit tabs, 运行 as the primary button and 高级研究 as a quiet one under it. Batch data sources and 外部策略 / 模型 are kit disclosures; the batch's datasets are kit checkboxes and its submit is a primary button. With no script yet the panel no longer stretches, so the disclosures follow the templates. |
| Results | 概览 / 交易 are kit tabs with 快速估算 as a badge and 回放 as a small button on the same row; 将当前选定版本挂回图表 is a kit button. Errors are danger alerts. With no run yet the panel is a heading and a line, with 快速估算 as a badge. The network guard is a kit disclosure. |
| Run history | The drawer is the kit drawer (title, close icon). Runs are rows with the state as a toned badge, the open run with an accent edge, and 查看结果 / 比较结果 as small buttons. The comparison picker is two kit selects and a primary button in a bordered section. Incompatible runs show a warning alert with the differing fields; the tables use run ids as column heads (the full label is the tooltip) instead of a label too wide for the drawer. Batch jobs and market inputs use the same rows. Saved accounts open in a kit drawer too. |
| Result replay | Transport buttons, the target bar, interval, comparison source, moving-average selects and 在新图表打开 are kit controls in one bordered bar; the link options are kit checkboxes; each chart's 图表样式 is a kit disclosure with kit select and checkboxes; balance, position and equity are kit stats; notes use kit buttons and text area; fills, signals and orders are kit disclosures with mono lists. |
| Return to a chart | The dialog on the market page that applies a research run to a chart is the kit dialog (title, description, close icon, footer with the primary action), with the run as a kit section and kit selects. Before, the native `<dialog>` rendered unstyled in the page's top-left corner. |
| Old URLs | The compatibility notice on `backtest.html` and `local.html` is a kit alert with its link and dismiss as quiet buttons. |
| Styles | `strategyResearch.css` is rewritten on tokens for the strategy page; the library and import rules are kept as they are for 5g5. The element rules that styled raw buttons across the page now skip kit segments and tabs, no longer reach the first-open cards, and no longer recolour kit link-buttons. `researchReturn.css` (loaded late with the dialog) is deleted. The mode-switch rules in `nativeStrategy.css` are gone with the switch's raw buttons. |
| Copy | No new strings; 1 key nothing uses any more is gone (the first-open eyebrow, 开始一个图表脚本快测). |

## Screens

The base build (Phase 5g3, `968b2564f`) and this branch, 1440 px, `zh-CN` unless marked. The page is opened on a local imported dataset (binance spot ETHUSDT 1m) with a saved Pine draft and its completed run (175 trades), seeded in the headless browser's storage. The result replay and the return dialog use fixture responses for their GET requests: no local run qualifies for either (the replay needs a spot cash run on local data; the return needs a Python run).

| | Before | After |
|---|---|---|
| First open | ![](assets/frontend-design-phase-5g4/first--before--dark.jpg) | ![](assets/frontend-design-phase-5g4/first--after--dark.jpg) |
| First open (light) | ![](assets/frontend-design-phase-5g4/first--before--light.jpg) | ![](assets/frontend-design-phase-5g4/first--after--light.jpg) |
| First open, English | ![](assets/frontend-design-phase-5g4/first-en--before--dark.jpg) | ![](assets/frontend-design-phase-5g4/first-en--after--dark.jpg) |
| No script yet (templates) | ![](assets/frontend-design-phase-5g4/templates--before--dark.jpg) | ![](assets/frontend-design-phase-5g4/templates--after--dark.jpg) |
| Script and result | ![](assets/frontend-design-phase-5g4/script--before--dark.jpg) | ![](assets/frontend-design-phase-5g4/script--after--dark.jpg) |
| Script and result (light) | ![](assets/frontend-design-phase-5g4/script--before--light.jpg) | ![](assets/frontend-design-phase-5g4/script--after--light.jpg) |
| Script and result, English | ![](assets/frontend-design-phase-5g4/script-en--before--dark.jpg) | ![](assets/frontend-design-phase-5g4/script-en--after--dark.jpg) |
| 脚本 tab | ![](assets/frontend-design-phase-5g4/script-code--before--dark.jpg) | ![](assets/frontend-design-phase-5g4/script-code--after--dark.jpg) |
| Results · 交易 | ![](assets/frontend-design-phase-5g4/trades--before--dark.jpg) | ![](assets/frontend-design-phase-5g4/trades--after--dark.jpg) |
| Run history | ![](assets/frontend-design-phase-5g4/history--before--dark.jpg) | ![](assets/frontend-design-phase-5g4/history--after--dark.jpg) |
| Run history (light) | ![](assets/frontend-design-phase-5g4/history--before--light.jpg) | ![](assets/frontend-design-phase-5g4/history--after--light.jpg) |
| Comparing two runs | ![](assets/frontend-design-phase-5g4/compare--before--dark.jpg) | ![](assets/frontend-design-phase-5g4/compare--after--dark.jpg) |
| Result replay (fixture) | ![](assets/frontend-design-phase-5g4/replay--before--dark.jpg) | ![](assets/frontend-design-phase-5g4/replay--after--dark.jpg) |
| Result replay (light) | ![](assets/frontend-design-phase-5g4/replay--before--light.jpg) | ![](assets/frontend-design-phase-5g4/replay--after--light.jpg) |
| Return to a chart, market page (fixture) | ![](assets/frontend-design-phase-5g4/return--before--dark.jpg) | ![](assets/frontend-design-phase-5g4/return--after--dark.jpg) |
| Return to a chart (light) | ![](assets/frontend-design-phase-5g4/return--before--light.jpg) | ![](assets/frontend-design-phase-5g4/return--after--light.jpg) |

## Verification

**In the running app** (headless, 1440 px): first open with no data; the imported dataset with no script (templates) and with the seeded draft (the three script tabs); the completed run's 概览 and 交易; run history with two runs, a comparison of them (GET); the result replay at bar 120 with a 5m comparison chart, a moving average, a note and fills; the return dialog on the market page with its workspace and chart selects. Nothing that changes data was run: no run, batch, note, external model, return to a chart, or library change. Replay note saves were blocked in the capture.

**Tests:** the strategy-research, backtest, research-data, local-data, app-control and app tests pass (527), and so does `scripts/strategy-research-smoke.mjs`. No test needed changing: the test hooks are kept (`strategy-research-run`, `strategy-research-templates`, `strategy-research-template-*`, `strategy-research-open-advanced`, `strategy-research-bar-only*`, `strategy-research-network-guard`, `strategy-history-comparison`, `research-batch-jobs`, `research-market-inputs`, the `strategy-replay-*` hooks and `data-*` attributes).

**Style metrics** (against 5g3): class names with no CSS rule 0 (unchanged), raw `<button>` 502 → 454, `<Button>` uses 263 → 305.

**Full check:** `npm run check` passes: 5,165 frontend tests, 137 desktop tests, lint (one existing warning), the i18n, style and architecture checks, both typechecks and the build.

## Known gaps

- **The strategy tester is shared with the market page and keeps its own styles:** the language select and Python permission box, the parameters and conditions editors, the result context bar and overview, the trade list and its explanation, and the native Pine panel and report. They are restyled once, for both pages, in a new row (5g6). The page's element rules still style their raw buttons until then.
- **Imported data (5g5):** the interval strip, the event markers panel, the empty imported chart and the data library drawer are unchanged.
- **Copy (Phase 6):** "快速估算" for bar estimates, run states as codes (`COMPLETED`), run ids in the history, the batch's internal labels, ISO times in the result replay.
- **The result replay's own chart** (the SVG candles) keeps its fixed marker and moving-average colours.
- **Desktop app:** not tested.
