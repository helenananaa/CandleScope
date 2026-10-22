# Causal Renko requests in historical Pine streams

`candlescope.pine-event-requests/1` binds event rows to a frozen physical source
and its authoritative close times. The runtime advertises this capability only
after checking exact bounded-cohort and append-feed semantics and the presence
of Core's typed `failed_request_context()` API. An older Core or SDK keeps its
ordinary capabilities without advertising event streaming.

The adapter resolves descriptors reached by actual Pine execution. It constructs
close-source Renko observations with the shared SDK, retaining every brick's
ordinal and source open time. A source cohort becomes available atomically at its
physical bar close. No synthetic milliseconds, matching prices, volume or account
observations are introduced. Historical vertices use the canonical source-close
visibility contract while the Host's progressive account and OHLC matching path
remain authoritative. Bounded windows retain a row offset within a time cohort.

A missing event context interrupts a tentative execution. The response contains
no partial intents, a typed window control status, and a digest of the resolved
recipe. Rebase discards the entire tentative Host ledger and evaluator and adds
the resolved context with empty prices and known timestamp-only endpoints. A
fresh actual-account pass discovers any further windows or contexts. The final
stable execution starts with fresh accounts and feeds. Ordinary window-only
rebases continue to preserve their Core reservations. A new event context instead
rebuilds the evaluator against the amended immutable provider plan.

The controller permits 16 synthetic contexts and 200,000 combined bricks, with
the Host's existing limit of 64 whole-trial attempts. Frozen physical inputs are
bounded to 17 contexts and 200,000 rows. A checkpoint binds physical sources,
descriptor recipes, source hashes, row cursors and response hashes. Reconstruction
replays Pine observations and plan resets before restoring the matching ledger;
it never rematches recorded fills. Equal-time ordinary bars, partial-cohort
cursors, changed sources and unnegotiated or nonempty legacy price snapshots
remain errors.

Provider misses are read from structured Core state. A script's `runtime.error()`
text is never treated as evidence of missing data. The typed status leaves the
failed runtime poisoned; only a new evaluator can consume an amended plan.

Controlled checks cover immutable cohorts and cursors, both actual subprocess
bridges, hidden partial intents, transcript restart/continuation and changed-source
rejection. Historical chart and Workbench paths execute against real Host accounts
and OHLC matching; chart recovery restores exact bounded values and tick counts,
and Workbench seek/replay reproduces the completed result.

This stage connects historical streams. Realtime print/book event discovery,
V2/cost combinations, resource workloads, an installed managed candidate and
packaged desktop/release qualification remain separate required work. Existing
close-source construction tests do not establish arbitrary TradingView Renko
construction or exchange execution equivalence.
