# Pine Workbench Host replay

Completed Pine runs with `execution_mode=CANDLESCOPE` advertise
`replay_contract=candlescope.external-replay/1`. The existing
`/backtests/native/replays` API accepts those runs without changing their account
authority. Their method is `HOST_ACCOUNT_CHECKPOINT`; native-account replay keeps
its existing historical-prefix/fixed-horizon behavior. The UI exposes replay
only when the run advertises this contract and hides the full batch report as
soon as the user enters the replay view.

Each committed chart cursor owns a Host kernel/account snapshot, pending orders,
entry allocation and OCA state, execution-event cursor, account/intent transcript,
scheduled fill passes, and the last interpreter request/result. Account and
visible result journals commit in the same SQLite transaction as the cursor.
The private account journal is excluded from list/get/export API envelopes.
User snapshots include the private state inside their server-side checksum.

With `candlescope.pine-workbench-control/1`, the checkpoint also retains the
frozen risk configuration and stop state. Synthetic closing fills preserve the
same ownership and consumed-liquidity state. See `pine-workbench-controls.md` for
the separate control negotiation, window and closing-liquidity contracts.

Forward execution restores the actual Host account and matcher and processes
only the remaining market events. The evaluator reconstructs the saved feedback
transcript and must reproduce its previous output before matching resumes. It
does not import a native broker account or rematch earlier fills/fees. A backward
seek intentionally rebuilds the requested prefix from the original initial
account. Restoring a saved checkpoint resumes from that checkpoint instead.

Supported Pine modes are BAR, trade tape, book-assisted, full-depth and sampled
book execution, with fill callbacks in the tape/book modes. Checkpoints occur at
confirmed chart boundaries. They preserve the last visible spread, depth already
consumed by hypothetical orders, assumed FIFO positions and admission depth,
sample timestamps, staleness counters and pending partial quantities. Repeated
identical book snapshots do not replenish previously consumed liquidity. Full
depth remains a disclosed pessimistic queue approximation; sampled books still
do not infer passive fills or exchange sequence continuity.

Restore checks run/input/Host implementation identities, checksums, cursor
agreement and book-state contracts. Changing matching code or a sampled-book age
policy requires the original implementation or a fresh run. Cancellation,
transcript mismatch, checkpoint size overflow and journal-write failures leave
the last committed account/cursor visible. Account checkpoints have a 64 MiB
ceiling on their complete stored representation, and ordinary worker IPC/deadline
limits remain in force. Large private account journals and snapshots use the
self-contained `candlescope.replay-checkpoint-zlib/1` storage envelope. It retains
every field, the decoded byte count and SHA-256, and the original complete
financial/transcript checksum. The decoder rejects truncated or trailing streams,
size/hash mismatches and decoded values over 256 MiB. Legacy plain JSON remains
readable. No external blob store or omitted report arrays are involved. Snapshot
serialization borrows the private journal only while holding the native lock;
mutable execution paths still receive detached account state.

The desktop controls poll `GET /backtests/native/replays/{id}?if_revision=N`.
An unchanged public revision returns metadata plus `result_unchanged=true` and
omits `result`; the caller retains its exact matching report. A changed revision
returns the complete current report. Result-journal revision checks also apply to
conditional polls. Default GET and export always return the full report and
validate its stored journal before materializing it. Complete repeated reads
reuse bounded encoded views, with a fresh detached JSON value for every caller.
These changes address repeated report-copy overhead; resource qualification still
requires the complete fresh-process Host matrix and its frozen budgets.

Full backtest controls likewise poll `/backtests/{native|external}/runs/{id}`
with `if_state=<cached state>`. An unchanged state returns the existing compact
run summary with `run_unchanged=true`; the caller retains its frozen configuration
and report. A state transition, default GET and export return the complete run.
This avoids parsing large uploaded physical-event inputs on every status poll.
The native and evaluator transports reuse one bounded I/O thread per worker,
serialize in-flight calls, and retain per-request response queues. Shutdown,
timeout and cancellation reap the process, close all pipes and join that thread.

Window discovery still executes every tentative market observation against a
fresh Host ledger and validates the final evaluator snapshot before sealing the
window. Since that ledger is then discarded, discovery skips construction of
unused Host reports and durable transcript copies. The private discovery flag
rejects capture or resumed execution; final runs, cost scenarios and replay
continue to construct their complete reports and checkpoints. Journaled commands
take one owned copy before the transport, preserving caller-mutation isolation.

Controlled tests cover all nine supported mode/callback combinations, spot cash
and inventory, pending queues/liquidity, backward seek, replay-service/interpreter-
worker restart, requested data,
imports, explicit execution clocks, HTTP/export, cancellation, corruption and
transaction rollback. Spies reject any restored forward operation that attempts
to match an earlier market event. Endpoint reports are compared against nine
pre-change receipts under `output/pine-host/phase3/replay-before/`; only the
expected Host implementation identity and enclosing report seal are excluded.

The earlier replay-only combined Host regression passed 278 cases, with 26 mixed/non-Pine
cases deselected. Shared kernel/cost/provider/recovery checks passed 75 cases.
Frontend checks passed 226 cases, both TypeScript projects and the 30-locale
catalog guard. A Playwright run operated the actual React report/controls against
an isolated real Pine Host HTTP service: create, step, save, step, restore, repeat
step and play to completion. Restored and repeated reports matched their earlier
values; the final report matched the batch result. Browser console errors and
warnings were zero. Screenshots and exported receipts are under
`output/playwright/external-replay-*` and `output/pine-host/phase3/external-replay-*`.
This is component plus real-service validation, not packaged-application proof.

Pyne external-account replay remains unadvertised; existing Pyne native-account
replay is separate. Workbench risk and closing scheduling now use the negotiated
control contract. BAR fill recalculation, richer request-prefix updates and
larger-history performance remain further work. These local checks
do not establish packaged-app acceptance, real exchange queues or TradingView
broker-emulator equivalence.
