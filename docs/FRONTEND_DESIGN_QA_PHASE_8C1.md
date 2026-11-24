# Frontend design refactor: Phase 8c1 QA (static inline styles)

- Date: 2026-11-23
- Branch: `design/phase-8c-kit`, on Phase 8b (`design/phase-8b-cleanup`, PR #579)
- Plan: [`frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md`](../frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md), Phase 8 (part 8c1)
- **Intended visible change:** the crash screen's retry button is the kit's primary button (32 px tall, the solid accent, 13 px type) instead of a hand-styled one (35 px, the lighter accent, the browser's 13.33 px). The crash screen shows only when a render error reaches the app's boundary. Everything else computes as before.

## What changed

| Area | Change |
|---|---|
| Static inline styles | 22 `style={{}}` objects with only literal values, and the literal half of one mixed object, become classes in the owning feature's stylesheet: the crash screen (`app-crash*`), the chart load error and its details, diagnostic and padding (`chart-load-error*`), the unavailable interval overlay, the chart header's history-only label, the market workspace's chart slot (its layout `order` stays inline), the drawing toolbar's spacer, bold and italic buttons and the tool variant corner mark, the workspace panel's lock icon, and the replay rail's full-height dock. The position readout's 11 px size and 50 px width join its rule in `styles/overrides.css`, which already holds its type in every toolbar. The chart load error's hint (`<small>`) needed nothing: `.error-message small` already sets the same three values. |
| Dynamic inline styles | 68 stay: geometry measured or dragged at runtime (panel widths, virtual list offsets, menu positions, depth bars) and colours that come from data (link groups, watchlist colours, indicator lines). |
| Crash screen button | A raw `<button>` with an inline style becomes the kit `Button` (`variant="primary"`). |
| Guardrails | The style metrics count static inline styles (literal values only) as a zero target in `npm run check`, and report dynamic ones without a target. Browser-test harnesses (`*.browser.tsx`, `src/test/`) are no longer counted as components: they render fixed-size test charts. The raw `<button>` ratchet is 263 (266 in 8b, less the crash screen's button and two in test harnesses). The inline style ratchet is gone. |

## Results

**Pair comparison** (`output/design-8/pair-diff-8c1.mjs`). Each changed element is added to its real container twice, as it was (old markup, inline style) and as it is now (class), and the two subtrees' computed styles are compared, plain and with hover, focus and active forced on every element. Market and strategy pages, dark and light, 1440 px, 10 pairs: the chart load error and the unavailable interval in a chart canvas, the history-only label in a chart header, the chart slot in the market workspace, the spacer, the bold, italic and position buttons and the variant mark in the drawing toolbar (and the buttons inside the strategy shell), the lock icon in the workspace panel's action grid, the replay dock in the market rail.

| | Pair checks | Differing values |
|---|---|---|
| 9 pairs | 72 | 0 |
| Chart load error | 8 | 120: width, inline size and transform/perspective origin of the overlay and its chart area, by at most 0.016 px |

The chart load error's two copies sit side by side as flex children of the chart canvas, which splits the width between them; the sub-pixel difference is their position in that row, not their styles (every other property, including padding, overflow and the details, pre and textarea rules, matches).

**Crash screen.** The same comparison on the crash screen's container, mark, title and detail: no differing value. The button differs as intended (above).

## Screens

The crash screen in dark, before (top, inline styles) and after (bottom, classes and the kit button), drawn in the app page with the screen's Chinese text:

![](assets/frontend-design-phase-8c1/crash-screen--before-top-after-bottom.jpg)

## Verification

Targeted local checks; the full check runs in CI:

- `npm run check:styles` (strict: static inline styles 0, raw `<button>` 263 at its ratchet), `npm run check:css-layers`, `npm run typecheck` (both tsconfigs), ESLint on the changed modules and scripts, `npm run build` (no warnings).
- Tests: the stylesheet readers and the tests of each changed surface (app shell, chart workspace, drawings, components, settings, strategy research, backtest, plugins, extensions) 1,318, all replay tests 688, and the style metric tests (10; new: static versus dynamic style objects, browser-test harnesses left out). One replay test read the dock's inline style from the source; it now checks the class and its rule.

## Known gaps

- **Not run locally: the full `npm run check`.** GitHub CI runs it on the PR.
- **The changed elements were compared as fixtures in their containers**, not in their own running states: the crash screen, the chart load error, the unavailable interval, the history-only label, the drawing toolbar's text options and the replay rail all need a render error, the local service or a replay session.
- **The chart load error's retry and copy buttons (`.retry-btn`) are still raw buttons**; they move to the kit with the rest in 8c5.
