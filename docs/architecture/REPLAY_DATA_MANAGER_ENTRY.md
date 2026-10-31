# Replay display sequences through MarketDataManager (#166)

This first frontend migration adds `MarketDataManager.replay` and connects the
production multi-chart replay display path. It reuses `SeriesWindowStore`,
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

## Scope still open

This is not full dual-Manager acceptance. The source adapter pool/stream,
run-level play/pause/trade controls, other replay API consumers and the backend
DataManager facade still use their existing entry points. Routing those through
the Managers, plus native saved-cursor/full-exit/restart, disconnect recovery and
financial reference acceptance, remain follow-up work. No #166 checklist is
declared fully passed by this patch.

The base includes #175 and #173. The separately developing #174 B130 public-block
PR and #147 seconds-history draft were checked before implementation; neither
supplies this replay lifecycle namespace. This phase changes no backend storage,
aggregation, download or revision authority.
