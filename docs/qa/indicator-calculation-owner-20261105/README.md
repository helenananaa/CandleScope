# Retained calculation ownership foundation

Source `bfcb36b7bc056da5ab4d47b38e4163f11b44f5ce`, based on #227 head
`f4c4638a45175995c1a9592eabbb80e49ad97337` / main `18cd6f34`.

**This is an internal runtime/service foundation. The chart HTTP/WS routes and
frontend are not yet bound to it. #227 Native remains unqualified and the prior
500→202 counter witness remains an unresolved acceptance counterexample.**

## Implementation

`RuntimeSupervisor.read_output` reads the already-held bounded SDK patch-base
projection. It sends no IPC, changes no engine state and never starts/restarts a
worker on a missing replica. A reference binds supervisor-instance epoch,
process generation, stream and output revision. Reads use the same lock as
executeBatch. The output is borrowed read-only; no second full output or input
history is retained, and it is not a calculation checkpoint/as-of result.

The language-neutral `ScriptCalculationOwner` retains only a fixed plan,
generation/sequence/source cursor and at most eight admitted task handles.
Cancelled callers cannot release physical ownership. A source fence after
execution blocks publication. Changed source revisions, missing replicas or a
runtime reset from an incomplete tail require explicit full-origin rebuilding.
A rebuild gets a fresh runtime epoch and must actually reset; an unchanged
forming observation is not counted again as a continuation. Older cursors and
wrong-owner output cannot become current. Close drains admitted work before
releasing dependencies, including under cancellation.

`PineCalculationRuntime` binds this owner to the existing
IndicatorRuntimeService / registered sidecar / SDK / qualified core. It keeps
source, parameters, series semantics and execution policy in the identity, and
gives request dependencies the calculation owner's lease ID. Notifications are
deferred until successful source-fenced publication, under the same owner;
reading cannot execute or notify. Notification failure cannot replay valid math.
Other languages are not silently relabelled or admitted by this Pine binding.

The legacy/default indicator execution path keeps its existing notification
behavior. No existing historical cache identity, historyLimit, finite warmup,
HTTP standalone/no-future semantics, SDK wire protocol, engine source or plugin
package is changed. Frontend and package product diffs are empty.

## Actual evidence

- `regression.log.gz`: **81 passed / 1 existing warning / zero skips**. Includes
  14 new real Pine/ownership cases plus supervisor, runtime service, input/output
  patch, script patch shape and standalone batch regressions.
- `observation.json.gz`, produced by `observe_domain.py`: actual current
  repository plugin/SDK through the registered runtime and indicator service,
  using the qualified copies-venv launcher and core **0.3.3+cs.1**. No provider,
  mathematical output or sidecar response is mocked. `core-identity.json` records
  the executable, prefix and installed core location/version.
- A cumulative `varip` script gives **500 → 501 → 502** through seed and two
  forming observations; an explicit rebuild gives **501**. Ten reads after each
  phase leave actual supervisor request counts unchanged: **3/3, 4/4, 5/5, 6/6**.
  The valid independent 201-bar historical calculation gives **201**, proving
  why its output must not be merged into this retained chart calculation.
- Tests cover negative-offset series/collections, distinct chart streams, old
  revisions, restarted/replaced supervisors, cache eviction, cancelled read
  waiters, bounded pending work, source amendment/fencing, nonoverlapping tails,
  unapplied resets, publication observers and owned cleanup. The two observation
  worker processes exited normally (code 0) and their PIDs were independently
  absent. This is component-process cleanup, not desktop full-quit acceptance.
- All **39 pre-existing dirty QA files** retain their exact pre-edit hashes.
  Original failed Native profiles/responses/assertions were not overwritten or
  staged. Only this new QA directory is added.

## Lifecycle follow-up

[The bounded registry and explicit stream-release follow-up](lifecycle.md) is
qualified on product/test source `1f9ada60`: 145 backend, 185 SDK, 240 Pine
passed (one existing core-capability skip in Pine). It adds application ownership
and durable per-stream cleanup without binding chart HTTP/WS/frontend. Earlier
81/104-test and observation claims above retain their original source identities.
The original Native counter failure remains unresolved.

## Remaining production integration

1. Bind one bounded, application-owned calculation instance to a chart's explicit
   source/parameter/series identity and calculation origin. HTTP and WS must
   acquire the same owner and dependency leases, not create independent state.
2. Make chart range views read that owner's current projection with cursor
   checks. Keep standalone/as-of historical APIs separate and unchanged. Missing
   output is an explicit recovery condition, never a short warmup fallback.
3. Connect initial hydration, ordered live updates and full-origin source
   correction to that same owner. Left expansion changes the formal origin and
   requires explicit owner/generation replacement with an atomic full snapshot.
4. Add frontend domain/generation/sequence acceptance so delayed HTTP or WS
   messages cannot mix calculations. Preserve independent charts and saved
   configuration/restart behavior; do not call a display replica a checkpoint.
5. Re-run actual service+renderer cases, then source-verified Native original
   monotonic/parity/negative-offset deletion/marker/bgcolor assertions, save,
   full owned quit and restart. Windows and the remaining #152 performance and
   materialization scope stay separate.

The next step is this production wiring, not increasing warmup or removing
historyLimit from the old cache identity. No main merge/CI or Native pass is
claimed for this foundation.
