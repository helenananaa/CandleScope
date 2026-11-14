# Frontend design refactor: Phase 5g5 QA (local data library and CSV import)

- Date: 2026-11-15
- Branch: `design/phase-5g5-local-data`, based on `design/phase-5g4-strategy-page` (PR #422)
- Plan: [`frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md`](../frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md) §6.1 and the Phase 5 rows. Contract: [`DESIGN.md`](../DESIGN.md#pages-with-modes)
- **Intended visible change:** the data library drawer (datasets, CSV import, trade import, the selected dataset's maintenance), the data source in the header and the interval chips above an imported chart use kit controls on tokens. What they do is unchanged.

## What changed

| Area | Change |
|---|---|
| Drawer | The library opens in the kit drawer (title, close icon, full height) instead of a floating card with a 关闭 button. |
| Datasets | 本地数据集 / 导入 CSV are kit tabs, with the dataset count as the tab's badge instead of a "数据集库 / 本地数据集 / 2 个" header. Each dataset is a row (name, symbol · interval · kind, rows in mono, gaps), the selected one with an accent edge and `aria-current`. No datasets is a kit empty state. Both tab panels stay mounted, so a half-filled import form survives a look at the library. |
| CSV import | A heading with "数据只写入本机" under it; the file picker is the kit file drop with the chosen file's name; fields are kit fields (required ones marked), the column mapping is kit selects in a bordered preview with the first rows in mono; errors are danger alerts; "作为…的新修订导入" is a kit checkbox; 导入到本地资料库 is the primary button; the progress row has a quiet 取消导入. The CSV import now comes first and the trade import follows it as a disclosure. |
| Trade import | A kit disclosure with the same fields, the expected columns in mono and the kit file drop. |
| Maintenance | 质量 · 修订 · 项目包 is a kit disclosure. Quality is a bordered section with its status as a badge (已通过 green, gaps amber) and the four figures as kit stats. Revisions, archive and trash keep their kit rows. |
| Header | 打开本地资料库 (and 使用当前图表 where offered) are kit buttons. |
| Intervals | The interval chips above an imported chart are kit buttons with the selected one pressed; the custom interval, anchor and calendar options were already on the kit. The kit button gained a pressed style for toggle buttons (`aria-pressed`), which the result replay's drawing tools from 5g4 now show too. |
| Kit | `Drawer` renders in place without a DOM, like `Dialog`, so the drawer's server-rendered tests still see its content. |
| Styles | The drawer's element rules (raw buttons, inputs and selects, focus, the submit colour) are gone with the raw controls; the library, import, quality and interval rules are rewritten on tokens in `strategyResearch.css`. The unused imported-chart empty state (component, CSS and copy) is deleted; the live chart's loading and error states are kit states. |
| Copy | No new strings; 7 keys nothing uses any more are gone (the empty imported chart's title and hint, the library count, and four uppercase kickers). |

## Screens

The base build (Phase 5g4, `12f9fe3d1`) and this branch, 1440 px, `zh-CN` unless marked, on the local library (okx BTC-USDT-SWAP 1m and binance ETHUSDT 1m). The CSV preview uses a 12-row sample file handed to the file input in the page; nothing was imported.

| | Before | After |
|---|---|---|
| Library | ![](assets/frontend-design-phase-5g5/drawer--before--dark.jpg) | ![](assets/frontend-design-phase-5g5/drawer--after--dark.jpg) |
| Library (light) | ![](assets/frontend-design-phase-5g5/drawer--before--light.jpg) | ![](assets/frontend-design-phase-5g5/drawer--after--light.jpg) |
| Library, English | ![](assets/frontend-design-phase-5g5/drawer-en--before--dark.jpg) | ![](assets/frontend-design-phase-5g5/drawer-en--after--dark.jpg) |
| Maintenance | ![](assets/frontend-design-phase-5g5/manage--before--dark.jpg) | ![](assets/frontend-design-phase-5g5/manage--after--dark.jpg) |
| Maintenance (light) | ![](assets/frontend-design-phase-5g5/manage--before--light.jpg) | ![](assets/frontend-design-phase-5g5/manage--after--light.jpg) |
| CSV import | ![](assets/frontend-design-phase-5g5/import--before--dark.jpg) | ![](assets/frontend-design-phase-5g5/import--after--dark.jpg) |
| CSV import (light) | ![](assets/frontend-design-phase-5g5/import--before--light.jpg) | ![](assets/frontend-design-phase-5g5/import--after--light.jpg) |
| CSV import, English | ![](assets/frontend-design-phase-5g5/import-en--before--dark.jpg) | ![](assets/frontend-design-phase-5g5/import-en--after--dark.jpg) |
| CSV preview | ![](assets/frontend-design-phase-5g5/preview--before--dark.jpg) | ![](assets/frontend-design-phase-5g5/preview--after--dark.jpg) |
| Trade import | ![](assets/frontend-design-phase-5g5/trades--before--dark.jpg) | ![](assets/frontend-design-phase-5g5/trades--after--dark.jpg) |
| Imported chart (header, intervals) | ![](assets/frontend-design-phase-5g5/chart--before--dark.jpg) | ![](assets/frontend-design-phase-5g5/chart--after--dark.jpg) |
| Imported chart (light) | ![](assets/frontend-design-phase-5g5/chart--before--light.jpg) | ![](assets/frontend-design-phase-5g5/chart--after--light.jpg) |

## Verification

**In the running app** (headless, 1440 px): `strategy.html?source=imported` opened the drawer on the library; the maintenance disclosure loaded quality, revisions and project actions (GET); the 导入 CSV tab showed the form, a sample file produced the column mapping and preview; the trade import opened; choosing a dataset closed the drawer onto the chart with its interval chips. Nothing that changes data was run: no import, rename, archive, trash, revision switch, or project import or export.

**Tests:** the research-data, local-data, strategy-research, kit, backtest, app-control and app tests pass (662). `researchDataLibrary.test` now looks for the selected dataset's `data-active` and `aria-current` instead of an `active` class. The hooks are kept: `research-data-drawer` (now on the drawer's content), `research-source-card-*`, `research-dataset-rail`, `research-dataset-*`, `research-data-import-form`, `research-market-trade-import`, `local-import-progress`, `research-dataset-quality`, `research-dataset-management`, `research-dataset-revisions`, `research-data-source-bar`, `research-source-use-current-chart`.

**Style metrics** (against 5g4): class names with no CSS rule 0 (unchanged), raw `<button>` 454 → 446, `<Button>` uses 305 → 311.

**Full check:** `npm run check` passes: 5,165 frontend tests, 137 desktop tests, lint (one existing warning), the i18n, style and architecture checks, both typechecks and the build.

## Known gaps

- **Copy (Phase 6):** the column mapping's labels are the raw field names (`time`, `open`, …), the import progress shows its stage code (`uploading`), "OHLC-only" is English, quality states other than the two named ones show their code.
- **The drawer covers the header** at full height, as the kit drawer does everywhere; before, it floated 12 px in from the edges.
- **Native date-time fields** in the trade import keep the browser's own format (`dd/mm/yyyy, --:--`).
- **Desktop app:** not tested.
