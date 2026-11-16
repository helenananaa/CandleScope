# Frontend design refactor: Phase 5g QA (retire the strategy-research fallbacks)

- Date: 2026-11-15
- Branch: `design/phase-5g-strategy-research`, based on `design/phase-5f6-replay-trading` (PR #417)
- Plan: [`frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md`](../frontend/FRONTEND_DESIGN_REFACTOR_PLAN.md) §6.1 and the Phase 5 rows
- **Intended visible change:** none on the default build. The flag-off fallbacks behind the strategy research page are removed, so the merge (5g2) and the restyling after it have one path to change.

## Decision

§6.1 left one product call open: is the legacy backtest path still needed? It was decided on 2026-11-15 to retire the fallbacks in their own PR before the merge. The survey found the legacy `BacktestApp` was already a 10-line wrapper around the research app, so there was one backtest interface. What remained were fallbacks that no default value or start script turned on:

| Flag setting | What it opened |
|---|---|
| `VITE_RESEARCH_DATA_LIBRARY_ENABLED=0` on `local.html` | The standalone `LocalApp` page (277 lines) |
| `VITE_RESEARCH_DATA_LIBRARY_ENABLED=0` on `backtest.html` | The research tools without the strategy page |
| `VITE_RESEARCH_DATA_LIBRARY_ENABLED=0` on `strategy.html` | The strategy page with the library and import hidden |
| `VITE_BACKTEST_RESEARCH_ENABLED=0` and `VITE_BACKTEST_LEGACY_WORKBENCH_ENABLED=0` | A "research disabled" screen |

The split of the rest of the row: **5g2** the merge (one page with a mode rail, `?mode=` deep links), **5g3** the research tools on the kit, **5g4** the strategy page, **5g5** local data and CSV import.

## What changed

| Area | Change |
|---|---|
| Bootstrap | `strategy.html`, `local.html` and `backtest.html` always render `StrategyResearchApp` with the page's launch intent. `resolveStrategyResearchBootstrap` and its local-legacy / backtest-legacy routes are gone. |
| Removed files | `LocalApp.tsx`, `BacktestApp.tsx`, `BacktestResearchDisabled.tsx`, `researchDataFlags.ts`. No other module lost its last user. |
| Library flag | Every `libraryEnabled` prop and branch is gone from `StrategyResearchApp`, `StrategyResearchRuntime`, `StrategyResearchShell`, `StrategyResearchFirstOpen`, `ResearchDataSourceBar` and `ResearchDataDrawer`: the library, the import card and 打开本地资料库 are always offered. |
| Backtest flags | `isBacktestResearchEnabled` and `isBacktestLegacyWorkbenchEnabled` are removed; `backtest-main.tsx` mounts the page with no flags. `VITE_BACKTEST_RESEARCH_ADVANCED_ENABLED` (the research tools' own switch) is unchanged. |
| Configuration | `.env.example` drops `VITE_BACKTEST_RESEARCH_ENABLED` and `VITE_BACKTEST_LEGACY_WORKBENCH_ENABLED`; `start-local-offline.ps1` and `.sh` stop setting `VITE_RESEARCH_DATA_LIBRARY_ENABLED`. The backend's `CANDLESCOPE_RESEARCH_DATA_LIBRARY_ENABLED` is unchanged. |
| Copy | 10 keys only the removed screens used are gone from all 30 languages (8 `local.*` keys from the standalone page, `research.disabled.title` and `.detail`). |
| Docs | ADR-BACKTEST-014 hard boundary 7 carries a dated amendment. The execution plans and evidence reports that describe the flags are historical and unchanged. |

## Verification

**Screens:** `strategy.html`, `backtest.html` and `local.html` were captured on the default build (1440 px) before and after; the images are byte-identical, so they are not repeated here.

**Tests:** the strategy-research, research-data, local-data and backtest tests pass (438), and so does `scripts/strategy-research-smoke.mjs`. The tests that asserted the fallbacks existed now assert that they are gone:
- `strategyResearchRelease`: the flag file does not exist; the launch module has no fallback routes; `.env.example` sets none of the three flags.
- `strategyResearchLaunch`: the bootstrap renders `StrategyResearchApp` for every page and names no retired fallback; `backtest-main.tsx` reads no backtest flags.
- `strategyResearchOrchestration`: import and Run polling are not reimplemented in `StrategyResearchApp` (it used to check `LocalApp` and `BacktestApp`).
- `strategyResearchOffline`: the offline launchers no longer set the flag.
- `strategyResearchState`: the source bar always offers the library (the flag-off rendering check is gone).
- `backtestIsolation`: the two flags are not exported, and `BacktestApp.tsx` and `BacktestResearchDisabled.tsx` do not exist.
- `localAppShell` and `researchDataLibrary`: `LocalApp.tsx` does not exist; interval selection keeps its storage key.
- The smoke script fails if any of the four removed files comes back, or if the bootstrap names a fallback.

**Full check:** `npm run check` passes: 5,163 frontend tests (one fewer: a test that only covered a removed fallback route is gone), 137 desktop tests, lint (one existing warning), the i18n check, both typechecks and the build.

## Known gaps

- **Anyone running with a retired flag set to 0** now gets the full page. No default, start script or release config sets them.
- **Desktop app:** not tested.
