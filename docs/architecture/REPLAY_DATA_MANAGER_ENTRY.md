# Replay sequences and run operations through MarketDataManager (#166)

This frontend migration adds `MarketDataManager.replay` and connects the
production multi-chart replay display path, run controls and adapter streams. It reuses `SeriesWindowStore`,
`ReplayChartProjection`, `ReplayTapeViewer` and their existing reveal/ordering
contracts. It does not replace the replay engine or financial calculations.

## Ownership and calls

`ReplayApp → ReplayDataProvider → MarketDataManagerCore.replay` owns one namespace
per replay document. The live `MarketDataManager` extends this same lifecycle
core. Replay imports only the core, which has no live feeds, network ports or
cache fallback. Existing architecture checks still reject transitive live
transport imports from the replay entry; no allowlist exception is added.

Each `ReplayChartProjection` creates an inert sequence candidate. The committed
React effect retains it; abandoned renders retain no manager entry. The identity
contains run, track, adapter session, data epoch, source generation and display
interval. Even equal identities get distinct mutable windows because each chart
owns its paged history and viewport. Replay rows never enter `SharedMarketCache`.

Server display projections and tape projection/history requests enter the
sequence's request lease. Caller cancellation, identity replacement, last release
and manager shutdown abort only that sequence's requests. A late response from a
transport that ignored abort is rejected by the captured local epoch, including
release/reacquire with the same server identity. Existing response identity,
reveal-boundary and source-sequence checks still run in the replay adapters.

`ReplayDataProvider` handles StrictMode effect replay without terminally closing
the retained manager. Final unmount closes it. Diagnostics at
`window.__CANDLESCOPE_REPLAY_DATA__.snapshot().replay` expose active sequence
identity, consumers, row count and pending/total requests; they contain no account
or order state. `MarketDataManager.diagnostics().replay` is also available in live
workspaces, independently of their market cache.

## Run and adapter operations

`ReplayTrainingRunApp` retains a run-entry operation for loading/preparing its
run. `useReplayViewerRuntime` retains a separate run-scoped operation for viewer
and track state, play/pause/step/trade commands, progress, advisory requests,
preparation and its training-run stream. Selection of another adapter inside the
same run keeps this operation alive; a run change/unmount releases it. Layout
effect retention precedes passive request effects and supports StrictMode replay.

The shared adapter pool receives this same manager and the owning run ID. Each
`ReplayRuntimeLifecycle` owns one adapter operation for capabilities, session
validation, commands/recovery, report/journal and its canonical stream. Chart
consumers still share one adapter connection and retain the existing controller
lease rules. Restart replaces requests/streams within the same operation;
last-consumer disposal releases the operation.

Operation leases contain no rows, account state or order state. Typed API
bindings enclose the complete parsed promise, so an HTTP response whose headers
arrived before cancellation cannot publish a late body. The API clients retain
their own command IDs, envelope serialization, retries, validation and ordering;
the manager neither deduplicates commands nor adds retries. Stream resources have
an additional per-open fence: callbacks and heartbeats from a stopped stream
cannot resume after another stream opens on the same operation. Final release
also stops registered resources even if their owning effect has not cleaned up.
Diagnostics include active operations, pending/total requests and active streams.

## Scope still open

This is not full dual-Manager acceptance. Hub/initial-market preparation, review
and rail-specific API consumers, indicator/history providers outside the managed
cell path, and the backend DataManager facade remain follow-up work. Native
saved-cursor/full-exit/restart, disconnect recovery and financial reference
acceptance also remain open. No #166 checklist is
declared fully passed by this patch.

The base includes #175 and #173. The separately developing #174 B130 public-block
PR and #147 seconds-history draft were checked before implementation; neither
supplies this replay lifecycle namespace. This phase changes no backend storage,
aggregation, download or revision authority.
