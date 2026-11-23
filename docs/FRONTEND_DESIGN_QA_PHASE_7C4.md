# Frontend design refactor: Phase 7c4 QA (Spanish, French, and the replay hub's status)

- Date: 2026-11-18
- Branch: `design/phase-7c4-es-fr`, based on `design/phase-7c3-cjk` (PR #472)
- Plan: [`frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md`](../frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md), Phase 7 (row 7c4)
- **Intended visible change:** in Spanish and French, the parts that still showed English now show the language: continuous research runs and history repair, trade history, replay notes, the history study, the read-only account, trading accounts with their journal, quick replay and statistics, the native strategy backtest with its report, comparison and drawing objects, support settings and AI MCP, "Go to date", data preparation, the replay hub's welcome and random start, search, and the proxy settings. In every language, the replay hub's run status ("Training can continue" and three others) is in the reader's language; it was the server's Simplified Chinese text. In the narrow rail, the tape's two filters share the row by what they hold, so the Spanish bubble threshold is no longer cut.

## What changed

| Area | Change |
|---|---|
| Spanish feature file | New `catalogs/spanishFeatureMessages.ts`: the seven feature blocks (continuous research with its return, batch, repair and reader parts; trade history; replay notes; history study; read-only account; trading accounts; native strategies), 1,218 messages typed against the English blocks and imported only by `es.ts`. |
| French feature file | New `catalogs/frenchFeatureMessages.ts`: the same seven blocks, 1,218 messages, imported only by `fr.ts`. |
| Inline English | 123 Spanish and 139 French messages translated in place: go to date, data preparation, the replay hub, search, the proxy and WebSocket settings, drawing settings. Values that read the same in the language (Volume, Position, Script, Mode, Error, No…) are left as they are. |
| Duplicates | 27 English duplicates of the native block (`aiControl.*`, `settings.category.ai`) that overrode it in `es.ts` / `fr.ts` are removed. |
| Replay hub status | `trainingRunStatusLabel` (`trainingHubLabels.ts`) maps the server's status codes `READY`, `AWAITING_MARKET`, `UNAVAILABLE` and `HEDGE_INPUT_RECOVERY_REQUIRED` to catalog messages; an unknown code still shows the server's text, and an ended run is still described by whether its review opens. The hub row and the "can't continue this run" error both use it. Four new keys, `replay.hub.status*`, in all 30 catalogs; Simplified Chinese keeps the server's wording. |
| Tape filters | In the narrow rail (below 340 px) the tape's two filters shared the row in equal halves, so in Spanish "Burbujas" left its select too little room: "≥ $100K" lost its last character, and "Desactivado" (bubbles off) was cut by 17 px. Already the case before this branch. The two now share the row by content (`tradeFlow.css`), and Spanish "off" is "Ninguna" (none), as the select is the bubbles' threshold. |
| Terms | Spanish (tú, Spain usage): operación, ejecución (fill and run), vela, financiación, comisión, patrimonio, libro de órdenes, conjunto de datos, deslizamiento, reproducción, revisión, diario. French (vous): transaction, exécution, bougie, financement, frais, capitaux, carnet d’ordres, jeu de données, glissement, relecture, revue, journal, plateforme. |
| Plan | Row 7c4 records the order of the 17 languages left, two per PR from 7c5. |

## Results

Messages shown in English, counted on the resolved catalogs (every key of the English catalog whose value is the same English text with two or more words):

| | Base (Phase 7c3) | This branch |
|---|---|---|
| Spanish | 1,113 | 14 |
| French | 1,130 | 27 |
| Other languages | unchanged | unchanged |

What is left reads the same in the language on purpose: names (Binance USD-M, Python Studio, Heikin Ashi, Line Break, Hong Kong, in French New York and Tokyo), MFE / MAE, AI MCP, TP / SL, Maker / Taker, the search example "BTC, ETH, SOL…", and in French the words French traders use as they are (Take profit, Stop loss, long / short, Average True Range, ATR auto, Volume (VOL), Transparent, Minute (UTC), page and cache).

The replay hub's run status, in every language: the four codes the server sends have a message in all 30 catalogs, so the row reads "Training can continue" in English, "El entrenamiento puede continuar" in Spanish, "L’entraînement peut reprendre" in French, and so on; Simplified Chinese reads as before ("训练可继续"). A code the app does not know still shows the server's text.

`npm run design:layout` in Spanish and French: 23 states × 4 widths = 184 visits per build, dark theme, writes refused.

| | Base (Phase 7c3) | This branch |
|---|---|---|
| Findings | 54, 51 with the full text on hover | 50, 47 with the full text on hover |
| Without the full text on hover | 3: the Spanish tape's bubble threshold at 1024 px | 3, the same; this audit ran before the fix below, which was measured instead (see Known gaps) |

On the base, 1 visit (the history study, Spanish, 1920 px) did not reach its state because the study loaded late; on this branch, 2 (Spanish 1024 px, French 1366 px). They were not run again with a longer wait (see Known gaps); the study's other visits (7 of 8 on the base, 6 of 8 here) reached it.

- **The tape's bubble threshold, Spanish, 1024 px** (the rail's tape, trading accounts and the tester, which leave the tape open): the select showed "≥ $100K" without its last character, and "Desactivado" (bubbles off) was cut by 17 px. The two filters split the narrow rail in equal halves and "Burbujas" is the longest label. They now share the row by content, and "off" is "Ninguna". Measured after the fix in ten languages, every option of both selects fits.
- The rail's accordion summaries ("Posiciones, diario y revisión", "OKX · Perpetuos con margen en USDT y en cripto · …", "Positions, journal et revue") are cut with an ellipsis and their full text on hover, as in English; on the base, the English summaries were cut the same way.
- The order book's status ("Resincronizando", "Resynchronisation", "Reconectando") gives way at narrow widths with its text on hover, as in Phase 7c.
- The rest is data: the dataset select and source name ("okx futures BTC-USDT-SWAP 1m …"), and the research panel's "no run selected" line at 1024 px, which has its text on hover.

## Screens

None this time. The local backend these captures need stopped answering a few minutes after each start (see Known gaps); only five of the ten "before" captures were taken, and an unpaired set says nothing, so none are included. What the screens would have shown is in Results: the counts, the hub status and the tape filters' measurement.

## Verification

- `npm run check` passed: architecture, plugin platform, i18n (30 locales, 5,434 keys, placeholders match in every catalog, no internal terms, no Simplified characters or mainland terms in zh-TW), style metrics, cascade layers, types (each new block lists every key of its English block), lint (one warning, in `SingleChartPanes.tsx`, which this branch does not touch), 5,199 + 1 tests (three new for the hub status: English, French and Chinese wording; an unknown code keeps the server's text; an ended run is described by its review), 137 desktop tests and the build.
- The build puts the Spanish text only in the `es` chunk (364.65 kB) and the French only in the `fr` chunk (375.18 kB). The main `index` chunk is 989.27 kB (988.50 kB in Phase 7c3): English and Simplified Chinese ship in it, so their four status messages and the status mapping are there.
- The translations were generated from tab-separated files (`output/i18n/7c4/`, not in the repository) by a script that refuses a missing or extra key, a changed placeholder or an empty message, keeps each block in its English key order, and, for keys a catalog already had in the language, reuses that translation. The four status messages were inserted in every catalog by a second script from one table.
- The tape's filters were measured in the narrow rail (1024 px) in Spanish, English, French, Polish, German, Italian, Portuguese (PT), Russian, Japanese and Arabic: every option, not only the one selected, fits its select.
- `npm run design:layout` in Spanish and French, as in Results (`output/design-layout/7c4-before/`, `7c4-after/`).

## Known gaps

- **No native-speaker review** of the Spanish or the French.
- **The other 17 languages** still spread the English feature blocks: Phase 7c5 onwards.
- **No screens, and the layout audit of this branch predates the tape fix.** After the two full audits, the local backend began taking 15–55 minutes to start, at full CPU on its own SQLite and history-archive work, and stopped answering a few minutes after each start. So the re-audit of the tape states with the fix, the history study's three missed visits with a longer wait, and the before/after screens were not done. The tape fix was checked by measuring the selects in ten languages instead; the history study was reached in 7 of its 8 visits on the base and 6 of 8 on this branch.
- **Spanish uses one word for a fill and a run** ("ejecución"), as the catalog already did ("Historial de ejecuciones", "Órdenes / ejecuciones"); context separates them. French does the same with "exécution".
