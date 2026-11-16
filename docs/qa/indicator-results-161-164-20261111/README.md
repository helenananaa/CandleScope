# Common indicator result ingress (#164 / #161)

Base: `12514a92fb4cc8745e3564538dd68247316e019d` (`origin/main`, 2026-11-11).
Branch: `codex/indicator-results-161-164`.

## Delivered boundary

`IndicatorDataManager.results` owns the workspace result ingress. Browser JS,
explicit provided-bars compute, hosted snapshots/patches/ranges/final points,
and speculative warming enter the same service before immutable cache commit.
The architecture check rejects production imports of the low-level result
writers outside that service. Existing read, invalidation, range coverage,
revision, active lease and GC contracts remain in the result cache.

The browser controller captures a result task before dispatch, including the
full projection key, job key, input/lifecycle predicate and coordinator epoch.
Retired tasks cannot revive when a textual selection key returns. Results are
still checked against the current definition at publication. A cache commit
checks the workspace input owner and input revision before notifying result
subscribers. A failing subscriber cannot fail another consumer's computation.

The existing chart cache remains an ID-retargeted, independently rendered
projection. A separate bounded semantic cache retains successful JS worker
envelopes before chart IDs are attached, enabling a later compatible view to
reuse an already completed computation. It is workspace-owned, with an 80-entry
and 4 MiB encoded key/output budget; oversized output executes without becoming
resident. Count and encoded bytes are diagnostic bounds, not a whole-process
heap measurement. Existing projection-cache and worker budgets also apply.

Semantic equality includes the exact script, language, parameters, full market
identity and complete supplied OHLCV content/finality. It uses exact semantic
serialization rather than a script/window digest as an equality proof. Input
dependency stamps retain revisions, not row arrays. Amendments, disconnect,
eviction and workspace recreation revoke reuse. Explicit force bypasses
completed results. Errors and forming/unknown-finality samples are never
retained as completed semantic results.

Projection definition keys also use exact serialized identity. The old
same-length 32-bit script signature collides for valid programs ending in
`// Aa` and `// BB`; the regression proves that the second script cannot hydrate
the first projection or publish through its captured task. A separate regression
closes the microtask race between a completed-cache hit and workspace disposal.

Forming samples retain the existing closed-prefix preview policy, so a busy
market cannot starve JS. Their raw envelopes are immutable; a superseded sample
cannot certify a cached result. A script's window origin remains part of its
identity. This does not equate window-relative recursive JS with a hosted or
long-history mathematical seed.

## Runtime adapter matrix

| Contract | Builtin | Frontend JS | Pine | Python |
| --- | --- | --- | --- | --- |
| Execution owner | Existing hosted history worker / live subscription; explicit-local remains opt-in | Existing bounded opaque-origin sandbox Worker | Existing installed Pine runtime and chart calculation session | Existing installed Python indicator plugin |
| Input identity/version | Full series; hosted server revision plus observed prefix; explicit provided input separately keyed | Full series, exact bounded bars/finality/origin, source stamp | Full series, script/params; chart calculation origin, domain/generation/sequence/input revision and observed prefix | Full series, script/params, server revision and observed prefix |
| Definition | Engine and canonical parameters, including effective VOL colors | Exact source/language/parameters; input origin | Source/language/security/parameters, private chart projection | Source/language/security/parameters, private chart projection |
| Result ingress | `results.snapshot/patch/replaceRange/point` | `results.publishCompute` then task-checked `results.snapshot` | Same snapshot/patch/range/point ingress after existing session admission | Same snapshot/patch/range/point ingress after existing stream/range admission |
| Compatible sharing | Existing equivalent-demand broker and builtin stream sharing | Exact-input in-flight broker and completed semantic results, retargeted to each view's IDs | HTTP work may share only under its existing contract; stateful live sessions and projection owners remain private | HTTP work may share only under its existing contract; live script sessions and projection owners remain private |
| Incompatible inputs | Full semantic series/definition and provided origin remain separate | Script/parameter/market/interval/origin/content/finality difference prevents reuse | No cross-session substitution of standalone warmup output for a retained calculation | No cross-session substitution of result state |
| Cancellation/release | Existing logical consumers; last consumer releases physical work | Each chart owns its signal/task; one cancellation leaves the survivor; last cancellation cannot warm late output | Existing `ChartCalculationSessions` and logical stream release | Existing logical stream/request release |
| Correction/recovery | Prefix/revision invalidation, existing range recovery | Input stamps revoke semantic and projected results; new current demand computes | Existing generation/CAS rebuild and stream/range recovery precede common commit | Existing server revision and stream/range recovery precede common commit |
| Prewarm | Existing bounded hosted range route | Existing window prewarm now commits through the same result service | Existing language protocol capabilities only; no new shareable retained-session warmup is asserted | Existing language protocol capabilities only; no new shareable live session is asserted |

Community runtime languages remain descriptor-routed; the adapter description
does not introduce a closed language union or a second execution router. Pyne
publication is explicitly rejected. Historical data/evidence is preserved.

Market health and result health stay distinct. `results.read` reports result
availability/input validity and stale segments; it does not certify source
freshness or whole-range coverage. `ChartDataFlowManager.health` continues to
report source continuity/freshness separately from result coverage. Existing
indicator errors, computing state and degraded realtime state remain separate
from the K-line connection status.

## Validation and evidence

- Full frontend `npm run check`: 5,074 functional tests, one isolated performance
  gate and 134 desktop tests passed, zero skips; architecture/plugin/i18n,
  both TypeScript projects, ESLint and production build passed. The existing
  `SingleChartPanes` effect-cleanup warning and large-bundle warning remain.
- Final-source targeted cache/result regressions: 40 passed; affected
  indicator/data-flow/architecture suite: 394 passed before the additional
  collision case (the full run includes it).
- Chromium: 16 functional scenarios passed, zero remaining worker targets,
  zero renderer exceptions, normal browser exit.
- Backend runtime/transport suites: 70 passed; all 12 gated installed-adapter
  cases passed with the isolated registry; Python plugin: 48 passed.
- `source-manifest.json` binds changed code/check/fixture files to their
  SHA-256. Raw check and runtime logs are gzip-compressed without editing.

The committed receipts/logs beside this document identify each executed suite.
The production-minified Chromium fixture exercises real React/chart lifecycle
and opaque-origin JS workers with controlled exchange/hosted transports. Its
added BTC/ETH × 1m/5m matrix checks cold/hot result reuse across IDs, changed
recursive origins and corrected input. Existing cases cover prewarm, independent
viewports, one-consumer cancellation, shared builtin streams, late joins,
reconnect, divergent parameters, sparse input and backend range waits.

The backend source suites exercise actual Pine IPC and retained output ownership,
plus HTTP/range/WS adapters and builtin batch execution. Python plugin tests
exercise its actual author/executor/runtime path. The pinned Pine binary used
for those tests is `0.3.3+cs.1`, SHA-256
`7223c7c80e5cf17141466fead4ddd7a1257d185dfddbd7d386d1b5599d8897a9`.
Its retained build lock matches this checkout's engine recipe commit
`c0ecc3bde5eece9c4f2a63c6785aec9c5e571acc` and patch hash
`53cc3758f4fb575d02e00094b5b8a29ff35e2992eddd57273ff72b1af6485ec3`.
Repository bridge and SDK code are installed from this worktree, not an old
user plugin profile.

Commands (from `frontend/`, `backend/`, and repository root respectively):

```sh
npm run check
node scripts/frontend-script-integration.mjs --indicator-flow --out /tmp/cs-indicator-161-164-browser-delivery
../.venv/bin/python -m pytest -q tests/test_indicator_calculation_owner.py tests/test_runtime_owned_output.py tests/test_indicator_runtime_transport_routing.py tests/test_indicator_compute_batch.py tests/test_indicator_runtime_routes.py tests/test_indicator_ws_resume.py tests/test_chart_pine_contracts.py
.venv/bin/python -m pytest -q packages/candlescope-plugin-python-indicator/tests
```

The first backend run has 70 passes and 12 installed-adapter skips. Enabling
those 12 contract cases initially selected an old user-profile adapter and
failed with missing `chart_strategy`; that configuration failure is retained.
Setting `CANDLESCOPE_NATIVE_RUNTIME_REGISTRY` to a test-owned registry pointing
at this worktree's interpreter and current installed bridge produced 12 passes,
zero skips. No user registry/install was modified. Python plugin tests produced
48 passes. The isolated registry path is ephemeral; recreate it with schema 1,
runtime `candlescope.pine-compat`, package `candlescope-plugin-pine-compat`,
version `0.4.0`, executable `<worktree>/.venv/bin/python`, args
`["-I", "-m", "candlescope_plugin_pine_compat"]` and this worktree as working
directory; set `NATIVE_TEST_PINE_PYTHON=1` for the gated contract tests.

An initial Chromium run passed all its functional assertions but failed cleanup
with one remaining worker target. That failed receipt is retained. A clean-base
comparison passed; the final candidate including the added real-worker matrix
also passed with zero remaining workers and zero renderer exceptions. No worker
cleanup source change or relaxed cleanup deadline is attributed to this work.

Scope is the common result contract and supported adapters. This evidence is
not a new installed-release save/exit/restart qualification, Windows acceptance,
GPU/whole-app retained-memory benchmark, arbitrary-script equivalence proof or
language protocol/persistence completion. #120/#152/#153/#154/#170 retain their
separate implementation and acceptance ownership. Merge and issue closure must
retain these evidence boundaries.
