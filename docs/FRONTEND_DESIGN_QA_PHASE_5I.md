# Frontend design refactor: Phase 5i QA (the order book and trade flow docks, header toggles on the kit)

- Date: 2026-11-15
- Branch: `design/phase-5i-docks`, based on `design/phase-5h-data-workbench` (PR #429)
- Plan: [`frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md`](../frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md), the Phase 5 rows. Contract: [`DESIGN.md`](../DESIGN.md)
- **Intended visible change:** the market rail's order book and trade flow docks use kit controls on tokens (mode and side switches, selects, collapse buttons, the trade history's date and hour), and the header's panel toggles, Settings and ⋯ are kit icon buttons. What they do is unchanged.

The row was split when it started (my call, like 5g6): the trading-account and read-only account docks have about 65 raw buttons of their own across ten files, with dialogs, a journal drawer and a practice ticket. 5i is the order book, trade flow and the header; **5i2** is the trading-account and read-only account docks.

## What changed

| Area | Change |
|---|---|
| Header | The indicators and alerts toggles on the market, replay and strategy pages are one `PanelToggle` (a kit icon button with `aria-expanded`, its count as a badge, tinted while open: blue for indicators, amber for alerts). Settings and the ⋯ overflow are kit icon buttons; the ⋯ keeps its menu anchor through the kit button's `ref`. |
| Rail | The hide button of the single-view rail (the replay page's right rail) is a small kit icon button. |
| Order book | 快照 / 连续 is a kit segmented control on its own row across the dock (连续 stays disabled with its reason where the exchange has no full book); levels, grouping and refresh are compact kit selects in one row of three; at a rail of 380 px or more the switch and the three selects share one row. 不限范围 is a compact kit select; the spread readout wraps under it as one piece when the rail is narrow instead of splitting across lines. The collapse button and 重试 are kit buttons. |
| Trade flow | 全部 / 主动买 / 主动卖 is a kit segmented control across the dock; the filter and bubble selects are compact kit selects. In 分布, 历史成交's UTC date and hour are kit fields (a date input and a select) with their labels above. |
| Styles | The order book's late-loading `orderBookControls.css` is merged into `orderBook.css` and deleted. The rules for the old mode switch, side switch, collapse button, the docks' raw selects, the header's `.app-header-icon` and the indicator toggle are gone, as is the shared chevron rule for raw selects in the docks (`components.css`). The compact selects share one padding rule so values such as 自动 0.1 and 1000 ms are not cut off. |
| Copy | No string changes. |

## Screens

The base build (Phase 5h, `d264f9057`) and this branch, `zh-CN` unless marked, BTCUSDT 1h on live Binance data (so prices differ between the two). 1440 × 900 unless marked; the narrow rail is a 1024 × 768 window. Writes were blocked in the capture and none was attempted.

| | Before | After |
|---|---|---|
| Market page, 盘口 open | ![](assets/frontend-design-phase-5i/market--before--dark.jpg) | ![](assets/frontend-design-phase-5i/market--after--dark.jpg) |
| Market page (light) | ![](assets/frontend-design-phase-5i/market--before--light.jpg) | ![](assets/frontend-design-phase-5i/market--after--light.jpg) |
| Market page, English | ![](assets/frontend-design-phase-5i/market-en--before--dark.jpg) | ![](assets/frontend-design-phase-5i/market-en--after--dark.jpg) |
| 盘口 and 成交 open | ![](assets/frontend-design-phase-5i/trades--before--dark.jpg) | ![](assets/frontend-design-phase-5i/trades--after--dark.jpg) |
| 盘口 and 成交 (light) | ![](assets/frontend-design-phase-5i/trades--before--light.jpg) | ![](assets/frontend-design-phase-5i/trades--after--light.jpg) |
| 分布 · 历史成交 | ![](assets/frontend-design-phase-5i/history--before--dark.jpg) | ![](assets/frontend-design-phase-5i/history--after--dark.jpg) |
| 分布 · 历史成交 (light) | ![](assets/frontend-design-phase-5i/history--before--light.jpg) | ![](assets/frontend-design-phase-5i/history--after--light.jpg) |
| Narrow rail (1024 × 768) | ![](assets/frontend-design-phase-5i/narrow--before--dark.jpg) | ![](assets/frontend-design-phase-5i/narrow--after--dark.jpg) |
| Narrow rail, English | ![](assets/frontend-design-phase-5i/narrow-en--before--dark.jpg) | ![](assets/frontend-design-phase-5i/narrow-en--after--dark.jpg) |
| Rail with only 自选 open | ![](assets/frontend-design-phase-5i/single--before--dark.jpg) | ![](assets/frontend-design-phase-5i/single--after--dark.jpg) |
| Strategy page header | ![](assets/frontend-design-phase-5i/strategy--before--dark.jpg) | ![](assets/frontend-design-phase-5i/strategy--after--dark.jpg) |

## Verification

**In the running app** (headless): on the market page the rail opened 盘口, 成交 and 分布; the order book streamed with its mode switch, selects and range row; the trade flow listed live trades with its side switch and selects; 分布's 历史成交 opened the history view with the date and hour fields; the header showed the indicators, alerts and Settings toggles at their usual places; in a 1024 × 768 window the order book's three selects still fit one row in Chinese and English. The strategy page header showed its indicators toggle and Settings. Nothing that changes data was run: no history read, no settings change.

**Tests:** the app, order-book, trade-flow, replay, strategy-research, kit, indicator, alert, settings and chart-workspace tests pass (1,597). `marketPageFrame.test` now finds Settings by its `settings-btn` class anywhere in the button's class list and the single-hide button by `market-rail-single-hide` among the kit classes. `indicator-toggle-btn` stays on the toggle (the smoke and multi-chart capacity scripts find it) and is listed as a test hook in the style metrics.

**Style metrics** (against 5h): class names with no CSS rule 0 (unchanged), raw `<button>` 364 → 350, `<Button>` uses 373 → 374, button class families 33 → 31, inline `style={{}}` 96 → 91, `!important` 30 (unchanged).

**Full check:** `npm run check` passes: 5,165 frontend tests, 137 desktop tests, lint (one existing warning), the i18n, style, CSS layer and architecture checks, both typechecks and the build. Two CSS-only adjustments after it (the narrow rail keeps three selects per row; the range readout wraps as one piece) were re-checked with the style and CSS layer checks, the order-book, trade-flow and app tests, and new captures.

## Known gaps

- **5i2:** the trading-account dock (accounts panel, add-account dialog, practice ticket, manual fill, journal drawer, stats, quick replay, chart overlay menu) and the read-only account dock (reconciliation, trade review) still use their own raw controls.
- **Kept as they are:** the rail's activity bar items (icon, label and badge stacked in one tile), its accordion triggers and collapse item, and the header's registered actions (历史研究, 跳转到日期), which can be links or buttons.
- **Replay page:** its indicators toggle (the same `PanelToggle`) and its right rail's hide button are covered by the replay and rail frame tests, but were not captured.
- **Desktop app:** not tested.
