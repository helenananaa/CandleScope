# CandleScope Design System

This file is the design contract for the CandleScope interface. Design tools and contributors read it before changing UI; where a design skill's defaults disagree, this file wins. Decisions and their reasoning live in [`frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md`](frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md).

- Product: an open-source desktop and web charting terminal for crypto and futures markets, with replay training and strategy research.
- Users: active traders and quant researchers who keep it open for hours. The default interface language is Simplified Chinese; English and other locales are supported.
- Implementation: tokens in `frontend/src/styles/tokens.css`, primitives in `frontend/src/components/ui/` (components and their CSS).

## Principles

1. **The chart is the hero.** Chrome recedes: neutral surfaces, few borders, one accent. Nothing in the chrome should be more saturated than the candles.
2. **Colour carries meaning.** Up and down belong to the user's chart settings. Status colours mean status. The accent means "act here" or "selected". Decoration never uses colour.
3. **Separate with space and surface steps, not lines.** Use a border only where a boundary carries meaning: inputs, focus, tables, the edge of an overlay. Never nest cards inside cards.
4. **Words are interface.** Task-first labels, one sentence at most, user terms rather than internal ones. Diagnostics go behind a "技术详情" / "Technical details" disclosure. Errors say what happened and what to do, in the interface language.
5. **One component per job.** Buttons, fields, tabs, badges, dialogs and drawers come from the primitives. A feature may add layout (margins, widths, grid placement); it may not restyle a primitive's box, colour or type.

## Colour: Graphite

Neutral greys with almost no hue, brand blue as the only accent. Values below are the source of truth for `tokens.css`; every text token reaches WCAG AA (4.5:1) on every surface, including hover, and `scripts/design-tokens.test.mjs` enforces it.

| Token | Dark | Light | Use |
|---|---|---|---|
| `--surface-0` | `#0d0e10` | `#ffffff` | App and chart background |
| `--surface-1` | `#141518` | `#f7f7f8` | Bars, rails, panels |
| `--surface-2` | `#1c1d21` | `#f0f1f3` | Inputs, raised controls, cards that must stand out |
| `--surface-hover` | `#272930` | `#e6e7ea` | Hover and pressed on any surface |
| `--border-subtle` | `#25272c` | `#e2e3e7` | Dividers that carry meaning |
| `--border-strong` | `#363940` | `#c8cad0` | Input and control outlines |
| `--text-primary` | `#e9eaec` | `#17181b` | Body text, values |
| `--text-secondary` | `#a6a9b0` | `#4a4d55` | Labels, secondary values |
| `--text-muted` | `#9094a0` | `#5b5f69` | Hints, captions |
| `--text-accent` | `#6aa9f5` | `#0f5bbd` | Links, selected text |
| `--accent-solid` | `#1473e6` | `#1473e6` | Primary buttons, with white text (4.54:1) |
| `--accent-blue` | `#3d8ef0` | `#1473e6` | Focus rings, selection outlines |
| `--text-info` | `#5fd4c6` | `#0b6577` | "Live" and informational status |

Status text keeps its meaning across themes: success, danger, warning and purple are defined in `tokens.css`. Chrome status colours stay muted; only the chart uses full-strength up/down colours.

Brand marks (`public/brand/`) use ink `#07182b`, blue `#1473e6` and teal `#12bfae`. Teal appears only in the mark and must never be confused with the user's up colour.

## Type

- **Interface font: IBM Plex Sans** (`@fontsource/ibm-plex-sans`, weights 400 to 700).
- **Chinese and other CJK text** comes from the system: PingFang SC / Microsoft YaHei for Simplified Chinese, PingFang TC / Microsoft JhengHei for Traditional, Hiragino / Yu Gothic for Japanese, Apple SD Gothic Neo / Malgun Gothic for Korean. Each stack applies only under its own `:lang()`, so Chinese never renders in a Korean font.
- **Monospace: JetBrains Mono**, for code, IDs and aligned order-book columns only. Prices elsewhere use the sans with `font-variant-numeric: tabular-nums`. IBM Plex Mono is under evaluation as a replacement.
- **Scale:** 11px (captions and badges only, never smaller), 12, 13 (body), 14, 16, 20, 24. Use the `--font-size-*` tokens.
- Letter-spacing is for uppercase Latin labels only and is reset for CJK interface languages.

## Space, shape, depth, motion

- 4px grid: `--space-1` (4) to `--space-10` (40). Lay out sibling groups with flex or grid and `gap`.
- Radius by role: `--radius-control` (6) for buttons, inputs and chips; `--radius-md` (8) for panels; `--radius-lg` (12) for dialogs.
- Three elevation steps: surfaces 0 to 2. Shadows only on overlays (menus, popovers, dialogs, drawers).
- Motion: 120ms for hover and press, 180ms for open and close, one ease-out curve. Animate only state changes the user caused. Respect `prefers-reduced-motion`.
- Stacking uses the `--z-*` layer tokens. Modals always sit above drawers; Escape closes the topmost layer.

## Themes

- **App theme** (Settings → Appearance): dark, light or follow system. It styles the whole interface and every chart that follows it.
- **Chart appearance** (per chart): follow the app theme (default), or its own dark, light or custom background, with optional up/down colours. The app theme never overrides a chart's own appearance; a reset returns the chart to following the app.
- Chart text and grid colours follow the chart's effective background, so any custom background stays readable.
- An installed theme extension takes the app theme's place.

## Copy

- Sentence case. Name things by what the user recognises: "Order book", not "L2 snapshot reconciler".
- Buttons state the action ("Create alert", "Save changes"); results confirm it ("Alert created").
- Never show raw error codes or English backend messages in another locale; map them through `describeError` in `frontend/src/i18n/serverErrors.ts`. A code users meet often gets a message of its own there (`CODE_KEYS`), which replaces the server text; other codes show a localized summary with the server text in brackets.
- Status values from the server (`accepted`, `accepted_with_gaps`) get labels, as `formatQualityStatus` does; an unknown value is shown as sent rather than hidden.
- Text written by an extension or by the host for support (extension load failures, registry errors) stays as written, set apart as technical detail.
- Keep internal QA, runtime and contract terms out of default views.

## Components

Build surfaces from the primitives in `frontend/src/components/ui` (import from `components/ui/index.js`); see them in both themes at `/ui-gallery.html` on the Vite dev server.

| Need | Use |
|---|---|
| An action | `Button`: `primary` for the one main action in a view, `secondary` (default), `ghost` for low emphasis, `danger` for destructive actions; `size="sm"` in dense panels. `IconButton` when there is no room for text; it always has a label. |
| A toolbar pill or picker | `.ui-control` (with `.is-active` or `aria-expanded`) |
| Text, number, choice or time input | `Field` around `Input`, `Select`, `Textarea` or `DateTimeInput`. `DateTimeInput` writes times as `2026-01-02 09:30` in every locale (the browser's own control follows the browser's language, not the app's), opens the browser's calendar from its button, and always shows its zone, UTC by default. Pass `zoneLabel={false}` only when the field's label already names the zone. |
| On/off | `Switch` for settings that apply at once; `Checkbox` in forms that are submitted |
| One of two to five options | `SegmentedControl` |
| Switching views | `Tabs` with `TabPanel` |
| A status word or count | `Badge` with a tone |
| A titled group | `Section` |
| A key figure | `Stat` |
| Secondary detail, diagnostics | `Disclosure` (closed by default) |
| A message inside a panel | `InlineAlert`; `EmptyState` when the panel has nothing to show |
| Choosing a file | `FileDrop`; `compact` for one row in a narrow panel. Never a bare `<input type="file">`, whose "Choose file" text is in the browser's language. |
| A task that needs full attention | `Dialog` (modal) |
| Asking before an action that cannot be undone | `confirmAction({ title, confirmLabel, tone: "danger" })`, or `ConfirmDialog` when rendering one yourself. Never `window.confirm`. |
| The result of an action (saved, failed) | `notify({ tone, title, message })`. Never `window.alert`. |
| A side panel next to the chart | `Drawer` (one per side; opening another replaces it) |
| Options anchored to a control | `Popover`, for a short form or choice tied to the button that opens it (the history study setup); `Menu` for a list of actions |
| A short description of an icon control | `Tooltip` (hover and keyboard focus) |
| Something users need to know about only when it goes wrong (an extension failed, recovery mode) | A toast through `notify({ durationMs: 0, action })` while it lasts, opening the fix. Never a permanent floating button. |
| An existing overlay that is not rebuilt yet | `OverlayLayer` around its markup: it joins the stack and keeps its look. Rebuilt surfaces use the primitives above. |

Overlays share one stack (`components/ui/overlay`): drawers, then modals, then popovers and menus, with toasts above modals. Every overlay renders in the overlay host outside the app root, so no page container can trap it under another.

- **Escape** goes first to the focused control: an editor, a nested picker or a field that cancels its edit uses it and calls `preventDefault`. If nothing used it, the topmost layer closes, and only that one. A native modal `<dialog>` keeps its own Escape. Page shortcuts on Escape (restoring a maximised chart, leaving a drawing tool) wait until no layer is open.
- **Focus** moves into a layer when it opens (its first control, skipping close buttons marked `data-overlay-close` and resize handles) and returns to the control that opened it.
- **A modal** makes everything beneath it inert and keeps Tab inside. A layer with unsaved work can refuse Escape (`closeOnEscape`), as the indicator editor does.

## Page header

Every page uses `AppHeader` (`frontend/src/app/AppHeader.tsx`), so the brand, the workspace navigation and Settings are always in the same place. Its regions, left to right:

| Region | Holds |
|---|---|
| Brand and navigation | The logo and 行情 · 策略研究 · 回放训练. A page may add a `badge` after them (the replay training badge, research's way back to its task list). |
| `context` | What the page is about: the symbol, the data source, the replay run. |
| `tools` | Controls for that context: intervals, prices, the chart source. They narrow through their own rules. |
| `actions` | Page actions as data (`HeaderAction`: label, handler, open state, link). Right-aligned; when space runs out the last ones move into the 更多 menu. A popover opened by an action anchors through `anchorRef`, which points to 更多 while the action is in the menu. |
| `extras` | Controls that cannot go into a menu (the layout picker, plugin toolbar items). |
| `panels` | Panel toggles such as indicators and alerts, as icon buttons. |
| `settings` | Settings, always the last control. |

Put a new page button in `actions`, not in `tools` or `extras`, so it collapses with the others at narrow widths.

**Narrow widths.** The header measures itself instead of following window-width breakpoints, so it holds in every language. When something does not fit it sets compaction steps on `data-compact`, in this order:

1. Inline market metrics become the compact 合约市场摘要 button; the replay session's metric placeholders hide.
2. The wordmark, the ⌘K hint and the replay price-change label hide.
3. Only now, if the left side still does not fit after the page actions moved into 更多: the exchange badge and the 图表策略 label hide (its status dot stays).
4. Last: the interval chips scroll and long names truncate.

A window resize recomputes the steps; content changes (a new symbol, a ticking price) can only add steps, so the header never flickers. To let a new header element give way, add it to a step in `app/topBar.css`, not a `@media` rule.

**Right rail.** The chart keeps at least 65% of the window (up to 760 px), so at 1024 px the rail and its tab strip take about 31%. Tab labels wrap onto two lines between words (hyphenated where the language allows) instead of truncating.

**Status bar.** Each side lists its items most important first. When a side runs out of room its later items drop out whole, never cut; on the right, the version goes first.

## Stylesheets and cascade layers

Every app stylesheet sits in a cascade layer. The order is set once, in `frontend/src/styles/layers.css`, which every entry page imports first:

| Layer | Holds |
|---|---|
| `reset` | Element defaults and scrollbars (`styles/reset.css`) |
| `tokens` | Design tokens and themes (`styles/tokens.css`) |
| `primitives` | Shared components in `src/components/ui` (`button.css`, `field.css`, `choice.css`, `display.css`) |
| `patterns` | Layouts built from primitives (empty for now) |
| `features` | Feature CSS, plus Monaco's CSS and extension stylesheets, which compete with it by specificity |
| `overrides` | Deliberate cross-cutting overrides (empty for now) |

A later layer wins regardless of selector specificity, so no `html` prefixes or `!important` are needed to beat feature rules.

The other side of that rule: a feature's element selectors (`.panel button`, `.drawer input`) beat kit controls inside the panel. Older feature CSS that styles bare elements skips kit controls inside `:where()`, so its specificity does not change, for example `.research-data-drawer button:where(:not(.ui-btn, .ui-icon-btn, .ui-datetime-picker))`. New feature CSS styles its own classes, not bare elements.

- **Feature CSS lives next to its feature.** `src/index.css` only lists files, each with `layer(…)`; within a layer, the listed order still breaks ties.
- **CSS imported from a lazy module wraps itself** in `@layer features { … }`.
- **`npm run check:css-layers`** fails on any stylesheet outside a layer.
- **Moving rules between files or layers:** run `npm run css:cascade -- --base <ref>`. It lists every pair of declarations whose winner would change, and should report none for a pure move.

## Do not

- Introduce colours, fonts, radii or shadows outside the tokens.
- Add a new `*-btn`, `*-badge`, `*-overlay` or `*-modal` class family; extend the primitive instead.
- Use `!important`, static `style={{…}}`, `window.confirm` or `window.alert`. If a rule must win, put it in the right layer.
- Add rules to `src/index.css`, or a stylesheet outside a cascade layer.
- Use the generic template look: eyebrow plus giant headline plus numbered cards, gradient glows, a second accent colour, or identical rounded cards for everything.
