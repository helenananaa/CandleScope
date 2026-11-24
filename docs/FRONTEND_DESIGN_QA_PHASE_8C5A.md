# Frontend design refactor: Phase 8c5a QA (market page, settings and accounts on the kit)

- Date: 2026-11-24
- Branch: `design/phase-8c5a-market`, on Phase 8c4 (`design/phase-8c4-plugins`, PR #586)
- Plan: [`frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md`](../frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md), Phase 8 (part 8c5a)
- **Split (2026-11-24):** 8c5 had 92 raw buttons in 38 files across every area, so it lands in three parts:
  - 8c5a: the market page, settings and accounts.
  - 8c5b: replay.
  - 8c5c: strategy, backtest and data, plus the documented exceptions and the zero target.
- **Intended visible change:** layout, type and behaviour stay. The look changes in these places:
  - The chart load error's "copy diagnostic" is a secondary button; retry stays the primary action.
  - Menu rows in the watchlist and symbol search are the kit's.
  - A chosen source in the source picker shows its check at the start of the row, "All" included.
  - The settings rail's current category is tinted with full-strength text instead of accent text.
  - Theme, proxy and storage cards are kit option cards: a smaller radius, and a tinted selection with an accent border instead of a ring.
  - The time navigation dialog's buttons are ghost and primary, and the dialog is centred.

## What changed

| Area | Change |
|---|---|
| Kit | **New `MenuItemButton`:** the menu row (`.ui-menu-item`) as a primitive, with a leading mark, label, hint and danger tone. The kit `Menu` now renders its items with it. Menus a feature lays out itself use it too: one with a header or groups, or a list inside a search panel. **Danger rows:** the icon takes the row's danger colour. **`OptionButton`:** reports its choice as `aria-checked` in a radio group (`role="radio"`), and fades when marked `aria-disabled`, like a disabled one. New kit tests. |
| Watchlist | **Buttons:** sort headers → small ghost `Button`s, keeping the header row's height and type. Collapse, new list, the collapsed rail's star, a list's fold toggle and a row's delete → `IconButton`s, keeping their icons and compact sizes; delete is `danger`. **Rows:** a row's keyboard control → `row` `OptionButton`, still laid out as the row. The collapsed rail's lists → `row` `OptionButton`s. **Menus:** the row and list menus' items → `MenuItemButton`s with their icon or dot as the mark and the tier description as the hint; the chosen tier stays tinted. |
| Symbol search | **Trigger:** → `ControlButton`. **Source picker:** sources → `MenuItemButton`s with the check in the mark column; favourite → pressed `IconButton`. **Other menus:** the coverage list's sources and the add-to-watchlist menu → `MenuItemButton`s. |
| App | **Header actions** → `ControlButton`s; a link action stays a link. **Chart load error:** retry → primary `Button` (`#retry-btn` stays) and copy diagnostic → `Button`, side by side. **Replay state panel:** its retry and resync → primary `Button`s, the same way; `retry-btn` is gone. |
| Time navigation dialog | Close → ghost `Button` and go → primary submit `Button`. The dialog has `margin: auto` again: the reset's `margin: 0` had put the native dialog at the top left. |
| Settings | **Category rail:** → `row` `OptionButton`s marked `aria-current="page"` (`.st-nav-item` stays for the snapshot script). They keep the rail's quiet resting colour and spacing. **Cards:** theme, proxy mode and storage preset → `card` `OptionButton`s. **Exchange rows:** → `row` `OptionButton`s, flush in their list. |
| Data workbench, trading accounts | **Data workbench:** an instrument's fold row → `row` `OptionButton`. **Trading accounts:** closed trade and journal rows → `row` `OptionButton`s laid out as the card's content (`trading-row-button` → `trading-row-open`). The account kinds → `card` `OptionButton`s in their radio group; planned kinds are `aria-disabled`. |
| CSS | **Removed:** these surfaces' own button styling (boxes, colours, hover, focus, active and disabled states, `.retry-btn`, the watchlist's `.wl-ctx-item*`, the settings cards' `.active` and lift on hover) and the dead `.interval-create-btn`. **Kept:** layout and content type. |
| Guardrails | Raw `<button>` ratchet 92 → 57. `*-btn` families 18 → 13. `wl-collapse-btn` is a declared hook: the replay soak script uses it. |

These surfaces have no raw buttons left.

## Results

Before/after compare 8c4 (`73f1e2d12`) with this branch, at 1440 × 900 in zh-CN, with the local service not running (`output/design-8/market-shots-8c5a.mjs`). The script itself is not in the repository.
- **Seen in the app:** the market page (top bar, and the watchlist with a row pointed at), the watchlist's row menu, the symbol search's source picker, and Settings on appearance, network and data.
- **Rendered by their components with fixed props** (they need the service): the exchange list inside Settings, the chart load error next to the replay state panel's two errors, the time navigation dialog and the add account dialog.

All scenes were captured in dark; six were also captured in light.

**Found and fixed while capturing:**
- **Watchlist header:** the sort headers had drifted, so the header row keeps its height (the kit button's border and line height), its gap before the sort icon and its centred name column. Its buttons now use the app's font; they had used the browser's default font (Arial).
- **Watchlist menu:** the tier descriptions had turned monospace; they are prose, so they keep the sans font.
- **Kit danger rows:** the remove row's icon had turned grey; the kit now colours a danger row's icon (kit fix).
- **Settings rail:** it had turned brighter and 2 px taller per row; it keeps its quiet resting colour and spacing.
- **Time navigation dialog:** it sat at the top left on 8c4 as well; it is centred now.

## Screens

Dark, 8c4 → this branch:

| | Before | After |
|---|---|---|
| Top bar and watchlist (ETHUSDT pointed at) | ![](assets/frontend-design-phase-8c5a/market-dark--before.jpg) | ![](assets/frontend-design-phase-8c5a/market-dark--after.jpg) |
| Watchlist row menu | ![](assets/frontend-design-phase-8c5a/wl-menu-dark--before.jpg) | ![](assets/frontend-design-phase-8c5a/wl-menu-dark--after.jpg) |
| Source picker | ![](assets/frontend-design-phase-8c5a/source-picker-dark--before.jpg) | ![](assets/frontend-design-phase-8c5a/source-picker-dark--after.jpg) |
| Settings: appearance | ![](assets/frontend-design-phase-8c5a/settings-appearance-dark--before.jpg) | ![](assets/frontend-design-phase-8c5a/settings-appearance-dark--after.jpg) |
| Settings: network | ![](assets/frontend-design-phase-8c5a/settings-network-dark--before.jpg) | ![](assets/frontend-design-phase-8c5a/settings-network-dark--after.jpg) |
| Settings: storage presets | ![](assets/frontend-design-phase-8c5a/settings-data-dark--before.jpg) | ![](assets/frontend-design-phase-8c5a/settings-data-dark--after.jpg) |
| Settings: exchanges | ![](assets/frontend-design-phase-8c5a/settings-exchange-dark--before.jpg) | ![](assets/frontend-design-phase-8c5a/settings-exchange-dark--after.jpg) |
| Chart load error, replay errors | ![](assets/frontend-design-phase-8c5a/errors-dark--before.jpg) | ![](assets/frontend-design-phase-8c5a/errors-dark--after.jpg) |
| Time navigation dialog | ![](assets/frontend-design-phase-8c5a/time-dialog-dark--before.jpg) | ![](assets/frontend-design-phase-8c5a/time-dialog-dark--after.jpg) |
| Add account | ![](assets/frontend-design-phase-8c5a/add-account-dark--before.jpg) | ![](assets/frontend-design-phase-8c5a/add-account-dark--after.jpg) |

Light:

| | Before | After |
|---|---|---|
| Top bar and watchlist | ![](assets/frontend-design-phase-8c5a/market-light--before.jpg) | ![](assets/frontend-design-phase-8c5a/market-light--after.jpg) |
| Watchlist row menu | ![](assets/frontend-design-phase-8c5a/wl-menu-light--before.jpg) | ![](assets/frontend-design-phase-8c5a/wl-menu-light--after.jpg) |
| Source picker | ![](assets/frontend-design-phase-8c5a/source-picker-light--before.jpg) | ![](assets/frontend-design-phase-8c5a/source-picker-light--after.jpg) |
| Settings: appearance | ![](assets/frontend-design-phase-8c5a/settings-appearance-light--before.jpg) | ![](assets/frontend-design-phase-8c5a/settings-appearance-light--after.jpg) |
| Chart load error, replay errors | ![](assets/frontend-design-phase-8c5a/errors-light--before.jpg) | ![](assets/frontend-design-phase-8c5a/errors-light--after.jpg) |
| Add account | ![](assets/frontend-design-phase-8c5a/add-account-light--before.jpg) | ![](assets/frontend-design-phase-8c5a/add-account-light--after.jpg) |

## Verification

These are targeted local checks; CI runs the full check.

- `npm run check:styles` passes in strict mode: raw `<button>` is at its ratchet of 57, families at 13, and no class name lacks a rule. The 8b dead-CSS scan finds no dead selectors.
- `npm run check:css-layers`, `npm run typecheck` (both tsconfigs) and ESLint on the changed modules pass.
- `npm run build` passes. Its one warning is the size of the code editor's bundle, and 8c4 gives the same warning.
- 2,614 tests pass, covering:
  - app and components (the kit included);
  - watchlist, symbol search, settings, trading accounts, data workbench, market data, replay, plugins and drawings;
  - i18n;
  - every test that reads the app's stylesheets;
  - style metrics.
- No existing test needed changing. New kit tests cover `MenuItemButton`, an `OptionButton` radio and `aria-disabled`.
- The scripts' hooks stay: `#retry-btn`, `#symbol-selector` and `.symbol-selector`, `.wl-collapse-btn`, `.st-nav-item`, `data-header-action` and `data-replay-action="resync"`.

## Known gaps

- **Not run locally: the full `npm run check`.** GitHub CI runs it on the PR.
- **Not seen, because they need the service's data:**
  - trading accounts' trade and journal rows;
  - the data workbench's instrument rows;
  - the symbol search's coverage list and add-to-watchlist menu;
  - the watchlist's collapsed rail (the rail's own panel manages collapsing).

  The rows keep their card's look on purpose: the option is laid out as the card's content. The menus use the same `MenuItemButton` as the watchlist menu, which was seen.
- **Seen only rendered by their components:** the exchange list, the error overlays, the time navigation dialog and the add account dialog.
- **The replay screenshot viewer is probably also a native dialog that the reset put at the top left.** It is left for 8c5b with the rest of replay.
