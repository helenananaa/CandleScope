# Bounded OI history on main261

Product source `4db5bdaab44db6d1dcede58292812ff121c5d175` follows integration
`cf25a8d15e27eae0f0611e8b382554d3ac9e38de`, with actual main261
`0de39f37f2389b09a35fc91e3a6d8d5844137da8` above prior #218
`30e3f9626d0e13f475991b5d8de16da8c85660e7`.
The sole merge conflict was the macOS workflow test list: retain all4 OI/market
suites and main's native-second-exchange test. No check was removed.

## Physical ownership defect and correction

The last OI waiter unlinked its singleflight request before awaiting cancellation
of its storage task. The physical read could still hold an actual SQLite/WAL
snapshot, while service shutdown and the32-query budget only counted the now-
absent joinable requests. Shutdown could return early and new admission omit the
still-owned storage work.

A separate same-revision Git archive of the pre-fix integration source, plus the
identical final regression file, reproduces **3 actual failures**: shutdown loses
successful/failed physical reads; and31 new queries plus1 retiring read incorrectly
admit a33rd job. The archive/extra test-script hashes and command/environment are
in baseline-command.json. Complete local-only capability/bootstrap first, then
hold the actual SQLite connection; no public transport is invoked.

The service now tracks joinable requests and physically owned OI jobs separately.
Unlinking the last waiter still prevents new callers joining a cancelling task,
but its job retains ownership/capacity until physically done. Shutdown drains the
owned set, including retiring reads. The existing diagnostics retain inflight and
add owned_jobs. No changes to query receipts, source timestamps, finality, policy
revision, sparse coverage interpretation or market-data values were required.

## Current checks

- **406 backend passed / zero skipped / 6 existing warnings** in one combination:
  OI lifecycle/local history, actual default factory/durable writer/HTTP contract,
  metrics storage, market service/API, history policy, main native-second-exchange
  regressions, current continuous/source/controller and executor/profile checks.
  The23-test focused pass is included, not added to this count.
- Full `npm run check` exited0: **4891 regular tests,1 independent performance
  check,130 desktop tests; zero skipped**. Architecture/plugin/i18n, TypeScript,
  lint and production Vite build completed. Existing SingleChartPanes ref-cleanup
  lint warning and large-chunk build warning remain.
- Backend architecture retains the same10 findings as actual main261; it is not
  architecture-clean. Precise source/helper/tree hashes and commands are retained.

Initial direct lifecycle attempts had a cold capability/bootstrap timeout before
the first worker entered; those are not treated as ownership counterexamples.
The isolated baseline initially lacked backend/scripts/plugin_sdk_isolation.py
and ran no tests. Both setup failures remain in logs. Adding the same-revision
test scripts and warming local-only bootstrap outside the timed ownership phase
produced the three real baseline failures; the same test bytes pass after the fix.
No product assertion or32-job budget was relaxed.

## Prepared, unlaunched Native candidate

The current arm64 APFS clone uses the previously verified main250 runtime,
current tracked backend/SDK, newly built frontend/desktop, updated ASAR integrity
and deep ad-hoc signature. **1064 source files,164 built files,9 plugin assets,
76 plugin source files match; zero mismatches; deep strict signature passes.**
Packages/requirements/pinned-fork inputs are unchanged from prior #218; verified
plugin wheels/core are reused, not rebuilt. This is a local candidate, not a fresh
standalone runtime build/CI installer. No profile exists and it has not launched.

Set CANDLESCOPE_BATCH1_QA_ROOT to a fresh owned output root,
CANDLESCOPE_QA_RUNTIME_SOURCE to the retained verified main250 app, and
CANDLESCOPE_QA_REUSE_VERIFIED_PLUGINS=1; use the qualified Python launcher for
assemble.py, then node verify.mjs. The adjacent original22-stage native driver
retains its public cooldown guard, futures/catalog-ready baseline, all-field
cold SQLite witness, receipt/source-value checks, real pane save, two complete
owned quits and restart comparison. Only its QA directory references changed;
node --check passed, but no Native assertions were executed this round.

Actual Native retry requires a fresh profile, no active owned app, and the global
public gate: **not before2026-11-06T10:12:49.286Z**. Set
CANDLESCOPE_PLAYWRIGHT_PACKAGE to the retained native-tooling-20261106/package.json
and CANDLESCOPE_QA_PYTHON to the qualified launcher. Old sourcefc7f44f9's22-stage
public Native result stays attached to that old source; current4db5bdaa still
needs its own source-matched Native save/full-owned-quit/restart result.

All24 pre-existing dirty QA files and their checked-out local PR branch remain
unchanged. This clean integration branch will advance only the remote PR by
fast-forward. Windows was independently unreachable at the MCP gateway429,
without any command reaching its host. Broader149 channels, old backfill/delete/
revision fencing, cross-process acquisition coordination and broader performance
qualification remain open. Keep Draft. CI runs in the background; main merging
needs exact final head/current base checks and corresponding product evidence.
