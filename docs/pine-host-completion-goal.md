# Pine host completion goal

Status: active, narrowed by user-authorized direction relayed on 2026-10-19
from the disk-space conversation. Preserve all completed work. Current scope:
**save a traceable checkpoint, align CandleScope with freshly verified main,
then trace and qualify replay watermark propagation end to end** (cross-market,
market type, smaller requested timeframe, 128/628 windows where applicable,
retry/recovery, and effective FX input visibility). The original broad goal
below remains background; its feature expansion is deferred.

Do not resume new core semantics, rich-order/intrabar integration, new rendering
destinations, parallel cold-load performance work, or GC work. GC PR58 remains
HOLD, unmerged and disabled. Do not opportunistically merge account/log/extension
PRs. Verify current remote main and preserve its funding-cohort correctness;
old `a89cd25b` test results do not qualify the new combined revision.

User originally requested goal mode, CandleScope first, then interpreter work
directly in `E:/projects/pine-interpreter`. The current phase honors the narrower
priority above; core is frozen at `b9200480e` and has no new source modifications.

## Source identities and boundaries

- Host: existing `codex/pine-host-adaptation` worktree, base `a89cd25b`.
  Preserve all preceding phase 1/2 changes; original dirty main is untouched.
- Core: `E:/projects/pine-interpreter`, new `codex/pine-host-completion`,
  clean starting revision `b9200480e`. This includes six newer local commits;
  phase 2's old `28ecae3c` core baseline is no longer the latest development core.
- Published plugin/runtime catalogs remain release artifacts, not development
  capability evidence. Test new engine bytes in an isolated candidate environment.
- Core stays host-neutral; data acquisition, scheduling, rendering, and external
  notification delivery belong in CandleScope.

## Ordered work ledger

The pending feature items below are **deferred** by the scope narrowing above.

1. Implemented and locally tested: indicator cross-exchange and declared finite dynamic/nested
   request contexts, inherited chart selectors, exact market type, missing-data
   diagnostics, no automatic backfill and confirmed remote-bar filtering.
2. Chart strategy imports implemented, frozen into revision dependency identity
   and validated in the installed isolated evaluator. Imported price-grid usage
   is now included in native analysis. Host-matching workbench also accepts libraries.
   Pending: chart strategy requested data, rich orders and intrabar scheduling using the authoritative
   host matcher, never reinterpret native fills as host fills.
3. Pending: remaining rendering destinations and supported symbol/session/chart
   metadata. Preserve unsupported diagnostics until the actual UI is wired.
4. Schema 3 effective currency input implemented for indicators, native runs,
   preparation and fixed-history replay. Explicit quote currency metadata is
   supported; no automatic FX source is inferred. Actual batch/replay/seek and
   host-matching library integration tests pass against an isolated installation
   of the current `b9200480e` core wheel. Pending broader product acceptance.
5. Pending: core gap re-audit against **current** source and fixtures, then implement
   selected remaining language/request/account gaps with Rust/Python/WASM gates.
   Currency conversion is already present in current development core;
   nonunit contract multipliers are still unsupported.
6. Pending: broad regressions, durable evidence and review of final changes.

## Current checks

- Current complete bridge + indicator-host suite: 75 passed, 12 skipped
  (separate Renko event extension). Old schema-2-only and currency-blocked
  expectations were updated; unsupported-financial rejection is retained.
- 8 actual isolated chart/provider/transport tests, including changed library
  content and restored authoritative account execution.
- 3 actual installed native integration cases: imported Magnifier replay,
  FX batch/replay/seek, and frozen libraries under CandleScope matching.
- 46 backend regressions pass; 8 separate optional plugin cases were skipped in
  that run, so the three explicit installed cases above were run separately.
- 31 frontend tests, UI typecheck and 30-locale catalog validation pass.
  Advanced native inputs now survive draft restoration, including incomplete
  JSON edits; selected datasets are still revalidated before freezing a run.
- Playwright component harness verified explicit context entry, invalid JSON
  feedback and correction, state updates, and zero browser errors after load.
  Screenshot: `output/playwright/pine-goal-data-inputs.png`; helpers stopped.
  This is component validation, not packaged-app acceptance.

Currency safety follow-up: scripts with declared account currency or reads of
currency-dependent metadata require actual quote-currency metadata. CandleScope
host matching rejects foreign-account conversion because its authoritative ledger
does not implement that conversion; native execution can use explicit rates.
Binance `usdm` indicator identity now uses the perpetual `.P` alias, and inherited
provider requests map back only to the proven chart storage instrument.

## Acceptance boundary

Local implementation and tests do not establish arbitrary TradingView script,
pixel, broker-fill, protected-library, or live-tick equivalence. Preserve separate
categories for unsupported core semantics, unconnected host capabilities, missing
external data/service access, and unqualified official-reference behavior.
