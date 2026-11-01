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

## Remaining frontend API entry points

The run context now reaches nested chart/review/rail consumers before their viewer
metadata is available. Hub list/create/preparation/storage, initial-market and
watchlist catalogs, integrity/review/fork/drawings/report, equity/account records,
public time and trade flow all use typed operation bindings. The Hub acquires its
lease on start or first actual request, so opening creation before loading the
list remains supported without retaining resources during construction.

BAR history keeps its original physical-read sharing key and fetcher. Each
consumer owns the complete read/parse/retry operation, including backoff; releasing
one consumer does not cancel a sibling's shared physical read. Tape providers and
canonical indicator calculations enclose their complete retry/compute operation.
Indicator scope and run replacement cancel old requests and suppress late partial
results. Standalone injectable providers retain a direct request default; all
production consumers supply a manager request boundary. Replay capability checks
opened from a live workspace use that workspace's replay namespace, not live data.

Portfolio exports are explicit file downloads, independent of transient chart/view
leases. The managed API exposes the validated URL for browsers. Native applications
use a trusted main-frame IPC command that accepts only a run ID; the host constructs
the fixed loopback portfolio-export endpoint and starts Electron downloadURL. This
streams the existing NDJSON attachment without relaxing navigation protection or
accumulating it as a renderer Blob. UI data loading still uses operation leases,
but leaving a chart does not cancel an already requested file.

During reconnect/resync, a paused or ended actor with no catch-up events may
reissue its current atomic snapshot with a historical fast-forward status reason.
The client accepts that handoff only when sequence, revision, virtual time, source
cursor and state hash all equal its accepted authority. A reset on an established
stream still requires its original atomic progression. Epoch, backward-state,
causality and payload checks remain enforced.

## Scope still open

This is not full dual-Manager acceptance. The backend DataManager facade remains
follow-up work. Native
saved-cursor/full-exit/restart, disconnect recovery and financial reference
acceptance also remain open. No #166 checklist is
declared fully passed by this patch.

The integration base includes #175, #173, #174 B130 and #183 H127, plus the #178
shared-input changes. The #147 seconds-history draft remains separate. This phase
changes no backend storage, aggregation, download or revision authority.
