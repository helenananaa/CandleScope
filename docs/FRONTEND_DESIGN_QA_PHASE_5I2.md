# Frontend design refactor: Phase 5i2 QA (the trading and read-only account docks on the kit)

- Date: 2026-11-15
- Branch: `design/phase-5i2-accounts`, based on `design/phase-5i-docks` (PR #430)
- Plan: [`frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md`](../frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md), the Phase 5 rows. Contract: [`DESIGN.md`](../DESIGN.md)
- **Intended visible change:** the market rail's 交易账户 and 只读账户 docks, and everything they open (add account, the trade journal, quick replay, the chart's 交易与笔记 menu), use kit controls on tokens. The history study overlay shares quick replay's frame and its buttons, so it moves too. What they do is unchanged.

## What changed

| Area | Change |
|---|---|
| Trading panel | The account picker is a kit select, 添加账户 and close are kit icon buttons. The mode is a badge; a feed catching up and errors are compact kit alerts (the error keeps its 关闭提示 action). 下单 / 持仓 / 历史 / 日志 / 统计 are kit tabs sized for the rail (all five fit in English too), with the open-position count as a tab badge and a dot for trades to review. No account and the unavailable service are kit empty states. |
| Rows | Positions, working orders, history and journal rows keep their layout; long and short are badges in the chart's up and down colours (which the user can swap), other tags are kit badges, and 笔记 / 复盘 / 市价平仓 / 取消 are small quiet buttons at the height of the links they replace. A closed trade or journal entry still opens as a whole row. |
| Order ticket | Buy / sell and market / limit / stop are kit segmented controls (the chosen side fills with the up or down colour, as does the submit button); quantity, prices, stop-loss and take-profit are kit fields; 只减仓 is a kit checkbox; the result is a success or danger alert. The manual fill form matches, and its date and time get their own line in a narrow rail instead of being cut off. |
| Add account | The kit dialog (title, close icon, focus trap, footer with 取消 and the primary 创建). The four account kinds stay choice cards (title, two lines, a 规划中 badge); the name and practice settings are kit fields. |
| Trade journal | The kit drawer: the title, the save state and 保存 in its header, then the stage badge and instrument. The four template sections are kit disclosures; text and price fields are kit fields (a hindsight badge on the label), 市场环境 and 是否遵守计划 are pressed toggle buttons (a second click still clears the choice). The locked plan is an info alert (amber once the risk fields are edited); plan suggestions, 快速复盘, capture and copy are kit buttons; the read-only source is a disclosure; quick notes take a kit input. |
| Stats | The period is a kit segmented control, the tag filter a removable kit button; figures are kit stats in tiles (gains and losses in the up and down colours, 样本少 as a warning badge); tags in the breakdown table are quiet buttons; errors are alerts. |
| Quick replay | The badge, 返回实时（Esc） and the transport (回看形态, 上一事件, ◀, ▶, 4× pressed while fast, ▶\|, 下一事件, the step select) are kit controls; a load failure is one alert with 重试加载 as its action, over the chart's corner; 提前显示最终结果 is a kit checkbox and the review note a kit input. |
| History study | The same frame: its banner badge, 保存并返回实时 and the playback controls are kit buttons, the cursor a kit input, errors kit alerts; the note editor uses a kit text area and buttons. The chart cell's loading and recovery masks use kit buttons too. |
| Chart menu | 交易与笔记 is a small kit button opening a kit popover (Escape, outside click and focus return come from the overlay stack instead of the menu's own listeners): the account as a kit select, the three overlays as kit checkboxes, the note filters as kit selects (shared with the replay page's layout menu), 关闭 as a quiet button. |
| Read-only account | The close is a kit icon button, the sync state a toned badge with the UID in mono. 更换凭证 / 接入只读密钥, 同步 / 重试 and 暂停同步 are kit buttons; the credentials are kit password fields in a bordered form with 断开并移除凭证 as a danger button. The seven views are pressed toggle buttons that wrap (kit tabs would scroll out of sight in the rail). Coverage, review coverage and exclusions are kit disclosures; errors and stream problems are alerts with their code in mono; reconciliation states are toned badges. The journal uses kit fields, a select and a text area, and each saved note is a disclosure. Browser users see the desktop-only message as a kit empty state. |
| Styles | `tradingAccounts.css` (628 → 381 lines) and `readonlyAccount.css` drop every rule for the replaced controls, including the element rules for all buttons, inputs and selects inside the read-only dock; `.trading-button`, which the history study and the chart cell borrowed, is gone. Both files and `chartAccountOverlay.css` now load with the global stylesheet instead of from lazy components. |
| Copy | No string changes. |

## Screens

The base build (Phase 5i, `65e1a157a`) and this branch, 1440 × 900, `zh-CN` unless marked, market page on BTCUSDT 1h. No trading account exists locally and creating one would write to the local store, so the captures serve fixture data to the page's own GET requests: a practice account (one open BTCUSDT position with stop-loss and take-profit orders, three closed trades, a plan, a trade note and a review note, an ETHUSDT feed catching up) and a manual account; and, for the read-only dock, an OKX account (a position, an order, a balance, fills, bills, a two-version journal note, a reconciliation report and one reviewed trade) behind a capture-only desktop session. Every write was refused in the capture and none was attempted. Quick replay asks the backend to prepare history, which is a write, so both builds show its "still preparing" state.

| | Before | After |
|---|---|---|
| 交易账户 · 下单 | ![](assets/frontend-design-phase-5i2/panel--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/panel--after--dark.jpg) |
| 下单 (light) | ![](assets/frontend-design-phase-5i2/panel--before--light.jpg) | ![](assets/frontend-design-phase-5i2/panel--after--light.jpg) |
| 下单, English | ![](assets/frontend-design-phase-5i2/panel-en--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/panel-en--after--dark.jpg) |
| 持仓 | ![](assets/frontend-design-phase-5i2/positions--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/positions--after--dark.jpg) |
| 历史 | ![](assets/frontend-design-phase-5i2/history--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/history--after--dark.jpg) |
| 日志 | ![](assets/frontend-design-phase-5i2/journal--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/journal--after--dark.jpg) |
| 统计 | ![](assets/frontend-design-phase-5i2/stats--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/stats--after--dark.jpg) |
| 统计 (light) | ![](assets/frontend-design-phase-5i2/stats--before--light.jpg) | ![](assets/frontend-design-phase-5i2/stats--after--light.jpg) |
| Manual account | ![](assets/frontend-design-phase-5i2/manual--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/manual--after--dark.jpg) |
| 添加账户 | ![](assets/frontend-design-phase-5i2/add--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/add--after--dark.jpg) |
| 添加账户 (light) | ![](assets/frontend-design-phase-5i2/add--before--light.jpg) | ![](assets/frontend-design-phase-5i2/add--after--light.jpg) |
| Trade journal, closed trade with a plan | ![](assets/frontend-design-phase-5i2/drawer--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/drawer--after--dark.jpg) |
| Trade journal (light) | ![](assets/frontend-design-phase-5i2/drawer--before--light.jpg) | ![](assets/frontend-design-phase-5i2/drawer--after--light.jpg) |
| Trade journal, plan suggestion | ![](assets/frontend-design-phase-5i2/drawer2--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/drawer2--after--dark.jpg) |
| Trade journal, quick notes and snapshots | ![](assets/frontend-design-phase-5i2/drawer2end--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/drawer2end--after--dark.jpg) |
| Trade plan | ![](assets/frontend-design-phase-5i2/plan--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/plan--after--dark.jpg) |
| Quick replay | ![](assets/frontend-design-phase-5i2/replay--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/replay--after--dark.jpg) |
| 交易与笔记 menu | ![](assets/frontend-design-phase-5i2/overlay--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/overlay--after--dark.jpg) |
| 只读账户 · 概览 | ![](assets/frontend-design-phase-5i2/ro--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/ro--after--dark.jpg) |
| 概览 (light) | ![](assets/frontend-design-phase-5i2/ro--before--light.jpg) | ![](assets/frontend-design-phase-5i2/ro--after--light.jpg) |
| 概览, English | ![](assets/frontend-design-phase-5i2/ro-en--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/ro-en--after--dark.jpg) |
| 更换凭证 | ![](assets/frontend-design-phase-5i2/roconnect--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/roconnect--after--dark.jpg) |
| 成交 | ![](assets/frontend-design-phase-5i2/rofills--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/rofills--after--dark.jpg) |
| 资金流水 | ![](assets/frontend-design-phase-5i2/robills--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/robills--after--dark.jpg) |
| 对账 | ![](assets/frontend-design-phase-5i2/roreconcile--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/roreconcile--after--dark.jpg) |
| 对账, positions | ![](assets/frontend-design-phase-5i2/roreconcileend--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/roreconcileend--after--dark.jpg) |
| 交易复盘 | ![](assets/frontend-design-phase-5i2/rotradesend--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/rotradesend--after--dark.jpg) |
| 交易日志 | ![](assets/frontend-design-phase-5i2/rojournal--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/rojournal--after--dark.jpg) |
| 交易日志, saved note | ![](assets/frontend-design-phase-5i2/rojournalend--before--dark.jpg) | ![](assets/frontend-design-phase-5i2/rojournalend--after--dark.jpg) |

## Verification

**In the running app** (headless, 1440 px): with the fixtures, the trading panel switched accounts and tabs, the ticket and the manual form rendered, 添加账户 opened its dialog, a closed trade and a plan opened the journal drawer (sections open by stage, the suggestion and quick notes shown), 复盘 opened quick replay, and the chart's 交易与笔记 opened its popover. The read-only dock showed its overview, the credentials form, fills, bills, reconciliation, the trade review and the journal. Nothing that changes data was run: no account, order, fill, note, snapshot, sync or credential.

**Tests:** the trading-accounts, read-only accounts, history study, app, kit, chart-workspace, replay and app-control tests pass (1,189). No test needed changing. The browser harnesses keep their hooks: `.chart-account-overlay-menu select` and its checkboxes (now in the kit popover), `.quick-replay-step select`, `data-replay-cursor-sec`.

**Style metrics** (against 5i): class names with no CSS rule 0 (unchanged), raw `<button>` 350 → 270, `<Button>` uses 374 → 441, button class families 31 → 29, inline `style={{}}` 91 → 89, `!important` 30 (unchanged).

**Full check:** `npm run check` passes: 5,165 frontend tests, 137 desktop tests, lint (one existing warning), the i18n, style, CSS layer and architecture checks, both typechecks and the build.

## Known gaps

- **Kept as plain buttons on purpose:** the trading rows that open a closed trade or a journal entry (two or three lines each) and the four account-kind cards.
- **Not captured:** the history study overlay (starting a study writes to the local store) and the replay page's layout menu, which shares the note filters; their buttons and selects are covered by the history-study, replay and chart-workspace tests.
- **Copy (Phase 6):** fact kinds as codes in the coverage lines (`fills`, `bills`), exchange identifiers in the read-only views (position, bill and fill ids), and `binance spot` in the journal's instrument line.
- **Desktop app:** not tested (the read-only dock only works there; the captures fake its session).
