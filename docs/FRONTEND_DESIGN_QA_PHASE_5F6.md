# Frontend design refactor: Phase 5f6 QA (replay order ticket and account view)

- Date: 2026-11-15
- Branch: `design/phase-5f6-replay-trading`, based on `design/phase-5f5-replay-rail` (PR #414)
- Plan: [`frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md`](../frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md) §2.4, §2.5, §2.6 and the Phase 5 rows. Contract: [`DESIGN.md`](../DESIGN.md#rail-views)
- **Intended visible change:** the replay rail's 下单 (order ticket) and 仓位 (account) views use kit controls on tokens, and the legacy rail stylesheet behind them is removed. What the ticket and the account view do, and every order rule, is unchanged.

This completes the replay row of Phase 5 (5f to 5f6).

## What changed

| Area | Change |
|---|---|
| 下单: header | The symbol, market type and margin mode on one line with leverage as a small kit select; equity and available as kit stats; an open position as a 多 / 空 badge with its size and floating P&L. |
| 下单: order | 开仓 / 平仓 is a kit segmented control; the order type is kit tabs whose panel holds the price and size fields. Fields are kit inputs with their unit inside (USDT, %, x); the size unit is a kit select beside the size. 25 % to 100 % are small buttons under the slider. The preview figures are a label/value list in mono. |
| 下单: risk plan | 按风险计划反算 is a kit checkbox that opens its fields in a quiet panel: risk mode, risk, invalidation and target price (two columns), the reason as a kit text area with its hint. Before, the fields had an oversized "风险口径" label and a browser select. |
| 下单: submit | 开多 / 开空 keep the user's candle colours (now from `--text-up` / `--text-down` directly) and stay tinted when disabled. The order feedback line under them is toned (error red, success green). |
| 仓位: summary and tabs | Equity (with its asset in the label), available and floating P&L are kit stats; the six record tabs are kit tabs with counts, sized to fit the rail in Chinese. |
| 仓位: positions | A position is one card: the symbol with 多 / 空, 全仓 / 逐仓 and leverage as badges, P&L on the right, its figures as label-over-value tiles three across (before: three columns of large mono figures), then 止盈止损, 平仓 and 市价全平 (danger) as kit buttons. The close, leverage and protection forms are kit fields with units; 更多操作 and 最近已平仓 are kit disclosures. No positions is an `EmptyState`. |
| 仓位: orders, fills | Rows separated by dividers: symbol (with a kit checkbox when the order can be cancelled), side, type and margin as badges, status as a toned badge, the figures as tiles, 改单 and 撤单 (danger) as small buttons. Empty tabs are `EmptyState`s; load failures are alerts; 加载更多 is a quiet button. |
| 仓位: assets, risk | Assets is one card of tiles. Risk is sections with dividers instead of bordered cards: rules, the fidelity notes with 审计, the ledger as a disclosure, isolated allocation as kit fields, and the two liquidation sections with badges. The liquidation timeline uses badges and an `EmptyState`, and its colours come from global tokens (its `--trade-*` colours were undefined inside the 复盘与完整性 drawer). |
| Styles | About 410 rules are removed: those for the ticket and the account view, and legacy rail markup that nothing renders any more (old tabs, tables, chips, list cards, the `--replay-rail-*` aliases, the `.replay-right-rail` wrapper). They included 7 `!important`. 99 token-based rules replace them at the end of `replay.css`; `replay.css` is 1,584 lines (was 2,767) and `replayPanels.css` 42 (was 463). |
| Code | The unused `ReplayRightRail` default export (a wrapper the page no longer renders) and the hand-written tab key handler are removed. `BacktestEquityCurve` loses a `compact` class that never had a rule of its own (a removed replay rule with the same name had hidden that). |

## Screens

The base build (Phase 5f5, `4320b2661`) and this branch, 1440 px, `zh-CN` unless marked. Neither local run has trades, so the captures add a sample account to the page's copy of the run's data (the tracks response, the run's stream and the account-record pages): one long position, one open limit order, two past orders and two fills. The last row is the real, empty account. Every replay write was refused except the controller lease.

| | Before | After |
|---|---|---|
| 下单 | ![](assets/frontend-design-phase-5f6/paper--before--dark.jpg) | ![](assets/frontend-design-phase-5f6/paper--after--dark.jpg) |
| 下单 (light) | ![](assets/frontend-design-phase-5f6/paper--before--light.jpg) | ![](assets/frontend-design-phase-5f6/paper--after--light.jpg) |
| 下单, English | ![](assets/frontend-design-phase-5f6/paper-en--before--dark.jpg) | ![](assets/frontend-design-phase-5f6/paper-en--after--dark.jpg) |
| 下单 · 限价 | ![](assets/frontend-design-phase-5f6/paperlimit--before--dark.jpg) | ![](assets/frontend-design-phase-5f6/paperlimit--after--dark.jpg) |
| 下单 · 按风险计划反算 (after: scrolled to the plan) | ![](assets/frontend-design-phase-5f6/paperplan--before--dark.jpg) | ![](assets/frontend-design-phase-5f6/paperplan--after--dark.jpg) |
| 下单 · 平仓 | ![](assets/frontend-design-phase-5f6/paperclose--before--dark.jpg) | ![](assets/frontend-design-phase-5f6/paperclose--after--dark.jpg) |
| 仓位 · 持仓 | ![](assets/frontend-design-phase-5f6/account--before--dark.jpg) | ![](assets/frontend-design-phase-5f6/account--after--dark.jpg) |
| 仓位 · 持仓 (light) | ![](assets/frontend-design-phase-5f6/account--before--light.jpg) | ![](assets/frontend-design-phase-5f6/account--after--light.jpg) |
| 仓位, English | ![](assets/frontend-design-phase-5f6/account-en--before--dark.jpg) | ![](assets/frontend-design-phase-5f6/account-en--after--dark.jpg) |
| 平仓 opened on the position | ![](assets/frontend-design-phase-5f6/accountclose--before--dark.jpg) | ![](assets/frontend-design-phase-5f6/accountclose--after--dark.jpg) |
| 当前 (open orders) | ![](assets/frontend-design-phase-5f6/acct-open-orders--before--dark.jpg) | ![](assets/frontend-design-phase-5f6/acct-open-orders--after--dark.jpg) |
| 历史 (order history) | ![](assets/frontend-design-phase-5f6/acct-order-history--before--dark.jpg) | ![](assets/frontend-design-phase-5f6/acct-order-history--after--dark.jpg) |
| 成交 (fills) | ![](assets/frontend-design-phase-5f6/acct-fills--before--dark.jpg) | ![](assets/frontend-design-phase-5f6/acct-fills--after--dark.jpg) |
| 资产 | ![](assets/frontend-design-phase-5f6/acct-assets--before--dark.jpg) | ![](assets/frontend-design-phase-5f6/acct-assets--after--dark.jpg) |
| 风险 | ![](assets/frontend-design-phase-5f6/acct-risk--before--dark.jpg) | ![](assets/frontend-design-phase-5f6/acct-risk--after--dark.jpg) |
| 仓位, the real empty account | ![](assets/frontend-design-phase-5f6/account-empty--before--dark.jpg) | ![](assets/frontend-design-phase-5f6/account-empty--after--dark.jpg) |

## Verification

**In the running app** (headless, 1440 px, sample account as above): 限价 showed the price field in the order-type panel; 按风险计划反算 opened the plan fields; 平仓 switched the ticket to closing; 平仓 on the position opened the close form with the size filled in; each record tab showed its rows. The order preview and capacity requests (advisory, they change nothing) answered as before. Not run, because they change the run: placing, closing, reversing or cancelling orders, setting protection or leverage, allocating margin, auditing the account.

**Capture safety:** the capture pages refuse replay writes, now including commands sent through the session path (`/runs/session/<id>/commands`) unless they only acquire the controller lease. The earlier phases' capture pages did not cover that path; the only command they sent through it was the same lease, since no capture pressed a trading control.

**Tests:** the replay, replay-launcher and soak-script tests pass. Four source assertions were updated with the markup: the account records and the order type are kit `Tabs` with their panel and 开仓 / 平仓 a `SegmentedControl` (instead of `role="tablist"`, `handleRailTabKeyDown` and `data-replay-rail-tab`); the trade palette takes buy and sell from `--text-up` / `--text-down` with no `--replay-rail-*` aliases left (instead of a light-theme alias rule and a 4-column grid); the rail's dock body scrolls through `.replay-market-dock-body`; and the narrow-rail liquidation legs rule is checked on `.replay-trading-workbench`, where the timeline renders, instead of the removed wrapper. The soak script's hooks (`[data-replay-action="place-order"][data-side]`, `aria-disabled`, `#replay-order-size-feedback[data-tone]`) are kept; it was not run.

**Style metrics** (against 5f5): class names with no CSS rule 0 (unchanged), raw `<button>` 571 → 544, `<Button>` uses 208 → 229, button class families 41 → 40, `!important` 41 → 34.

**Full check:** `npm run check` passes: 5,164 frontend tests, 137 desktop tests, lint (one existing warning), both typechecks and the build. The slider styling, the summary alignment and the full-width time tiles were adjusted after that run; the typechecks, lint, the stylesheet checks and the replay, replay-launcher and soak-script tests (751) were run again on the final code.

## Known gaps

- **English record tabs** (Positions … Risk) are wider than the rail; the last tab scrolls into view rather than showing at once.
- **Copy (Phase 6):** fidelity and status codes are still shown as codes (`UNSUPPORTED_NO_HISTORY`, `NOT_RUN`, `ACTIVE`, ledger kinds and references); the ticket's fidelity line and the risk notes use internal terms.
- **The buy and sell buttons** stay outside the kit (see DESIGN.md, "Trading views"); so does the size slider (a native range input).
- **Not exercised:** the trading actions above, a HEDGE run (per-leg leverage and the leg selector), an ISOLATED run (allocation form), multi-market positions (the 当前商品 filter).
- **Desktop app:** not tested.
