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
ceiling, and ordinary worker IPC/deadline limits remain in force.

Controlled tests cover all nine supported mode/callback combinations, spot cash
and inventory, pending queues/liquidity, backward seek, replay-service/interpreter-
worker restart, requested data,
imports, explicit execution clocks, HTTP/export, cancellation, corruption and
transaction rollback. Spies reject any restored forward operation that attempts
to match an earlier market event. Endpoint reports are compared against nine
pre-change receipts under `output/pine-host/phase3/replay-before/`; only the
expected Host implementation identity and enclosing report seal are excluded.

The selected combined Host regression passed 278 cases, with 26 mixed/non-Pine
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
replay is separate. Workbench closing-tick scheduling, richer request-prefix
updates and larger-history performance remain further work. These local checks
do not establish packaged-app acceptance, real exchange queues or TradingView
broker-emulator equivalence.
