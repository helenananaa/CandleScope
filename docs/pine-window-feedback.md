# Observed historical request windows

`candlescope.pine-window-feedback/1` is a separate historical stream capability.
Core initializes static reservations without executing Pine or inventing future
account frames. The real Host matcher supplies observations to a tentative run.
If a dynamic selector enlarges a calculation window, Core interrupts evaluation.
The bridge returns a typed status with no partially emitted intents; the Host
records that response and discards the entire tentative ledger.

Rebase retains discovered context reservations and resets Pine variables,
rollback state, outputs, intents and requested prices to the initial seed. A
complete uninterrupted trial may be sealed, followed by a fresh canonical run.
Ordinary Pine failures remain fatal. Incomplete passes cannot be sealed. Core
checks the exact historical rows and keeps guarding later window drift.

Workbench runs discovery against fresh real kernels, including each independent
cost scenario. Chart BAR execution suppresses durable checkpoints while window
discovery is pending. Rebase resets its session, account, observation counters,
planner and risk allocation; it replaces trial execution/market hooks instead of
relaxing their frozen-configuration restore guards. Stable canonical checkpoints
then use the ordinary atomic provider/ledger path. A newly admitted history-tick
V2 profile no longer requires fill callbacks to select its Pine OHLC scenario.

Both coordinators retain request/response hashes for trial observations and
resets. Recovery reconstructs Pine only, clears emitted-intent verification at
each reset, and compares the final canonical observations with the recorded
Host groups before restoring the matching ledger. Recorded fills are not
matched again. Unsealed chart checkpoints reject. At most 64 discovery
executions/attempts are allowed; existing cancellation and shared deadlines
still apply.

Controlled tests compare Core streaming with complete observed schedules and
Host dynamic runs with explicit fixed-window controls. They cover ordinary
failure poisoning, declaration-only windows, exact-row guards, feed rollback,
varip/intents/cursor resets, stale journal mutations, linear/spot/V2 accounts,
chart serial and supervised workers, independent costs, tentative interruption
and committed-prefix recovery with an old-event matching guard.

This does not establish arbitrary TradingView dynamic-request equivalence.
Combined frozen-source qualification, long-history resources, chart book
admission, production engine/Renko patch pins and actual packaged acceptance
retain their separate evidence requirements. The persistent print stream does
not provide a known historical OHLC plan and does not negotiate this capability.
