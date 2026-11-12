# Frontend design refactor: Phase 2a QA (cascade layers and the `index.css` split)

- Date: 2026-11-12
- Branch: `design/phase-2a-css-layers`, based on `design/phase-0-1` (PR #359)
- Plan: [`frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md`](../frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md) §5, §6. Contract: [`DESIGN.md`](../DESIGN.md#stylesheets-and-cascade-layers)
- Intended visual change: **none.** This PR only moves CSS and assigns cascade layers.

## What changed

| Area | Change |
|---|---|
| Layer order | `src/styles/layers.css` declares `reset, tokens, primitives, patterns, features, overrides`. Every entry page imports it first, so the order holds on all five pages. In the build, the shared stylesheet that carries it is the first app stylesheet each page links. |
| `src/index.css` | Was one 15,859-line file. It is now a manifest that imports each file into a layer: `styles/reset.css` (reset), `styles/tokens.css` (tokens), and in `features` the existing components, plugin center and extension stylesheets plus 37 new feature files next to their features (for example `features/watchlist/watchlist.css`, `features/replay/replay.css`, `app/topBar.css`). |
| Other app CSS | The 15 stylesheets imported from JavaScript wrap themselves in `@layer features`. So do the Settings and Data Workbench `<style>` strings. |
| Third-party and extension CSS | Monaco's CSS is wrapped into `features` by a Vite plugin (`scripts/vite-css-layers.mjs`). Extension stylesheets and extension themes are wrapped the same way when injected. Unlayered, each would beat every layered rule regardless of specificity. |
| Tests | Tests that assert on global CSS read it through `src/test/appStyles.ts`, which inlines the manifest's imports. A new extension test checks that injected styles land in `features`. |
| Tooling | `npm run check:css-layers` (part of `npm run check`) fails on CSS outside a layer. `npm run css:cascade -- --base <ref>` compares stylesheets with a Git ref and lists every declaration pair whose winner would change. |

## How "no visual change" was verified

### 1. Static cascade comparison

`npm run css:cascade -- --base design/phase-0-1` compares every declaration in the app's stylesheets at the base with the working tree. That covers `index.css` and its imports, the stylesheets imported from JavaScript, the `<style>` strings and Monaco's CSS.

- **Result: 23,702 declarations; 0 removed, 0 added, 0 winner changes.**
- **What a winner change means:** a pair of declarations that set the same property with different values, can match the same element, and would resolve the other way because of a new layer or a new order.
- **How the tool decides that two selectors can match the same element:**
  - **Subject compounds:** tag, id, classes and pseudo-element must be compatible.
  - **Classes on one element:** which classes the TSX source can put on one element, including classes forwarded through `className` props and strings routed through variables.
  - **Nesting:** which classes can sit inside which. This comes from a JSX containment scan that uses the TypeScript checker to tell text values from markup.
- **Where the tool can't tell:** a class applied through the DOM API, an unresolved component, or content passed as children it can't see. It treats these as able to meet anything.

**Splitting by feature means reordering rules.** The 105 interleaved ownership runs in the old file were grouped into feature files without crossing any order dependency the model found. Where a dependency blocked a move, the rules stay in a separate later file instead of being forced together.

### 2. Live check on the running app

A one-off script loaded each snapshot state from `scripts/design-snapshots.mjs` in headless Chrome against the Vite dev server and a LIVE backend. For each state it:

1. recorded every element's computed style, plus `::before` and `::after`, with the new stylesheets;
2. replaced each stylesheet's text with its base version on the same DOM and recorded again;
3. restored the new text and recorded a third time.

It then compared new against old wherever the first and third captures agreed, so live data updates didn't count as differences. Each state ran twice: plain, and with `:hover`, `:focus`, `:focus-visible` and `:active` forced on every element.

- **Coverage:** 22 states, dark and light at 1440×900, plus dark at 1366×768 and 1024×768.
- **Result: no differing computed value in any of the 88 captures, in either pass** (about 92,600 elements, plus their `::before` and `::after` boxes).
- **Two states not reached at 1024×768:** the rail's tape and accounts views. The rail is collapsed at that width, so those two captures show the market page instead.
- **Proving the check works:** a planted change in the base CSS was detected in both passes. The hover-only part of it showed up only in the forced pass.

### 3. Build

`vite build` keeps the layers. The main stylesheet starts with the layer order, then `@layer reset`, `@layer tokens` and the `@layer features` blocks. Monaco's chunk is wrapped in `@layer features`. In every page's HTML, the shared stylesheet is linked before any feature stylesheet.

## Known gaps, intentionally left for later phases

- **Moved to Phase 2b, because each changes how some controls look:**
  - **The `html :is()` button patches.** Moving them to `overrides` would change about 1,300 rule pairs; for example, disabled primary buttons in Settings would look enabled.
  - **Removing `!important`** (45 declarations).
  - **Moving `.ui-*` into `primitives`.** `components.css` stays in `features` until 2b replaces it with the kit.
- **Sixteen order-dependent files.** Fifteen files hold rules that must load later than their feature's main file, and `styles/lateFixes.css` holds a few that must load after every feature file. Each says why in its header. They merge into the main file when the surface is rebuilt in Phase 5.
- **Extension stylesheets behave slightly differently.**
  - They now always beat reset and token rules, which used to win by specificity in rare cases.
  - `@import` inside an injected extension stylesheet is no longer supported. `docs/trusted-extensions.md` says so.
- **Dev and build load three stylesheets in a different order.** `chartAccountOverlay.css`, `historyStudy.css` and `chartStrategyEntry.css` load before `index.css` in dev and after it in the build. This was already true before this PR. All of them are now in `features`, so their order relative to `index.css` decides ties exactly as before, in each environment.
- **What the checks don't cover.**
  - The live check covers only the snapshot states; a replay session and the trading workstation are not among them.
  - The static check covers every rule, but it relies on how the source applies classes. A class built at runtime in a way the scan can't see would be missed.
- **No desktop (Electron) smoke run.**
