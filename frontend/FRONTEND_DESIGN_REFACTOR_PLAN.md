# Frontend Design Refactor Plan

- Date: 2026-11-11 (decisions recorded 2026-11-12, see §8)
- Palette and type comparison, rendered on the real app: <https://claude.ai/artifact/KCtniUQLZSzbFaVjbHu1iE>
- Scope: all five entry points (`index.html` market, `strategy.html`, `replay.html`, `backtest.html`, `local.html`) and every overlay, drawer, and dock they open
- Basis: a code audit of `frontend/src` and full-resolution screenshots of the running app (backend LIVE mode, Vite dev server, headless Chrome at 1440×900 and 1024×768, dark and light)
- Evidence: [`docs/assets/frontend-design-audit-20261111/`](../docs/assets/frontend-design-audit-20261111/)

## 1. Verdict

The token layer is sound and is not the problem: CSS has 5,583 `var(--…)` uses against 67 hex literals. The problems are one layer up:

1. **No component layer in practice.** `components/ui/Button.tsx` and `styles/components.css` exist, but `<Button>` is used 5 times against 855 raw `<button>` elements. Every feature re-invents buttons, tabs, badges, selects, dialogs, and drawers. The result is 60 button classes and about 28 modal, dialog, drawer, and backdrop classes, each slightly different.
2. **No overlay system.** Drawers and modals stack on each other in the wrong order, and Escape behaves differently in each one.
3. **Some surfaces were never styled.** Seven or more user-facing panels render as bare browser defaults.
4. **Copy written for engineers.** Internal QA terms, raw error codes, and multi-paragraph explanations appear in the UI.
5. **Chinese typography is broken at the font-stack level.** Korean fonts are listed before any Chinese font, so Chinese text renders in a mix of Korean and Chinese glyphs.

Fixing these takes a primitive kit, an overlay manager, a shared page shell, a copy pass, and then a surface-by-surface migration. A visual redesign on top of the current structure would decay back into today's inconsistency within a few PRs.

## 2. Findings

Severity: **P0** looks broken to a user; **P1** is clearly unprofessional; **P2** is polish.

### 2.1 Unstyled surfaces (P0)

These render with browser defaults: grey native buttons, inline-flowing labels, native file inputs, and date inputs in the en-US format inside a Chinese UI.

| Surface | Where | Evidence |
|---|---|---|
| Event-marker panel ("分析事件标记") | `features/local-data/LocalAnalysisPanel.tsx`; 14 of 15 classes have no CSS rule | [59-local-analysis](../docs/assets/frontend-design-audit-20261111/59-local-analysis.jpg) |
| CSV event import | `features/local-data/LocalAnalysisCsvImport.tsx`; 9 of 9 classes unstyled | (inside the same panel) |
| History study setup dialog | `HistoryStudySetupDialog.tsx` borrows `.chart-time-dialog` (jump-to-date) and `.trading-button` (trading accounts) but never imports `tradingAccounts.css`, and `.chart-time-actions` and the select have no rule. The buttons ("关闭 开始研究") run together unstyled unless a trading or history chunk loaded first. Date inputs use the en-US format; the dialog is pinned top-left over the top bar | [38-history-study](../docs/assets/frontend-design-audit-20261111/38-history-study.jpg) |
| Replay hub "继续训练" hero button | `ReplayTrainingPageShell` | [20-replay](../docs/assets/frontend-design-audit-20261111/20-replay.jpg) |
| Replay chart "重试" and error line | replay chart workspace | [33-replay-session](../docs/assets/frontend-design-audit-20261111/33-replay-session.jpg) |
| Strategy toolbar "切换" plus native checkboxes | `StrategyResearchApp` toolbar | [21-strategy](../docs/assets/frontend-design-audit-20261111/21-strategy.jpg) |
| Data workbench "添加周期" and fieldset legend | `DataWorkbenchModal` | [37-data-workbench](../docs/assets/frontend-design-audit-20261111/37-data-workbench.jpg) |
| Extension recovery panel | `features/extensions/*`: native `Choose file / No file chosen` in English | [32-ext-recovery](../docs/assets/frontend-design-audit-20261111/32-ext-recovery.jpg) |
| Research dataset management and revisions | `features/research-data/ResearchDataset{Management,Revisions}.tsx` | code scan |

In total, 130 class names referenced in TSX match no CSS rule. Some are JS or test hooks, such as `export-exclude`. The clusters above are real unstyled UI.

A second failure mode sits behind some of these: **borrowing another feature's classes**. Feature CSS is imported by lazy modules, so a component that reuses `.trading-button` or `.chart-time-dialog` without importing their stylesheet is styled only if the user happened to open that other feature first. Primitives with their own CSS remove this whole class of bug.

### 2.2 Overlays and layering (P0)

- **Drawers and modals do not close each other.** Indicators, Alerts, Symbol Search, and Export were all open at once in one session ([04-alerts](../docs/assets/frontend-design-audit-20261111/04-alerts.jpg)).
- **Wrong stacking order.** The Symbol Search modal rendered under the Alerts drawer ([05-symbol-search](../docs/assets/frontend-design-audit-20261111/05-symbol-search.jpg)).
- **Escape is inconsistent.** The Alerts drawer has no Escape handler, and 21 other files each implement their own.
- **Plugin Center swaps out the Settings modal** for a differently designed modal with its own header, its own tab style, and a text "返回" link ([14-settings-plugins](../docs/assets/frontend-design-audit-20261111/14-settings-plugins.jpg)).
- **The Extension Recovery button covers other controls on every page.** It is `position: fixed; z-index: var(--z-modal)` and overlaps the status bar, the Alerts "创建警报" CTA, and the rail's "收起" control. It is a safety tool, but it is permanently on screen. *(Fixed in 3c: it appears only when needed.)*
- **The code reflects this.** There are 26 `role="dialog"` and 8 `<dialog>` implementations with no shared focus trap, scroll lock, or return focus. There are also 9 `window.confirm` and 2 `window.alert` calls.

### 2.3 Typography (P0/P1)

- **P0: CJK font fallback is wrong.** The `--font-sans` stack lists `Malgun Gothic`, `Apple SD Gothic Neo`, and `Noto Sans KR`, but no Chinese font. Chrome's platform-font report for `replay.html` shows Chinese text split between **Apple SD Gothic Neo** (Korean) and **PingFang SC**, sometimes inside one word ("回放训练": 2 glyphs from each). The Korean font covers the KS X 1001 Hanja, so those characters take Korean glyph forms and metrics. This alone makes the whole UI look slightly "off". Windows has the same problem with Malgun Gothic.
- **P1: The type is too small and flat.** `--font-size-xs` (11px) is the most-used size (412 rules, plus 58 literal `11px`), against 137 at 12px. Most panels read as one undifferentiated grey 11–12px block.
- **P1: Monospace in the wrong places.** Watchlist tickers, replay session titles ("成交回放验收 2026-10-11"), and account equity use JetBrains Mono. Mono should be for code, IDs, and aligned numeric columns only. Prices elsewhere should use `tabular-nums` on the sans.

### 2.4 Copy and walls of text (P1)

- **Internal terms shown to users:**
  - "已通过并行影子验收" (passed parallel shadow acceptance) on the exchange list ([11-settings-exchange](../docs/assets/frontend-design-audit-20261111/11-settings-exchange.jpg))
  - "检查 Bundle、信任门… runtime receipt", "仅使用权威 ID", and "独立研究 runtime" on the backtest page ([22-backtest](../docs/assets/frontend-design-audit-20261111/22-backtest.jpg))
  - "dataEpoch a4eedb2cf5c1" in the strategy toolbar
  - "1 × 0 = 0" in the data workbench
- **Raw or untranslated errors:** "Could not read the provider history boundary" in English, shown twice ([33-replay-session](../docs/assets/frontend-design-audit-20261111/33-replay-session.jpg)), and "SUBSCRIBE_FAILED: trade-flow…" in the trade-flow dock.
- **Repetition:** the plugin detail shows "需处理" three times.
- **Long explanations where a label or tooltip would do:** history study (four paragraphs), data workbench, CSV import, and alert steps.

### 2.5 Inconsistent component language (P1)

- **Buttons:** one Settings page shows four button styles (segmented tab, primary, full-width outline, text-in-card) ([12-settings-data](../docs/assets/frontend-design-audit-20261111/12-settings-data.jpg)).
- **Segmented controls and tabs** look different in Settings, Data management, Alerts, Indicators, Replay filters, and Plugin Center.
- **Selects:** 138 native `<select>` elements. Some get the custom chevron, and many show the OS arrow.
- **Badges:** 39 badge, chip, pill, and tag classes. One exchange row carries six coloured pills.
- **Cards inside cards:** Alerts (panel → step card → symbol card → condition card), Data workbench, and Exchange settings.
- **Specificity patches:** `styles/components.css` already forces consistency with `html :is(.st-btn, .alert-btn, …)` overrides and global `!important` rules (37 in `index.css`). That is a symptom of the missing component layer.
- **Inline styles:** 172 `style={{…}}` in 61 files. `IndicatorEditor.tsx` alone has 36.

### 2.6 Generic "AI template" look (P1)

- **The backtest landing page** is the clearest case: an eyebrow, a giant headline, numbered "01–05" cards, a radial glow, a cyan accent used nowhere else, and no app header or navigation ([22-backtest](../docs/assets/frontend-design-audit-20261111/22-backtest.jpg)).
- **The palette is stock Tailwind slate and blue** (`#0f172a`, `#1e293b`, `#2563eb`, `#3b82f6`), not the brand mark's own colours: ink `#07182b`, blue `#1473e6`, teal `#12bfae` (`public/brand/favicon.svg`).
- **Too many 1px borders.** Panels separate content with a border on every container instead of spacing and surface steps.
- **The current muted text fails AA.** `--text-muted` on `--surface-hover` is 4.20:1, although the `tokens.css` header says every text colour reaches 4.5:1.
- **Some components bypass the tokens.** When the token set was swapped for the palette comparison, the alert cards and the exchange status tiles stayed navy, so their colours are hard-coded. These must move onto tokens before any palette change is complete.

### 2.7 Theme model (P1)

- **Choosing 亮色 (light) in Settings only turns the chart canvas white.** The chrome stays dark, and `<html data-theme>` stays `dark` ([50-light-market](../docs/assets/frontend-design-audit-20261111/50-light-market.jpg)). Yet `index.css` has 90 `[data-theme='light']` blocks, and the Settings styles have more. There is an app-level light theme the market page cannot reach.
- **The cause is the Settings scope.** The market page opens Settings in chart scope (`LiveChartCell` passes `appearanceScope: "chart"`), so its 视觉主题 picker writes an override onto the active chart and never reaches the app theme. The full analysis and the fix are in §5.1.
- **The backtest page ignores the theme entirely.**

### 2.8 Shell, layout, and responsiveness (P1/P2)

- **Each page has a different header:**
  - Market: a full toolbar with 15 controls
  - Strategy: different items
  - Replay hub: navigation plus a gear
  - Replay session: 13 controls ([33](../docs/assets/frontend-design-audit-20261111/33-replay-session.jpg))
  - Backtest: no header at all
- **At 1024px wide the right rail takes about 37% of the width** ([60-market-1024](../docs/assets/frontend-design-audit-20261111/60-market-1024.jpg)). Rail tab labels truncate to "交易…" and "只读…", and the status bar truncates "Candle…".
- **English labels overflow.** The English UI truncates the right-rail tabs to "Wat…", "Ord…", "Prof…", "Tra…", "Rea…" and "Coll…", and shows "Controller gro" and "20 lev" in the chart header and order book. Fixed-width controls were sized for short Chinese labels, so the Phase 7 hardening pass must cover the longest supported language as well as narrow widths.
- **The strategy page's right column is mostly empty**, with full-width black buttons and a tiny "高级研究" link-button ([21-strategy](../docs/assets/frontend-design-audit-20261111/21-strategy.jpg)).
- **Replay session cards** have orphaned fields ("完整性" wraps alone onto a second row).
- **The Settings save model is confusing.** "保存代理" sits inside a tab while "保存并关闭" sits in the sidebar, so it is unclear what is saved when.

### 2.9 Styling architecture (enabler)

| Metric | Today |
|---|---|
| `src/index.css` | 15,859 lines, one global file covering every feature |
| CSS shipped as JSX `<style>` strings | `SettingsModalStyles.tsx` 2,437 lines; `DataWorkbenchStyles.tsx` 871 lines (re-injected on every mount) |
| Total CSS | about 23,000 lines |
| Button / modal-family / badge classes | 60 / ~28 / 39 |
| `<Button>` vs raw `<button>` | 5 vs 855 |
| Class names with no rule | 130 |
| `!important` | 37 in `index.css` |
| Transition timings | 8 different durations |

## 3. Design skills: research and recommendation

I checked the primary sources for the main candidates (README and SKILL.md) and the user's Claude plugin catalog.

| Skill | What it is | Fit for CandleScope | Decision |
|---|---|---|---|
| **Impeccable** (pbakaus, Apache-2.0) | Extends Anthropic's frontend-design with 23 commands: `document` (writes `DESIGN.md` from existing code), `critique`, `audit`, `polish`, `typeset`, `layout`, `clarify` (UX copy), `harden`, `extract` (pull components and tokens into a system), `distill`, `quieter`. Ships `npx impeccable detect src/`, a deterministic anti-pattern scanner that runs without an LLM. | Best fit. It is designed for existing codebases, and `detect` can become a CI gate. `clarify`, `distill`, and `quieter` target our copy and density problems directly. | **Install (primary)** |
| **Vercel web-design-guidelines** | Reviews UI code against Vercel's Web Interface Guidelines (accessibility, forms, focus, interaction) and reports `file:line`. Fetches the current rules from GitHub on each run. | A good rule-based review for each migrated surface. It complements Impeccable's taste-driven passes. | **Install (review gate)** |
| **Anthropic "Design" plugin** (in your plugin catalog) | `design-critique`, `design-system`, `accessibility-review`, `ux-copy`, `design-handoff`. | `ux-copy` and `accessibility-review` are useful for the copy pass and the bilingual message catalog. | **Optional** |
| Anthropic **frontend-design** (official) | Direction guide that pushes away from template defaults: explicit palette and type plan, "spend boldness in one place", avoid card kits. | Impeccable already builds on it. Installing both gives overlapping, sometimes conflicting instructions. | Skip (covered by Impeccable) |
| UI Design Review (UXKIN, community, in catalog) | Renders screens at phone and desktop sizes and lists fixes by priority. Optional MCP server with real-product references. | Overlaps with Impeccable `critique`. Very new (2026-11-10). | Skip for now |
| UI/UX Pro Max | Generates a design system from palette and font databases. | Picks from a catalogue, so it tends to produce the stock look we want to leave. Built for new projects. | Skip |
| Taste Skill, Hallmark | Premium marketing and landing-page aesthetics. | Wrong genre for a trading terminal. | Skip |
| Interface Design (Dammyjay93) | Persists design decisions to `.interface-design/system.md`. | Same job as Impeccable's `DESIGN.md`. | Skip |

Install per user (decided 2026-11-12), so nothing is committed to the repo:

- **Impeccable, preferred route:** a Claude Code plugin that installs at user scope and uses the Claude Code-specific build. In a terminal `claude` session, run `/plugin marketplace add pbakaus/impeccable`, then install it from `/plugin`.
- **Impeccable, fallback:** `npx skills add pbakaus/impeccable -a claude-code -g`. This installs the generic shared build rather than the Claude Code one.
- **Vercel web-design-guidelines:** `npx skills add vercel-labs/agent-skills --skill web-design-guidelines -a claude-code -g`

Because every contributor installs their own copy, note the reviewed versions in `DESIGN.md` so reviews stay comparable.

Guardrails for using skills here:

- **Review before installing.** Read each `SKILL.md` and pin the reviewed version; skills are third-party instructions. The Vercel skill fetches its rules from GitHub at run time, so its output can change between runs.
- **Our rules win.** These skills lean toward new projects. The project's `DESIGN.md` (Phase 1) and the token and primitive contract take precedence over skill defaults. Never let a skill introduce new fonts, colours, or one-off component styles outside that contract.
- **Keep the AGENTS.md rules.** Shared UI must stay language-neutral. Pyne stays retired, so never restore Pyne UI while restyling editors or runtime pickers.

## 4. Proposed design direction (to confirm in Phase 1)

A trading terminal earns trust through calm, density, and precision, not decoration. The direction is "instrument panel": the chart is the hero and the chrome recedes.

- **Colour: pick the neutral temperature first, keep one accent.** Three candidates were rendered on the real app through its extension-theme hook, which recolours both CSS tokens and the chart canvas (comparison link at the top). Each changes only the neutrals:

  | Candidate | Surfaces 0 / 1 / 2 / hover | Text primary / secondary / muted | Lowest text contrast | Character |
  |---|---|---|---|---|
  | Current | `#0a0e17` `#111827` `#1a2332` `#253247` | `#e2e8f0` `#94a3b8` `#8794a8` | 4.20:1 (fails AA) | Tailwind blue-grey |
  | **A · Graphite** (chosen 2026-11-12) | `#0d0e10` `#141518` `#1c1d21` `#272930` | `#e9eaec` `#a6a9b0` `#9094a0` | 4.79:1 | Near-neutral; candles and the accent are the only saturated colours |
  | B · Deep Ink | `#06101d` `#0b1727` `#112035` `#1a2d48` | `#e6edf6` `#a3b4cb` `#8ea1bb` | 5.27:1 | Brand navy; richer, but still a blue world |
  | C · Warm Carbon | `#100f0e` `#171615` `#1f1e1c` `#2b2927` | `#eceae6` `#ada9a2` `#97938c` | 4.74:1 | Slightly warm; softer, can look muddy next to red and green |

  The rest of the colour rules apply to every candidate:
  - Brand blue `#1473e6` is the only accent (4.54:1 with white text): primary action, selection, focus.
  - Brand teal `#12bfae` is reserved for the mark and the "live" signal, and is only used where it stays clearly distinct from the user's candle-up colour (test against the defaults and the user presets).
  - Status colours are muted in the chrome so they never compete with candles.
  - Remove cyan as a second accent.
- **Separation by space and surface, not borders.**
  - Three elevation steps.
  - Borders only where a boundary carries meaning (inputs, focus, tables).
  - No cards inside cards.
- **Typography.**
  - Fix the CJK stack first. Use per-language stacks: `:lang(zh)` → `PingFang SC`, `Microsoft YaHei`, `Noto Sans SC`, `Source Han Sans SC`. Korean fonts apply only under `:lang(ko)`. Verified with Chrome's platform-font report: the fixed stack renders the replay heading entirely in PingFang SC, against today's Apple SD Gothic Neo and PingFang SC mix.
  - **Interface font: IBM Plex Sans** (chosen 2026-11-12, from six candidates rendered on the real English UI; see the comparison link at the top).
    - Ship it through `@fontsource/ibm-plex-sans`, replacing `@fontsource/inter` in the five entry files, with the same Latin and Cyrillic subsets.
    - Load weights 400, 500, 600 and 700. Drop 300 unless a screen still needs it.
    - `--font-sans` becomes `'IBM Plex Sans'` followed by the Chinese stack above, so Chinese text still uses PingFang SC or Microsoft YaHei.
    - Plex is slightly wider than Inter. Check the toolbars, rail tabs and order-book controls for new truncation in the Phase 1 snapshots.
    - IBM Plex Sans SC would make Chinese text match too, but it is a multi-megabyte download, so the system Chinese fonts stay.
    - Evaluate IBM Plex Mono as the numeric and code font in Phase 1, since it is designed to pair with Plex Sans. JetBrains Mono stays until that comparison is made.
  - Scale: 11 (captions and badges only), 12, 13 (body), 14, 16, 20, 24.
  - `tabular-nums` for all numbers. Mono only for code, IDs, and order-book columns.
- **Words are interface.** Use task-first labels, one sentence at most, and put details behind "技术详情" disclosures. Map every backend error code to a translated, actionable message.
- **Motion.** Two durations (120ms and 180ms) and one easing. Animate only open/close and confirmations. Honour `prefers-reduced-motion`.

## 5. Target architecture

1. **Cascade layers.**
   `@layer reset, tokens, primitives, patterns, features, overrides;`
   This removes the need for the `html :is(…)` specificity patches and `!important`.
2. **Co-located CSS.**
   - Split `index.css` by feature, next to the owning feature, since Vite already code-splits CSS imported by lazy chunks.
   - Convert `SettingsModalStyles.tsx` and `DataWorkbenchStyles.tsx` into real `.css` files.
3. **Primitive kit in `src/components/ui/`.** Each primitive owns its box, colour, and type. Features add layout only (this is the rule `components.css` already states). The kit: `Button`, `IconButton`, `Field` (label, hint, error), `Input`, `Textarea`, `Select`, `Checkbox`, `Switch`, `SegmentedControl`, `Tabs`, `Badge`, `Section`, `Stat`, `Disclosure`, `Banner`/`InlineAlert`, `EmptyState`, `Dialog`, `Drawer`, `Popover`/`Menu`, `Tooltip`, `Toast`, `ConfirmDialog` (replaces `window.confirm` and `window.alert`), `DateTimeInput` (locale-aware, UTC-labelled), and `FileDrop`.
4. **Overlay manager.**
   - One stack.
   - At most one drawer per side; opening another replaces it.
   - Modals always sit above drawers.
   - Escape closes the topmost layer.
   - Focus trap and focus return, scroll lock, and z-index tokens only.
5. **One `AppHeader`** for all five pages. It has slots for navigation, context (symbol and data source), and page actions, and moves extra actions into an overflow menu at narrow widths.
6. **Guardrails in `npm run check`.** These start in warn mode and become errors in Phase 8.
   - Fail when a class name in TSX has no rule. The audit script can be the starting point.
   - Fail on hex or `rgb()` literals outside `tokens.css`, on new `*-btn` or `*-overlay` class families, on static `style={{}}`, and on `!important`.
   - Run `npx impeccable detect src/ --fast --json` with a findings budget.
   - Add a design snapshot script that captures about 25 named states at 1440×900, 1366×768, and 1024×768 in both themes, reusing the CDP approach in `scripts/smoke.mjs`.

### 5.1 Theme model (decided 2026-11-12)

**Rule.** The theme picked in Settings is the app theme. It styles the whole interface and every chart that follows it. Any chart can have its own appearance instead, and the app theme never overrides it.

**Today**, which is why 亮色 only turned the chart white:

- **The market page can't change the app theme.** Its Settings opens in chart scope, so the 视觉主题 picker writes `theme` onto the active chart (`nextCellChartSettings`). `applicationSettingsPatch` deliberately skips the four appearance keys. Only the `PageSettingsDialog` pages (such as the replay hub) can change the app theme.
- **One label for two scopes.** Both scopes use the label 视觉主题; nothing tells the user which one they are changing.
- **No way back.** Once a chart has an override, nothing shows it and nothing resets it to "follow the app".
- **App-level 自定义 recolours the chrome.** It writes the custom background into the chrome (`--surface-0` and `--surface-1`), not only into the charts.
- **Light custom backgrounds can be unreadable.** A light custom chart background keeps the dark theme's axis text and grid, because `getPaneThemeColors` takes them from the dark defaults.

**Precedence**, first match wins:

1. **The chart's own appearance.** Shared across a link group when chart style linking is on (the existing `chartStyle` link channel).
2. **The app theme:** 深色, 亮色 or 跟随系统. An installed theme extension takes this slot, as it does today.
3. **The default:** Graphite dark.

**Data model.** Mostly in place already. `CELL_CHART_APPEARANCE_KEYS` (`theme`, `customBg`, `upColor`, `downColor`) are optional per chart, and a missing key means "inherit". The changes:

- Remove 自定义 from the app theme options. Custom backgrounds become chart-only.
- Add a reset that deletes a chart's appearance keys, and show when a chart inherits.
- Derive chart text and grid colours from the chart's effective background (light or dark by luminance), so any custom background stays readable.
- Up/down colours follow the same rule: an app default with an optional per-chart override. The chrome (watchlist, order book, trade flow) always uses the app value.

**UI.**

- **Settings is always app scope.** Settings → 外观显示 shows 应用主题 (深色, 亮色, 跟随系统) and the app up/down colours. When overrides exist, a line says "N 个图表使用自己的外观" with a "全部恢复跟随应用" action.
- **Per-chart appearance lives in the chart.** Each chart header menu (the existing "图 N 布局操作" menu) gets 图表外观. Its options:
  - 跟随应用主题 (the default), or 自定义: dark, light or a custom background colour, plus optional up/down colours.
  - A "恢复跟随应用" action.
  - A note "同步到联动组的 N 个图表" when style linking is on.
- **Overrides are visible.** A chart with its own appearance shows a small marker in its header, so it's never a mystery why one chart looks different.
- **No regression in between.** Until the chart menu ships (Phase 4), Settings shows a second group, 当前图表外观, below the app theme. Per-chart themes keep working the whole time. *(Done in 4c: the chart menu has shipped, and Settings no longer shows the group on pages whose charts have a header menu.)*

**Migration.**

- **Keep existing per-chart overrides.** They are user data; the marker and the reset action make them visible. Many were probably created by accident through the old picker. If every chart overrides the app theme with the same value on the first launch after the change, offer once to make that the app theme instead.
- **Convert an app theme of 自定义.** It becomes 深色 or 亮色 depending on its background's luminance. *Changed during Phase 1:* charts that inherited an app-level custom background are not rewritten. Workspace documents live in versioned storage, replay keeps its own copy, and charts in windows that aren't open can't be reached at startup. Those charts follow the converted app theme instead, and the old custom colour becomes the starting value when a chart gets its own background. App-level 自定义 was only reachable from the strategy and replay page settings, so few users are affected.
- **No schema or backend change.** Workspace documents and link groups keep their schema.
- **Moved to Phase 4 with the chart menu:** the "N 个图表使用自己的外观 · 全部恢复跟随应用" line, the one-time offer to adopt a common chart override as the app theme, and the header marker. All three need workspace-wide state that the chart menu work adds. *(Done in 4c.)*

**Related fixes.**

- **Electron window background.** It is hard-coded to `#0b0f14` in `desktop/electron-window-manager.mjs`. Set it from the app theme so light mode doesn't flash dark when a window opens or resizes.
- **The light theme is effectively untested.** It exists in CSS, but the market page could never reach it. It needs a Graphite light ramp (Phase 1) and a full visual pass (Phase 7).

## 6. Roadmap

Each phase lands as one or more reviewable PRs, and ends with before/after screenshots in a `design-qa` note (following the existing root `design-qa.md` convention).

| Phase | Work | Exit criteria | Size |
|---|---|---|---|
| **0. Baseline and tooling** | Add the snapshot script and the unstyled-class scan (warn mode). Install skills. Run `impeccable document` to draft `DESIGN.md`. | Baseline captured for every state; checks report numbers in CI. | 1–2 d |
| **1. Direction and tokens** | Decide palette, typeface, scale, and density (decisions in §8). Tokens v2 (Graphite dark and light), keeping the legacy aliases. Switch the interface font to IBM Plex Sans and fix the CJK font stack. Theme model (§5.1): Settings becomes app scope, the app theme covers chrome and following charts, existing chart overrides are kept and resettable, plus the migration and the Electron window colour. | `DESIGN.md` approved. Chinese text renders in one font family. Switching the app theme restyles the chrome and every following chart. Charts with their own appearance keep it. A light custom chart background stays readable. | 2–3 d |
| **2. Primitives and overlay system** | In three PRs. **2a:** `@layer` and the split of `index.css` into feature files, with no visual change. **2b:** the non-overlay kit (buttons, fields, choices, display) with a dev-only gallery; move `.ui-*` into `primitives`; `Button` replaces `.st-btn`, `.alert-btn` and the plugin center buttons, and the `html :is()` patches go. **2c:** the overlay manager with `Dialog`, `ConfirmDialog`, `Drawer`, `Popover`/`Menu`, `Tooltip` and `Toast`; `window.confirm` and `window.alert` go. Remaining `!important` rules belong to their surfaces and go in phase 5. | Kit documented with a dev-only gallery page; overlay behaviour has tests. | 4–6 d |
| **3. P0 fixes** (parallel with Phase 2 once `Button`/`Field`/`Dialog` land) | Style the surfaces in §2.1. Fix overlay stacking and Escape. Move Extension Recovery into Settings → 插件与扩展 and show a small toast only when an extension has failed or safe mode is on. Translate raw errors. Rebuild the history study as an anchored popover. | 0 unstyled clusters; no overlay overlap; no English strings in the zh UI. | 2–3 d |
| **4. Shell and market workspace** | Unified `AppHeader`. Top bar grouped into symbol, intervals, chart tools, panels, and workspace, with overflow at narrow widths. Rail width rules and label handling. Status bar. Move per-chart appearance into each chart's header menu, with an override marker (§5.1). | Market page reviewed at three widths; header shared by all five pages. | 3–5 d |
| **5. Surface migration** | In order: Settings (Plugin Center moves inside the Settings frame) → Alerts → Indicators and editor → Symbol search → Export → Replay hub and session → Strategy research merged with backtest (§6.1), local data, CSV import → Data workbench → Order book, trade flow, and account docks → Extension manager. For each: primitives only, `clarify`/`distill` the copy, put diagnostics behind disclosures, delete dead CSS. | Each surface passes `critique` and the Vercel review with no P0/P1 findings, plus a before/after snapshot. | 2–3 wk |
| **6. Copy and i18n** | Copy guidelines (zh and en). Extend `describeError` in `i18n/serverErrors.ts` (it already maps coded errors) so uncoded backend messages, such as the replay "provider history boundary" error, also get a translated summary. Glossary that replaces internal terms with user terms. Extend `check-i18n`. | No internal QA or runtime terms in default views. | 2–3 d |
| **7. Polish, accessibility, responsive** | `impeccable polish`/`audit`. Contrast checks in both themes. Keyboard paths. 1024 / 1366 / 1440 / 1920 widths. Reduced motion. | WCAG AA text contrast; every overlay keyboard-operable. | 2–3 d |
| **8. Cleanup** | Remove the legacy `--bg-*` aliases and dead CSS. Switch the guardrails from warn to error. | Targets in §7 met. | 1–2 d |

**Status, 2026-11-12 (branch `design/phase-0-1`).**

Phase 0 is done:

- `npm run design:snapshots` captures 22 named states in each theme and viewport, and its `--compare` mode builds a before/after page. The baseline is in `output/design-snapshots/baseline/`.
- `npm run check:styles` reports the §7 metrics. It warns only and runs inside `npm run check`.
- [`DESIGN.md`](../DESIGN.md) records the decisions.
- The skills are not installed; per-user installation is yours to run (§3).

Phase 1 is done:

- Graphite tokens for dark and light, with every text colour at WCAG AA on every surface including hover.
- IBM Plex Sans with per-language CJK stacks.
- Graphite chart canvas colours, with text and grid chosen by background brightness.
- The theme model from §5.1: app theme versus a chart's own appearance, plus the 自定义 migration.
- The desktop window background follows the app theme.

Not done yet:

- The IBM Plex Mono comparison.
- Moving hard-coded component colours (alert cards, exchange tiles) onto tokens. This now belongs to each surface's migration in Phase 5.

**Phase 2a is done (branch `design/phase-2a-css-layers`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_2A.md`](../docs/FRONTEND_DESIGN_QA_PHASE_2A.md).

- `src/styles/layers.css` sets `reset, tokens, primitives, patterns, features, overrides`; every entry page loads it first.
- `src/index.css` (15,859 lines) became a manifest: 37 new feature files plus `styles/reset.css`, imported after the existing tokens, components, plugin center and extension stylesheets. Feature CSS loaded from JavaScript, the Settings and Data Workbench style strings, Monaco's CSS and extension stylesheets join `features`.
- No computed style changes: `npm run css:cascade` finds no winner change across 23,702 declarations, and a live check that swaps the old CSS in place on the same page found no differing computed value in any snapshot state.
- `npm run check:css-layers` keeps new CSS inside a layer.

Moved to 2b, because each changes how some controls look:

- **The `html :is()` patches.** Moving them to `overrides` changes about 1,300 rule pairs; for example, disabled primary buttons in Settings would look enabled.
- **Removing `!important`.**
- **Moving `.ui-*` into `primitives`.**

Sixteen of the new files hold rules that must load later than their feature's main file, because rules in between depend on the order. Each says so in its header and merges into the main file when its surface is rebuilt in Phase 5.

**Phase 2b is done (branch `design/phase-2b-primitives`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_2B.md`](../docs/FRONTEND_DESIGN_QA_PHASE_2B.md).

- The non-overlay kit is in `src/components/ui`, with styles in the `primitives` layer and a dev gallery at `/ui-gallery.html`. The kit covers `Button`, `IconButton`, `Field` with `Input`/`Select`/`Textarea`/`DateTimeInput`, `Checkbox`, `Switch`, `SegmentedControl`, `Tabs`, `Badge`, `Section`, `Stat`, `Disclosure`, `InlineAlert`, `EmptyState` and `FileDrop`.
- Settings, Alerts and plugin center buttons use `Button`; the `html :is()` patches are gone.
- The chart appearance switch is a `SegmentedControl`, so the faint selected state from Phase 1 is fixed.

**Phase 2c is done (branch `design/phase-2c-overlays`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_2C.md`](../docs/FRONTEND_DESIGN_QA_PHASE_2C.md).

- One overlay stack with these rules: one drawer per side, modals above drawers, popovers above both, Escape closes the top layer, focus returns to the opener, and a modal makes the page inert.
- `Dialog`, `ConfirmDialog` (also `confirmAction()`), `Drawer`, `Popover`, `Menu`, `Tooltip`, and toasts through `notify()`.
- All 9 `window.confirm` and 2 `window.alert` calls are replaced.
- Existing drawers and modals move onto the stack in Phase 3; that is where the overlapping drawers and Escape fixes land.

**Phase 3 lands in three PRs:** 3a puts the existing overlays on the stack; 3b styles the unstyled surfaces (§2.1) and rebuilds the history study as a popover; 3c moves Extension Recovery into Settings and translates the raw errors.

**Phase 3a is done (branch `design/phase-3-p0-fixes`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_3A.md`](../docs/FRONTEND_DESIGN_QA_PHASE_3A.md).

- Every drawer and modal from before the kit is on the overlay stack through `OverlayLayer`, with its own look unchanged. This covers:
  - Alerts, Indicators and Workspace;
  - Settings, with Plugin Center and the data workbench as layers above it, and the page Settings dialog;
  - Symbol Search and the replay launcher;
  - the trading account dialog and the trade journal;
  - plugin dialogs and plugin side panels;
  - the strategy page's research data, saved accounts and run history drawers;
  - the replay page's integrity and results drawers.
- That fixes the §2.2 findings:
  - Only one right-hand drawer is open at a time.
  - Symbol Search no longer opens under a drawer.
  - Alerts, the data workbench and plugin side panels close on Escape.
  - Escape closes one layer at a time.
- Escape now reaches the focused control first, so a field that cancels its edit or a nested picker keeps working inside a layer.

Still outside the stack, and moved when each is rebuilt:

- **Surfaces that open as native modal `<dialog>`s:** Export, jump to date, research return, replay screenshots, and the drawing property panels. The browser keeps them above everything and gives them their own Escape; the stack leaves Escape to them. (The history study moved to a popover in 3b; Export moved onto the stack in 5e.)
- **The replay hub's create and end-session dialogs, and the trade explanation inside the strategy tester.**

**Phase 3b is done (branch `design/phase-3b-unstyled-surfaces`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_3B.md`](../docs/FRONTEND_DESIGN_QA_PHASE_3B.md).

- The §2.1 surfaces are rebuilt from the kit: the event markers and their CSV import, dataset management and revisions, the strategy toolbar's custom interval, the replay hub's resume button, the replay and strategy chart errors, the strategy language picker, and the data workbench's interval group.
- The history study setup is a popover anchored to its top-bar button, on the overlay stack.
- `DateTimeInput` writes times as `2026-01-02 09:30` in every locale and opens the browser's calendar from a button; `FileDrop` has a one-row `compact` form. No bare file input is left on these surfaces.
- Unstyled class names: 110 → 1. The scan no longer counts values compared inside `className` expressions, test and script hooks are declared, and dead modifier classes are gone. The one left is the desktop-only AI control panel in Settings, rebuilt in Phase 5.

**Phase 3c is done (branch `design/phase-3c-recovery-errors`), which completes Phase 3.** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_3C.md`](../docs/FRONTEND_DESIGN_QA_PHASE_3C.md).

- The always-visible 扩展恢复 button is gone. Extensions are managed in Settings → 插件与扩展 → 可信扩展. When an extension fails to load or extensions are off, a notice appears with 管理扩展, which opens the same management in a dialog outside the replaceable slots.
- Extension management is rebuilt from the kit; the English "Choose file" picker is a `FileDrop`.
- `describeError` gives frequent codes a message of their own: the replay "provider history boundary" error and the trade-flow `SUBSCRIBE_FAILED` now read in the user's language, and the replay chart's load errors go through it. Dataset quality statuses and the strategy toolbar's "source bars" and "dataEpoch" are translated.
- Not done here, and moved to Phase 6: internal terms in the replay session (status bar `REPLAY`/`PAUSED`, `AGG_TRADE · EXACT`, `Controller`), "Run" in the replay opening message, and uncoded backend messages, which still show as sent.

**Phase 4 lands in three PRs:** 4a puts every page on one `AppHeader`; 4b groups the market top bar, sets the rail width rules and reworks the status bar, reviewed at 1440, 1366 and 1024 px; 4c moves per-chart appearance into each chart's header menu with the override marker (§5.1).

**Phase 4a is done (branch `design/phase-4-shell`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_4A.md`](../docs/FRONTEND_DESIGN_QA_PHASE_4A.md).

- `AppHeader` replaces `MarketTopBarFrame` on the market, strategy, replay hub, replay session, backtest research and local pages, and the backtest landing page now has a header.
- Regions: brand and navigation, then context and tools on the left; actions, extras, panels and Settings on the right. Settings is always the last control; on the market page it used to sit between the intervals and the panel toggles.
- Page actions are data and collapse into a 更多 menu when space runs out: 历史研究 and 跳转到日期 on the market page, the saved accounts and run history on the strategy page, and the replay session's five actions.

**Phase 4b is done (branch `design/phase-4b-market-shell`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_4B.md`](../docs/FRONTEND_DESIGN_QA_PHASE_4B.md).

- The header compacts by measurement in four steps instead of window-width breakpoints tuned for Chinese labels; English at 1024 px no longer overlaps "Chart strategy" with the intervals or hides the active interval. Every page has the same divider between the navigation and its context, and the strategy page uses the standard brand.
- The right rail keeps the chart at 65% of the window (31% for the rail at 1024 px, was 36%). Its tab strip is 60 px and labels wrap instead of truncating (交易账户, "Trading accounts", "Beobach-tungsliste"). At that width the watchlist keeps change % and drops the exchange badge.
- The status bar drops whole items, lowest priority first, with separators, and uses classes instead of inline colours.
- Moved to Phase 5: panel toggles and Settings on the kit `IconButton` (it has no slot for the indicator count badge yet), and the English truncations inside the chart header ("Controller gro…") and order book controls, which belong to those surfaces.

**Phase 4c is done (branch `design/phase-4c-chart-appearance`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_4C.md`](../docs/FRONTEND_DESIGN_QA_PHASE_4C.md).

- Each chart's header menu starts with 图表外观: 跟随应用主题 or 单独设置, then 深色, 亮色 or 自定义 with its background colour, and 单独设置涨跌颜色. It stays available when the layout is locked or the chart is maximized, on the market page and in the replay session.
- A chart with its own appearance shows a palette marker beside its menu button. Settings → 外观显示 says how many charts have their own appearance, with 全部恢复跟随应用, and no longer shows 当前图表外观 where charts have the menu.
- On the first launch with the menu, if every chart sets the same theme on its own and the app uses another, a notice offers once to make it the app theme.
- The menu is named 图 N 外观与布局 (was 图 N 布局操作) and renders outside the chart cell on the market page too, so small charts in a grid no longer cut it off; it sits under modals and toasts.
- `SegmentedControl` labels wrap (hyphenated where the language allows) instead of running under the next option.

**Phase 5 lands surface by surface** (split decided 2026-11-14), each PR with its own QA note:

| PR | Surfaces |
|---|---|
| 5a | Settings frame: the Plugin Center inside Settings, the save model, 网络连接, 数据管理's library, AI MCP |
| 5b | The rest of Settings: 交易所 (internal terms, pills, tiles onto tokens), 存储与维护, 高级维护, 关于与支持 |
| 5c | Alerts (cards in cards, notifications through `notify()`) |
| 5d | Indicators and the indicator editor |
| 5e | Symbol search and Export (native `<dialog>` onto the kit) |
| 5f | Replay hub: the run list, the create dialog, deleting a run |
| 5f2 | Replay storage management and the initial market picker |
| 5f3 | Replay session controls: the bottom bar, its notices and diagnostics, the end dialog, the capabilities view |
| 5f4 | Replay review and integrity drawer, training results |
| 5f5 | Replay right rail: notes, watchlist, the market data view, the review rail |
| 5f6 | Replay order ticket and account view (positions, orders, fills, assets, risk) |
| 5g | Retire the flag-off fallbacks (standalone local page, research-disabled screen, the library and legacy flags) before the merge (§6.1) |
| 5g2 | Strategy research merged with backtest (§6.1): one page with a mode rail, `?mode=` deep links, backtest.html and local.html open strategy.html in the matching mode, no landing |
| 5g3 | The research tools (精确成交验证, 参数稳健性, Python / 模型, 多市场比较, 交易回放复盘) on the kit |
| 5g4 | The strategy page: script panel, results, run history, first open |
| 5g5 | Local data library and CSV import |
| 5g6 | The strategy tester shared by the market page and the strategy page: language and Python permission, parameters and conditions editors, result context, overview and trade list, the native Pine panel and report |
| 5h | Data workbench |
| 5i | Order book, trade flow and account docks; panel toggles and Settings on `IconButton` |

Each PR also merges its surface's late-loading CSS file into the main one and removes its `!important` rules.

**Phase 5a is done (branch `design/phase-5a-settings`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_5A.md`](../docs/FRONTEND_DESIGN_QA_PHASE_5A.md).

- Settings is one dialog (1080 × 760 at most). The Plugin Center opens inside it as 插件与扩展 instead of replacing it with a differently styled window; its sections are kit tabs with 刷新 and 安装插件 beside them.
- The save model: changes apply as they are made, so 保存并关闭 is gone. The proxy is the one form with its own save, enabled only when there are unsaved edits; 网络连接 shows a dot while they wait, and closing asks before discarding them. Settings stays open while a plugin installs.
- 数据管理 uses kit tabs; the library section lists the local library and the data workbench as two rows, with the workbench text distilled ("SQLite", "VACUUM" removed).
- AI MCP has its own icon; in a browser it is an empty state, and the desktop panel is rebuilt from the kit (it was the last unstyled class name).
- The Settings CSS moved from a 2,364-line `<style>` string, re-injected on every open, into `features/settings/settings.css`.

**Phase 5b is done (branch `design/phase-5b-settings-panels`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_5B.md`](../docs/FRONTEND_DESIGN_QA_PHASE_5B.md).

- 交易所: each exchange is a row with its name and one line of plain text instead of up to six pills and market chips; 当前 and 不可路由 are the only badges. Verification ("已通过并行影子验收", now "已与并行数据比对验证") moved into the technical details, product status is a label/value list instead of tinted tiles, and each market's channel table sits behind a disclosure. The panel's own colour set (including a hard-coded orange) is gone; it uses tokens and kit controls.
- 存储与维护: three storage layers, each with one figure, 预估清理 / 清理 and a 详细数据 disclosure, instead of three walls of tiles; estimates and results are one-line alerts. The hard-coded English labels ("DataManager series", "Script cache", "active/subscribed") are translated. The storage policy uses a segmented control, kit fields and a real table in a disclosure.
- 高级维护 uses the row pattern; results are alerts with per-series detail in a disclosure. 关于与支持 and 外观显示 use kit disclosures, selects and a segmented colour preset.
- Settings has no raw `<select>` or text field left; the raw buttons that remain are the choice cards (themes, proxy modes, storage presets), the sidebar and the exchange rows, plus native colour inputs, which the kit has no equivalent for. `settings.css` is 1,289 lines (2,364 at the start of 5a), and 46 unused message keys are gone.

**Phase 5c is done (branch `design/phase-5c-alerts`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_5C.md`](../docs/FRONTEND_DESIGN_QA_PHASE_5C.md).

- The alerts drawer drops its context card (four tiles repeating the chart header) and uses kit tabs, with the rule count as the 全部警报 badge.
- 添加警报 is four numbered sections instead of five tinted cards with more cards inside; 到期 and 通知 stack instead of sharing a 520 px row; channels are checkboxes with descriptions; the rule test is a closed disclosure; 新建草稿 / 创建警报 stay in a footer. Step descriptions are gone. A custom expiry uses `DateTimeInput`, so it no longer shows the browser's date format.
- Rules and history are rows with ghost actions; the column-label chips that looked like filters are gone; empty states use `EmptyState`.
- Fired alerts go through `notify()`: they show above dialogs and can be clicked while one is open (the 3a known gap), with 打开警报 as the action.
- `alerts.css` went from 1,500 lines to about 370; the late-loading `alertToasts.css` is merged and deleted; 21 unused keys are gone.

**Phase 5d is done (branch `design/phase-5d-indicators`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_5D.md`](../docs/FRONTEND_DESIGN_QA_PHASE_5D.md).

- The indicator drawer uses kit tabs (the count is the 已添加 badge) with 自定义 as a small button beside them. A library row is the name, one line of description and pane, and an add toggle; the 内置 / 主图 / 副图 pills on every row are gone, leaving badges for exceptions (自定义, 行情数据, unavailable in replay).
- Added indicators show their parameters as kit fields, two per row (one in a narrow drawer), with compact colour swatches; errors and notices are `InlineAlert`s.
- The script editor has one toolbar (title and name, actions, close), kit fields, no uppercase labels (they turned `ta.timeframe` into "TA. TIMEFRAME"), and Pine's advanced inputs as closed disclosures with labelled monospace text areas. It had 40 inline styles and has none.
- `indicators.css` went from 957 lines to 437 with no hard-coded colours; the late-loading `indicatorEditorToolbar.css` is merged and deleted; two unused keys are gone.

**Phase 5e is done (branch `design/phase-5e-search-export`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_5E.md`](../docs/FRONTEND_DESIGN_QA_PHASE_5E.md).

- Symbol search: the scope is a segmented control and the five filters one row of labelled kit selects; rows show the market type as text instead of a pill on every line; the 名称 and 数据来源 columns have their own labels instead of borrowed ones; loading, empty and error states use the kit; the footer actions are ghost buttons.
- Export is a kit `Dialog` on the overlay stack instead of a native `<dialog>`. Scope and format are segmented controls with the chosen option's description, the options kit checkboxes, the file name shown once, and the preview's four tiles one line.
- `symbolSearch.css` 700 → 444 lines and `exportPanel.css` 517 → 169, with no hard-coded colours. The kit `Dialog` takes `onKeyDown`, and segments and tabs carry `data-value` for scripts and tests.

**Phase 5f is done (branch `design/phase-5f-replay`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_5F.md`](../docs/FRONTEND_DESIGN_QA_PHASE_5F.md). The replay row was split in three (5f, 5f2, 5f3) when it started: the hub, storage and the session are each the size of an earlier sub-phase.

- The replay hub lists runs as rows (name with a state badge, one line of details, equity, small actions) instead of cards with seven label/value tiles each; the counts strip that repeated the filters is gone; the state filter is a segmented control. A filter that matches nothing offers to clear it.
- 新建训练 is a kit `Dialog` on the overlay stack: numbered sections, choices as segmented controls with the chosen description (no BAR / AGG_TRADE / RANDOM / MANUAL codes as labels), kit fields, UTC dates as `DateTimeInput` text, the advanced part a `Disclosure`, and a summary column. Deleting a run uses the kit `ConfirmDialog`.
- The two hub stylesheets are merged into `trainingHub.css` (582 → 534 lines; it still carries the frame the market picker, storage and status pages use); the old rules that styled bare buttons and inputs no longer reach kit controls. Kit: `Dialog` renders in place without a DOM (like `OverlayLayer`), `Disclosure` can be controlled and take an `id`, `DateTimeInput` takes `earliest`. 12 unused keys are gone.

**Phase 5f2 is done (branch `design/phase-5f2-replay-storage`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_5F2.md`](../docs/FRONTEND_DESIGN_QA_PHASE_5F2.md).

- 存储管理 is a kit `Dialog` instead of a panel above the run list: the release decision and alerts are `InlineAlert`s, each storage category is one row with used / limit and its percentage, and the counts, objects and the source matrix sit in closed disclosures. The cleanup dry run, its confirmation and the verified trade days use kit fields, a checkbox and a danger button; the "keep until" time is UTC text.
- The initial market picker drops its mark, eyebrow and tiles: the run's constraints are one line, the filters are a kit search field, a segmented market type and a checkbox, and markets are rows with venue · interval · coverage and 选择.
- The storage and picker rules move from three stylesheets into `trainingHub.css`; the late-loading `trainingHubMarketPicker.css` is deleted.

**Phase 5f3 is done (branch `design/phase-5f3-replay-session`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_5F3.md`](../docs/FRONTEND_DESIGN_QA_PHASE_5F3.md). The session was split again when it started (5f3, 5f4, 5f5): its review drawer and its right rail are each the size of a sub-phase.

- The bottom control bar is kit buttons, selects and an input: 结束 is a quiet red button, the step buttons a group, 播放 the primary action, the time on the right. "Next base bar" is hidden when it would repeat "next display bar" (the same interval), which showed two identical 下一根 1m buttons.
- The read-only, reconnecting and command-error notices are `InlineAlert`s with their actions; 高级诊断 is a kit `Disclosure` with the fidelity codes as badges.
- Ending a run is a kit `Dialog` on the overlay stack (取消 focused, danger confirm), replacing a hand-built dialog with its own focus trap.
- The capabilities view is one row per capability with a short state badge (精确, 近似, 不可用) instead of a grid of tiles whose state codes overflowed.

**Phase 5f4 is done (branch `design/phase-5f4-replay-review`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_5F4.md`](../docs/FRONTEND_DESIGN_QA_PHASE_5F4.md).

- The 复盘与完整性 and training results drawers share one frame: a header with icon buttons and a scrolling body of sections separated by dividers; the eyebrows are gone.
- 复盘与完整性: the six code tiles are labelled facts (mode and disclosure in words); the rule revision forms and history, the audit events and the proof hashes are folded into disclosures; kit fields and buttons throughout, with 不可逆揭示时间 as a danger button and the review timeline as rows.
- Training results: kit stats and trade rows with side badges and tinted P&L, instead of a nearly unstyled panel.
- About 60 old panel rules (one `!important`, an element rule that restyled every button in the drawer) are replaced by token-based drawer rules.

**Phase 5f5 is done (branch `design/phase-5f5-replay-rail`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_5F5.md`](../docs/FRONTEND_DESIGN_QA_PHASE_5F5.md). The right rail was split when it started: **5f5** the notes, watchlist, market data view and review rail; **5f6** the order ticket and the account view, about 1,850 lines whose source and styles the tests check closely.

- 回放笔记: notes are rows with a 原始记录 / 复盘补记 badge, the market time, the text, links and screenshots, and 编辑 / 版本历史 as quiet buttons; the editor is a kit field with its hint, the link and screenshot pickers use kit checkboxes, errors are alerts and an empty view is an `EmptyState`. Before, the notes had browser buttons, body-size headings and an oversized field label. The rail's subtitle no longer repeats the title (计划与复盘).
- 自选: kit search field; search results are rows that no longer truncate the symbol to "B.. U.. S.."; the selected market has an accent edge; 在新图表打开 is an icon button.
- 市场: kit tabs and panels; 未启用历史盘口 and 当前来源不支持订单流 are empty states instead of amber boxes; trade-flow figures are kit stats.
- Review rail: the "复核 · 只读" eyebrow is a badge, the facts are one list, status notices are alerts.
- About 120 old rules (including element rules that restyled every button in the notes panel and the watchlist) are replaced by 95 token-based ones.

**Phase 5f6 is done (branch `design/phase-5f6-replay-trading`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_5F6.md`](../docs/FRONTEND_DESIGN_QA_PHASE_5F6.md). This completes the replay row (5f–5f6).

- 下单: 开仓 / 平仓 is a segmented control and the order type kit tabs whose panel holds the price and size fields; fields are kit inputs with the unit inside; leverage and the size unit are kit selects; 25–100 % are small buttons; the risk plan is a kit checkbox that opens its fields (before, an oversized label and a browser select); equity and available are stats. Buy and sell keep the user's candle colours.
- 仓位: equity, available and floating P&L are stats; the record tabs are kit tabs with counts; a position is one card with side, margin mode and leverage as badges, its figures in two columns and kit buttons (市价全平 as danger); orders and fills are rows with side, type and status badges; empty tabs are `EmptyState`s; the risk tab is sections with dividers; closed trades, the ledger and liquidation recoveries are kit disclosures.
- The legacy rail stylesheet is gone: about 410 rules for the ticket, the account view and rail markup nothing renders any more (old tabs, tables, chips, the `--replay-rail-*` aliases), including 7 `!important`, are replaced by 99 token-based rules; `replayPanels.css` is down to 42 lines. The liquidation timeline uses global tokens (its `--trade-*` colours were undefined inside the integrity drawer).

**Phase 5g is done (branch `design/phase-5g-strategy-research`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_5G.md`](../docs/FRONTEND_DESIGN_QA_PHASE_5G.md). The strategy-research row was split when it started (5g–5g5), after the product call in §6.1.

- The flag-off fallbacks are retired: the standalone `LocalApp` shell, the `BacktestApp` wrapper, the research-disabled screen, `VITE_RESEARCH_DATA_LIBRARY_ENABLED` (frontend) with every `libraryEnabled` branch, `VITE_BACKTEST_RESEARCH_ENABLED` and `VITE_BACKTEST_LEGACY_WORKBENCH_ENABLED`. `strategy.html`, `local.html` and `backtest.html` always open the one strategy research app. The backend's `CANDLESCOPE_RESEARCH_DATA_LIBRARY_ENABLED` is unchanged.
- No visible change on the default build: the three pages capture byte-identical before and after.
- Tests and `scripts/strategy-research-smoke.mjs` now assert that the fallbacks stay gone, as the repository does for retired Pyne entry points. ADR-BACKTEST-014 carries a dated amendment.

**Phase 5g2 is done (branch `design/phase-5g2-research-modes`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_5G2.md`](../docs/FRONTEND_DESIGN_QA_PHASE_5G2.md). Strategy research and backtest are one page (§6.1).

- A 72 px mode rail at the left edge of `strategy.html`: 快速测试, then 成交验证, 参数稳健, 模型测试, 多市场, 交易复盘. `?mode=` carries the mode; switching rewrites the address without reloading, and the app-control `research-panels` group has a `mode` command.
- The five-card landing page and its 研究任务 button are gone; the rail is the overview. Leaving 快速测试 carries its source, strategy draft and latest result into the tools as a launch context; with nothing to carry, a tool opens with its own defaults instead of refusing (the "需要先选择数据 / 草稿" errors are gone).
- `backtest.html` and `local.html` rewrite themselves to `strategy.html` in the matching mode (`?mode=precise`, `?source=imported`), keeping run, study and context links; links the app builds (chart tester, results, preparation jobs) point at `strategy.html?mode=…` directly. Every URL carries the 策略研究 title.
- Still to do in this row: the research tools' panels and copy (5g3), the strategy page (5g4), local data and CSV import (5g5).

**Phase 5g3 is done (branch `design/phase-5g3-research-tools`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_5G3.md`](../docs/FRONTEND_DESIGN_QA_PHASE_5G3.md).

- The five research tools are on the kit: a segmented chart-source switch, panels as sections with a plain heading and the object in mono, kit fields and buttons (the creating step primary), run and study rows with state badges, raw JSON behind closed 技术详情 disclosures, results as kit stats and tabs (概览, 交易, 信号轨迹, 对比, 数据质量), the Python studio and the status page on kit pieces.
- `backtest.css` (983 lines, only loaded by `backtest.html`, styling the retired workbench) is deleted with the unused `BacktestResultChart`; `backtestResearch.css` is rewritten on tokens. The quick test's external model form moved onto the kit with them.
- Left for Phase 6: the tools' internal terms (`BAR_APPROX`, "Study V2", "Phase 11", "runtime receipt", the status bar's "独立研究 runtime"), epoch-millisecond times; the JSON drafts stay text areas.

**Phase 5g4 is done (branch `design/phase-5g4-strategy-page`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_5G4.md`](../docs/FRONTEND_DESIGN_QA_PHASE_5G4.md). Row 5g6 was added when it started: the strategy tester's pieces are shared with the market page, so they are restyled once for both.

- The strategy page's own pieces are on the kit: first open (template cards, the two ways to start as buttons), the engine switch as a segmented control, the script panel (recent scripts select, tabs, primary 运行), batch sources and the external model as disclosures, results with kit tabs and badges, run history and saved accounts as kit drawers with state badges and a kit comparison picker, and the result replay's controls, stats, notes and traces.
- The dialog that hands a research run back to a market chart is the kit dialog (it rendered unstyled before); `researchReturn.css` is deleted. `strategyResearch.css` is rewritten on tokens for the page, with the library and import rules left for 5g5; its element rules skip kit segments, tabs and link-buttons.
- Left: the shared strategy tester (5g6), imported data's interval strip and event markers (5g5), copy such as run states as codes (Phase 6).

**Phase 5g5 is done (branch `design/phase-5g5-local-data`).** QA: [`docs/FRONTEND_DESIGN_QA_PHASE_5G5.md`](../docs/FRONTEND_DESIGN_QA_PHASE_5G5.md).

- The data library is the kit drawer: datasets and CSV import as kit tabs (the count as a badge), dataset rows with an accent edge for the selected one, the CSV import and trade import on kit fields, file drops, selects and alerts, the maintenance disclosure with quality as a badge and kit stats.
- The header's 打开本地资料库 and the interval chips above an imported chart are kit buttons; the kit button has a pressed style for toggles, and the kit drawer renders in place without a DOM (like the dialog).
- The drawer's element rules are gone; the unused imported-chart empty state and 7 unused strings are deleted. Left: the shared strategy tester (5g6), copy such as raw column names and stage codes (Phase 6).

### 6.1 Merging strategy research and backtest (decided 2026-11-12)

**Today.** The routing is already shared; the experience is not.

- `strategy.html` and `backtest.html` both call `mountStrategyResearchPage`. With the research data library flag on, both render `StrategyResearchApp`.
- `backtest.html` (and the strategy page's "高级研究" button) sets the intent to `advanced`. `StrategyResearchApp` then replaces the whole page with `BacktestResearchApp`. That is why the backtest page has no header, its own five-card landing, its own cyan accent, and only a "返回来源图表" way back.
- The "高级研究" button builds a new URL (`createStrategyResearchAdvancedHref`) and refuses to open without a data source and a draft.
- With the library flag off, `backtest.html` still renders the legacy `BacktestApp` or `BacktestResearchApp` directly.

**Target.** One "策略研究" page.

- **Shared shell.** It keeps the shared `AppHeader` (Phase 4), so the merge lands after the header.
- **Modes instead of a separate page.** A mode switcher replaces the separate destination: 快速测试 (today's default view) plus the five research tools under user-facing names, covering parameter robustness, fill-accurate validation, multi-market comparison, trade replay review, and Python model tests. Six items are too many for a segmented control, so use a compact left mode rail, the same pattern as the market page's right rail.
- **Shared context.** Data source, strategy draft and run history carry across modes. Switching is client-side, with `?mode=` in the URL for deep links, instead of building a new href.
- **No missing-input refusals.** Modes that need a source or a draft show an empty state that says what to pick and offers the picker.
- **No landing page.** The five-card landing goes away; the mode rail is the overview.
- **Plain copy.** Internal terms ("Bundle、信任门", "runtime receipt", "仅使用权威 ID", "独立研究 runtime") are rewritten or moved behind "技术详情".
- **Compatibility.** `backtest.html` and `local.html` stay as compatibility URLs that open `strategy.html` in the matching mode. Keep their bootstrap tests, `scripts/strategy-research-smoke.mjs`, and the explicit rejection of retired Pyne scripts (`AGENTS.md`).

**Product call (decided 2026-11-15): retire the flag-off fallbacks first.** By then the legacy `BacktestApp` was already a 10-line wrapper around the research app; what remained were flag-off fallbacks that no default or start script enabled (the standalone `LocalApp` behind `VITE_RESEARCH_DATA_LIBRARY_ENABLED=0`, the research-disabled screen behind `VITE_BACKTEST_RESEARCH_ENABLED=0` with the legacy flag off). They are removed in their own PR (5g) before the merge.

**Size:** 3–5 days inside Phase 5.

## 7. Success measures

| Measure | Today | Target |
|---|---|---|
| Unstyled class names (excluding declared JS hooks) | 130 | 0 |
| Raw `<button>` outside `components/ui` | 855 | ≤ 20, documented exceptions |
| Distinct button / modal-family / badge classes | 60 / ~28 / 39 | primitives with variants |
| Static inline `style={{}}` | 172 | 0 (dynamic geometry allowed) |
| `!important` | 37 | 0 (except reduced-motion) |
| `window.confirm` / `window.alert` | 11 | 0 |
| Fonts rendering zh-CN text | 2 mixed (Korean + Chinese) | 1 |
| Total CSS lines | ~23k | expected to fall substantially; tracked per phase, no fixed number until Phase 2 shows the real duplication rate |
| Snapshot states reviewed and approved | 0 | all ~25, both themes |

## 8. Decisions

| Topic | Status | Decision or recommendation |
|---|---|---|
| Strategy and backtest | Decided 2026-11-12 | Merge into one Strategy Research page (§6.1) |
| Skill install scope | Decided 2026-11-12 | Per user (§3) |
| Typeface | Decided 2026-11-12 | IBM Plex Sans for the interface, with the Chinese font stack fixed to PingFang SC / Microsoft YaHei (§4) |
| Palette | Decided 2026-11-12 | A · Graphite (§4). The token values are final only after the hard-coded component colours move onto tokens and Graphite is checked on every surface |
| Theme scope | Decided 2026-11-12 | The Settings theme is the app theme and also styles every chart that follows it. Each chart can have its own appearance, including a custom background, which the app theme never overrides (§5.1) |

## 9. Risks and constraints

- **Merge conflicts.** Several contributors land frontend PRs in parallel. Do the mechanical `index.css` split in one short, announced PR with no visual change, then migrate surfaces in small PRs.
- **Tests and smoke checks depend on class names** (for example, `scripts/smoke.mjs` uses `.st-overlay`). Move those selectors to roles or `data-testid` as each surface migrates, and run the full `npm run check` on every PR.
- **Chart colours are applied in JavaScript** (`chartAppearanceSettings.ts`, Lightweight Charts options). Tokens v2 must feed the chart theme, and the runtime `--candle-up` and `--candle-down` overrides must keep working.
- **Lazy chunks must stay lazy.** Import each feature's CSS from its lazy module, not from `index.css`.
- **Desktop shell:** verify Electron (macOS) after Phases 1, 4, and 8.
- **Pyne retirement** (`AGENTS.md`): restyling editors and runtime pickers must not bring back Pyne entry points or labels.

## Appendix: how the audit was done

- **App setup:** backend `uvicorn app.main:app` in LIVE mode, Vite on `127.0.0.1:15173`.
- **Screenshots:** a headless Chrome over CDP captured 35+ states at 1440×900 and 1024×768: every Settings tab, each drawer and modal, all five pages, the replay session, the chart strategy tester, the rail docks, the data workbench, history study, extension recovery, and the light theme. The 16 most informative are in `docs/assets/frontend-design-audit-20261111/`.
- **Code metrics:** greps over `frontend/src`, plus a script that cross-references every `className` in TSX against every selector in `.css` and `*Styles.tsx`.
- **Font evidence:** CDP `CSS.getPlatformFontsForNode` on `replay.html` headings, paragraphs, and buttons.
