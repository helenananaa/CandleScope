# CandleScope Design System

This file is the design contract for the CandleScope interface. Design tools and contributors read it before changing UI; where a design skill's defaults disagree, this file wins. Decisions and their reasoning live in [`frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md`](frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md).

- Product: an open-source desktop and web charting terminal for crypto and futures markets, with replay training and strategy research.
- Users: active traders and quant researchers who keep it open for hours. The default interface language is Simplified Chinese; English and other locales are supported.
- Implementation: tokens in `frontend/src/styles/tokens.css`, shared primitives in `frontend/src/styles/components.css` and `frontend/src/components/ui/`.

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
- Never show raw error codes or English backend messages in another locale; map them through `describeError` in `frontend/src/i18n/serverErrors.ts`.
- Keep internal QA, runtime and contract terms out of default views.

## Do not

- Introduce colours, fonts, radii or shadows outside the tokens.
- Add a new `*-btn`, `*-badge`, `*-overlay` or `*-modal` class family; extend the primitive instead.
- Use `!important`, static `style={{…}}`, `window.confirm` or `window.alert`.
- Use the generic template look: eyebrow plus giant headline plus numbered cards, gradient glows, a second accent colour, or identical rounded cards for everything.
