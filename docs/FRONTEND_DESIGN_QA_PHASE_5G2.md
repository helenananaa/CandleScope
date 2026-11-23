# Frontend design refactor: Phase 5g2 QA (strategy research modes)

- Date: 2026-11-15
- Branch: `design/phase-5g2-research-modes`, based on `design/phase-5g-strategy-research` (PR #418)
- Plan: [`frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md`](../frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md) §6.1 and the Phase 5 rows. Contract: [`DESIGN.md`](../DESIGN.md#pages-with-modes)
- **Intended visible change:** strategy research and backtest become one page. A mode rail at the left edge switches between 快速测试 and the five research tools; the five-card landing page is gone; the old URLs open the same page in the matching mode. The tools themselves look as before (their restyle is 5g3).

## What changed

| Area | Change |
|---|---|
| Mode rail | A 72 px rail at the left edge of `strategy.html`, under the header, like the market page's activity bar: 快速测试, a divider, then 成交验证, 参数稳健, 模型测试, 多市场, 交易复盘. Each item is an icon with a two-line label; its tooltip gives the tool's full name and what it checks. The current mode is tinted with an accent edge (`aria-current="page"`). |
| Modes in the URL | `?mode=quick|precise|robust|python|multi|replay`. Switching rewrites the address without reloading, keeping a tool's run, study or context link. The app-control `research-panels` group gains a `mode` command. |
| No landing page | The five-card page (先选研究问题，再打开对应控制, 01–05) and the 研究任务 button that returned to it are gone; the rail is the overview. A tool opened without a chosen task (a bare link) opens 成交验证. |
| Carrying the work | Leaving 快速测试 with a data source and strategy draft creates a launch context from them (and the latest result), so the tool opens on the same work, as the old 高级研究 button did, without leaving the page. With nothing to carry, the tool opens with its own defaults instead of refusing: the "先选择数据" and "先保存草稿" errors are gone. The script panel's and result panel's 高级研究 buttons now switch to 成交验证 the same way. Going back to 快速测试 shows it as it was left. |
| Old URLs | `backtest.html` rewrites itself to `strategy.html?mode=precise` (or `robust` for a study link; a launch context picks its own tool), keeping `run`, `compare`, `study` and `context`; `local.html` to `strategy.html?source=imported`. The one-time compatibility notice still shows. Every URL carries the 策略研究 title. |
| Links | Links the app builds now point at the page and mode directly: the chart tester's 高级研究 link and research hand-off, the result views' run and comparison links, and the data preparation log's 打开结果 (`/strategy.html?mode=precise&run=…`). |
| Layout | Each view's interval bar sits beside the rail with its workspace, so the rail starts under the header in every mode. |
| Copy | 8 new strings in all 30 languages (the rail and its labels); 10 keys nothing uses any more are gone (the landing page's, the 研究任务 button's, the two refusals, and the per-URL page titles). |

## Screens

The base build (Phase 5g, `c69b4ae7e`) and this branch, 1440 px, `zh-CN` unless marked.

| | Before | After |
|---|---|---|
| `strategy.html` (快速测试) | ![](assets/frontend-design-phase-5g2/strategy--before--dark.jpg) | ![](assets/frontend-design-phase-5g2/strategy--after--dark.jpg) |
| `strategy.html` (light) | ![](assets/frontend-design-phase-5g2/strategy--before--light.jpg) | ![](assets/frontend-design-phase-5g2/strategy--after--light.jpg) |
| `strategy.html`, English (the rail labels) | (not captured) | ![](assets/frontend-design-phase-5g2/strategy-en--after--dark.jpg) |
| 快速测试 on imported data | ![](assets/frontend-design-phase-5g2/imported--before--dark.jpg) | ![](assets/frontend-design-phase-5g2/imported--after--dark.jpg) |
| `backtest.html` (before: the landing page; after: 成交验证) | ![](assets/frontend-design-phase-5g2/backtest--before--dark.jpg) | ![](assets/frontend-design-phase-5g2/backtest--after--dark.jpg) |
| `backtest.html` (light) | ![](assets/frontend-design-phase-5g2/backtest--before--light.jpg) | ![](assets/frontend-design-phase-5g2/backtest--after--light.jpg) |
| `backtest.html`, English | ![](assets/frontend-design-phase-5g2/backtest-en--before--dark.jpg) | ![](assets/frontend-design-phase-5g2/backtest-en--after--dark.jpg) |
| 成交验证 (before: picked from the landing page; after: `?mode=precise`) | ![](assets/frontend-design-phase-5g2/precise--before--dark.jpg) | ![](assets/frontend-design-phase-5g2/precise--after--dark.jpg) |
| 成交验证 (light) | ![](assets/frontend-design-phase-5g2/precise--before--light.jpg) | ![](assets/frontend-design-phase-5g2/precise--after--light.jpg) |
| 参数稳健 | ![](assets/frontend-design-phase-5g2/robust--before--dark.jpg) | ![](assets/frontend-design-phase-5g2/robust--after--dark.jpg) |

## Verification

**In the running app** (headless, 1440 px):
- On `strategy.html`, the rail opened 参数稳健 (`?mode=robust`, the tool's panels shown), then 交易复盘 (`?mode=replay`), then 快速测试 again (`?mode=quick`, the quick view as it was). The rail's buttons take keyboard focus.
- `backtest.html?run=<a local run>` became `strategy.html?mode=precise&run=…` with 成交验证 open on that run; `backtest.html` became `strategy.html?mode=precise`; `local.html` became `strategy.html?source=imported` in 快速测试; `strategy.html?mode=multi` opened 多市场. The compatibility notice showed on the old URLs, and every page had the 策略研究 title.
- Not run: carrying a source and draft into a tool, because it creates a launch context on the backend; the path is the one the old 高级研究 button used, now without leaving the page.

**Tests:** the strategy-research, research-data, backtest, data-preparation and app-control tests pass (450), and so does `scripts/strategy-research-smoke.mjs`. New tests cover the mode a URL opens in (`?mode=`, compatibility URLs, run, study and context links) and the rewrite of `backtest.html` and `local.html`. Updated tests: the task-home test now checks the mode ↔ task mapping, links and that the picker is gone; the result-view and tester tests expect `strategy.html?mode=precise` links; the navigation test checks that the app hosts the tools as modes, carries its context with `createStrategyResearchContextSearch`, and no longer navigates away or refuses.

**Style metrics** (against 5g): class names with no CSS rule 0 (unchanged), raw `<button>` 543 → 542, button class families 40 → 39.

**Full check:** `npm run check` passes: 5,165 frontend tests, 137 desktop tests, lint (one existing warning), the i18n and architecture checks, both typechecks and the build. The rail was widened from 60 to 72 px afterwards (so labels such as "Parameters" and "Paraméterek" stay whole); the stylesheet and cascade-layer checks were run again on that.

## Known gaps

- **The tools still look as before** (their own header with 实时参考 / 冻结快照 / Run 结果, the JSON panels, internal terms such as `BAR_APPROX`, "Bundle", "runtime receipt"): 5g3.
- **Going back from a tool to 快速测试** does not bring a Run created in the tool along; the tool keeps its own run history.
- **Mode switches replace the history entry** instead of adding one, so the browser's Back button leaves the page rather than returning to the previous mode.
- **Desktop app:** not tested.
