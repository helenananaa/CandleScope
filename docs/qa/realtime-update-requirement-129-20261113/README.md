# Preserve declared updates before producer throttling — #129

Base `6f590578a8e5e7bb52407c295d8d5a693b35cf91`; product
`11e39c2864cf24266ffe0c52c1a2b09929f6aabf`.

## Contract and change

DataManager.subscribe(preserve_updates=True) already preserves distinct pending
observations in EventBus. The aggregator's earlier global UPDATED throttle could
discard them before that queue. Default DataManager/real bridge/SQLite regressions
reproduce both exact and wildcard cases on unchanged main: only [101] arrives
instead of [101,102,103] (before.log).

The publisher now asks a synchronous language-neutral requirement provider before
throttling enabled updates. DataManager binds it to the existing exact/wildcard
EventBus routing index, complete semantic identity and live subscription flags.
An active preserving consumer that requests BAR_UPDATED requires every enabled
update. Closed-only, unrelated, recovered/terminal and removed consumers do not.
Regular consumers retain the existing producer throttle. Explicitly disabled
producer events remain disabled. Lookup failures preserve enabled input, emit a
diagnostic and increment update_requirement_errors; required_updates_unthrottled
counts attempts that bypass the throttle, not completed delivery acknowledgments.

No second subscription index, queue, timer, source lease, network connection,
payload copy or global throttle change is introduced. The demand lookup snapshots
only matching exact/wildcard consumers; a no-global-scan test includes unrelated
preserving subscriptions. The existing queue recovery/backpressure contract is
retained. Source acceptance, numeric reduction, close/amend and persistence paths
are unchanged. This establishes a necessary input-demand boundary for future
coalescing; it does **not** implement deferred preview computation or its scheduler.

## Source and real runtime checks

Final focused contracts plus real HTTP/WS/Pine calculation transport suites:
**74 passed, one warning**. The initial expanded test had a harness-only misuse
of SeriesKey's constructor for a foreign identity; the corrected test uses its
existing create factory. The first runtime invocation had 46 failures because
the test interpreter lacked pine-compat-runtime, not because of changed results.
The qualified 0.3.3+cs.1 wheel is reused from the retained native 0.4.0 bundle;
its SHA-256 matches that bundle's installation receipt. Provenance, failed logs
and the final complete result remain archived. The wheel is retained locally,
not copied into this evidence directory. No retired Pyne runtime is installed.

Final CCXT/backend integration selector: **2063 passed, 63 warnings**. Architecture
passes. The non-Pine demand/routing suites are part of that selector; actual Pine
transport cases are added to the existing four-platform qualified Pine host job,
which builds the pinned core before running them. No case is silently skipped
because the ordinary CCXT job lacks a Pine binary. Cloud checks are separate
merge gates; receipts from each platform remain host-contract evidence rather
than native desktop UI acceptance.

The initial Windows host job ran all test bodies successfully (222 passed, one
skipped) but reported 47 teardown errors: the newly included transport fixture
used POSIX `os.kill(pid, 0)` as a process-absence probe. Windows can retain a
terminated process PID while its handle is open, and this signal API is not an
appropriate read-only termination probe there. The fixture now checks a Windows
SYNCHRONIZE handle with a zero-timeout wait, closes that handle, and still requires
every runtime's normal exit code to be zero. POSIX retains its absence check.
A real child-process regression distinguishes a live process from a terminated
one while retaining the Popen object/Windows handle. The corrected transport and
demand suites pass 74 cases locally; that additional process-probe regression
also passes independently. This is a test-observation correction, with no product
or packaged backend change. The original Windows log is retained.

```sh
CANDLE_DATA_DIR="$PWD/output/requirement-tests" PYTHONPATH=backend python -m pytest -q backend/tests/test_preview_update_requirements.py backend/tests/test_event_bus_routing_index.py
# With the qualified core installed, also run test_chart_calculation_*.py.
python backend/scripts/ccxt_contracts/integration.py --timeout=90
python backend/scripts/check_architecture.py
```

## Controlled policy cost

Fresh process per case/variant, complete old backend versus product, same Python
3.12.15/macOS arm64. Default DataManager is registered but not started; its bridge
is inactive and a callback observes publisher output. This isolates policy and
snapshot dispatch, not source normalization, reducer work or consumer execution.
Two warm plus seven timed 512-attempt windows use a simple changing-volume state.

| Case | Emitted of 512, old → new | CPU median µs per attempt, old → new |
| --- | ---: | ---: |
| Regular consumer | 1 → 1 | 8.71 → 18.39 |
| Explicit preserve_updates | 1 → 512 | 8.60 → 36.11 |
| 64 unrelated preserving consumers | 1 → 1 | 8.90 → 18.44 |

Regular/unrelated payload hashes match; the preserving case intentionally differs
because the old publisher loses 511 requested observations. Correctly doing that
work costs more. The ordinary path adds a scoped identity/demand lookup; this is
not a CPU reduction, stable latency, RSS or application performance pass. Full
samples, counters and hashes are in the cost JSON files.

## Native package observations

The same macOS arm64 app overlays all 1000 committed backend/app files on the
retained frontend/runtime/plugin bundle from build
ef8f0e0fa6df299a823f4460b701eb1c3c98361f, then is ad-hoc sealed. All backend
hashes match both the checkout and app; asar and deep strict signatures match
before/after. This is assembled-backend qualification, not a fresh frontend or
release build. All profiles are fresh/empty, public OKX BTC-USDT spot, no seed
history or response replacement. Existing local proxy 127.0.0.1:7897 is process
only, default HTTP timeout 8 seconds; no system network settings change.

Ordinary configuration completes 45m/90m explicit deep history, unchanged 500-row
1m/5m readiness, recreation, save/full process exit/restart with **3450 closed-bar
nine-field comparisons**, actual source frames at all three checkpoints, saved
workspace and complete owned-process exits. Screenshots and raw receipts are kept.

An additional **instrumented** run sets the existing ordinary throttle to 10000ms
and adds one public wildcard read-only DataManager subscriber declaring
preserve_updates=True. A QA-only import hook installs that observer after normal
module loading; it does not change application files, producer values, responses
or numeric execution. It requests no additional stream lease. A bounded scalar
tee records publisher attempts and matches public callback fingerprints; it is
not a second source subscription or parallel ingestion/write path.

Both sidecars register at 10000ms. **All 116 recorded attempts match 116 callbacks
in series order**, including 45m/90m bursts within the ordinary throttle interval;
no shutdown tail is excluded and the 256-attempt-per-process cap is not reached.
That instrumented workflow independently passes the same 3450 closed comparisons
and save/restart gates. Counts from overlapping runs are not summed. This is
observed enabled-update preservation, not performance/endurance, every raw
network tick, or completed canonical-delivery acknowledgment qualification.

The first witness launch did not forward the two new environment variables
through the retained driver's explicit environment whitelist. It completed the
ordinary flow but created no witness, so it is not accepted as demand evidence.
That attempt is preserved. The driver now forwards only those explicit QA
settings. The initial verifier's weaker final-second-prefix report is retained;
the final verifier checks all 116 attempts without that exclusion. Runtime warning
logs and remaining ledger work are kept; a workflow pass is not a clean-log claim.
Only ephemeral contextToken strings are redacted; active_read_tokens counts remain.

## Remaining original scope

#129 remains open. Deferred forming computation, bounded dirty scheduling and
watermarks, all semantic barriers/consumer modes, state retention/reconstruction,
history-prefix initialization and full resource/performance/runtime matrices
continue. This input-preservation prerequisite does not complete those phases or
#126/#127's remaining requirements.
