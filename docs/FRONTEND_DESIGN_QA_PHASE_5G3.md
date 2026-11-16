# Frontend design refactor: Phase 5g3 QA (the research tools on the kit)

- Date: 2026-11-15
- Branch: `design/phase-5g3-research-tools`, based on `design/phase-5g2-research-modes` (PR #419)
- Plan: [`frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md`](../frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md) §6.1 and the Phase 5 rows. Contract: [`DESIGN.md`](../DESIGN.md#pages-with-modes)
- **Intended visible change:** the five research tools (成交验证, 参数稳健, 模型测试, 多市场, 交易复盘) use kit controls on tokens: their header, side panels, results and the Python studio. What they do is unchanged.

## What changed

| Area | Change |
|---|---|
| Header | The chart source (实时参考 / 冻结快照 / Run 结果) is a kit segmented control; a disabled source still says why in its tooltip (the kit's choice options gained a `title`). 刷新权威对象 is an icon button; 返回来源图表 a quiet link-button. The "高级模式" chip is gone; 只读 shows as a badge only when the tools are read-only. |
| Panels | Each panel is a section with a plain heading (策略, 数据, 执行, Run, Study, 结果) and the object it shows under it in mono, instead of a cyan uppercase eyebrow over a bold title. Fields are kit fields (selects, inputs, JSON text areas in mono); buttons are kit buttons with the creating step primary (校验并创建 Run, 创建草稿, 显式启动, 编译 revision); details are kit disclosures. |
| Lists and states | Run and study lists are rows with the state as a toned badge (COMPLETED green, FAILED red, running blue), the open one with an accent edge. States in facts (Run 状态, bridge state, ON/OFF flags) are badges. Operation errors and notices are alerts. |
| Evidence | Raw JSON readouts (snapshot quality, review bridge, study authority) sit in closed 技术详情 disclosures. |
| Results | The four figures are kit stats (realized P&L green or red). SUMMARY / TRADES / TRACE / COMPARE / QUALITY are kit tabs named 概览, 交易, 信号轨迹, 对比, 数据质量; the trades table has a sticky header and tinted P&L. An empty results panel no longer repeats its message as its title. |
| Python studio | The template, file imports, manifest preview, inspect / freeze / smoke buttons, the runtime choice (a radio list, since each option is a sentence) and the trusted-local confirmation use kit fields, checkboxes and buttons; coverage is a badge; a smoke failure is a danger alert. Its test hooks are kept. |
| Status page | Loading and errors are a kit `EmptyState` with 重试 and 返回行情, on the page background instead of a cyan gradient with an eyebrow. |
| Strategy page | The quick test's external model form (`ResearchExternalModel`) used the same field and button rules, so it moved onto kit fields and buttons too. |
| Styles | `backtestResearch.css` is rewritten on tokens (512 lines including the 5g2 rail). `backtest.css` (983 lines) is deleted: it was loaded only by `backtest.html`, its rules styled the retired backtest workbench, and the few still matching anything (the equity curve's empty line, an unused chart component) never applied on `strategy.html`. The unused `BacktestResultChart` component goes with it; the equity curve's empty line gets a rule in the chart tester's stylesheet. |
| Copy | 5 new strings in all 30 languages (the result tabs); 2 keys nothing uses any more are gone (the status page's eyebrow and "高级模式"). |

## Screens

The base build (Phase 5g2, `8650929e9`) and this branch, 1440 px, `zh-CN` unless marked. "On a run" uses a local completed run (ETHUSDT 1m, 175 trades). The Python studio is off by default; its row was captured with `VITE_BACKTEST_PYTHON_STRATEGY_ENABLED=1` on both builds.

| | Before | After |
|---|---|---|
| 成交验证 | ![](assets/frontend-design-phase-5g3/precise--before--dark.jpg) | ![](assets/frontend-design-phase-5g3/precise--after--dark.jpg) |
| 成交验证 (light) | ![](assets/frontend-design-phase-5g3/precise--before--light.jpg) | ![](assets/frontend-design-phase-5g3/precise--after--light.jpg) |
| 成交验证, English | ![](assets/frontend-design-phase-5g3/precise-en--before--dark.jpg) | ![](assets/frontend-design-phase-5g3/precise-en--after--dark.jpg) |
| 成交验证 on a run | ![](assets/frontend-design-phase-5g3/run--before--dark.jpg) | ![](assets/frontend-design-phase-5g3/run--after--dark.jpg) |
| 成交验证 on a run (light) | ![](assets/frontend-design-phase-5g3/run--before--light.jpg) | ![](assets/frontend-design-phase-5g3/run--after--light.jpg) |
| Results · 交易 | ![](assets/frontend-design-phase-5g3/trades--before--dark.jpg) | ![](assets/frontend-design-phase-5g3/trades--after--dark.jpg) |
| 参数稳健 | ![](assets/frontend-design-phase-5g3/robust--before--dark.jpg) | ![](assets/frontend-design-phase-5g3/robust--after--dark.jpg) |
| 模型测试 | ![](assets/frontend-design-phase-5g3/python--before--dark.jpg) | ![](assets/frontend-design-phase-5g3/python--after--dark.jpg) |
| Python studio (flag on) | ![](assets/frontend-design-phase-5g3/studio--before--dark.jpg) | ![](assets/frontend-design-phase-5g3/studio--after--dark.jpg) |
| 多市场 | ![](assets/frontend-design-phase-5g3/multi--before--dark.jpg) | ![](assets/frontend-design-phase-5g3/multi--after--dark.jpg) |
| 交易复盘 on a run | ![](assets/frontend-design-phase-5g3/replay--before--dark.jpg) | ![](assets/frontend-design-phase-5g3/replay--after--dark.jpg) |

## Verification

**In the running app** (headless, 1440 px): each tool opened from `?mode=`; on the local run the results showed the four figures and the 交易 tab its table; the Python studio rendered with the flag on (template, imports, buttons, runtime choice, coverage). Nothing that changes data was run: creating runs, studies, revisions, review bridges or external connections, smoke runs, or Python bundle inspection.

**Tests:** the strategy-research, backtest, research-data and app-control tests pass (436), and so does `scripts/strategy-research-smoke.mjs`. `ResearchResultsPanel.test` now looks for the kit's closed disclosure and the tab list instead of a bare `<details>`; `backtestM9Contracts` checks the bounded equity curve where it is used (the chart tester's result view) instead of in the removed component. The Python studio's test hooks (`python-strategy-studio`, `python-template-create`, `python-import-zip`, `python-import-directory`, `python-trusted-facts`, `python-coverage`, `python-host-owns-report`) are kept.

**Style metrics** (against 5g2): class names with no CSS rule 0 (unchanged), raw `<button>` 542 → 502, `<Button>` uses 228 → 263.

**Full check:** `npm run check` passes: 5,165 frontend tests, 137 desktop tests, lint (one existing warning), the i18n and architecture checks, both typechecks and the build.

## Known gaps

- **Copy (Phase 6):** the tools still speak in internal terms: `BAR_APPROX`, "BacktestRun", "Study V2", "Phase 11", "revision", "smoke", "runtime receipt", "独立研究 runtime" and "仅使用权威 ID" in the status bar, JSON field names in the drafts; run and study states are codes. Times in the trades table and range fields are epoch milliseconds.
- **The run and study drafts are still JSON** in a text area; turning them into forms is a product change.
- **Not exercised:** every action that creates or changes data (listed above), the review bridge, external model connections.
- **Desktop app:** not tested.
