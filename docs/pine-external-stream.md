# External Pine observation streams

The development bridges advertise `candlescope.pine-external-stream/1` only when
the installed Core exposes stream schema 1, the complete Python lifecycle and
the tick scheduling budget. Chart `pine-chart/9` and Workbench
`pine-external/13` share the same implementation. This is an additive transport
capability; product admission for realtime and historical every-tick strategies
still depends on connecting the actual application clocks.

One isolated evaluator process owns one immutable source/environment. The Host
sends `stream_open`, `stream_begin`, individual `stream_observe` messages and
`stream_commit`. A known `historical_plan` initializes dataset endpoints and
static windows without account execution. Core returns an input skip; the Host
must map retained bar indices accordingly. Unresolved dynamic window discovery
is explicitly rejected pending its observed-feedback/rebase integration.

Chart/account/request bar timestamps are exact integer seconds on this wire;
event clocks and availability clocks remain milliseconds. The bridge converts
bar times once. It rejects unnegotiated requested transactions, nonempty initial
requested datasets under the observed-update contract, legacy execution fields
in stream opening, frozen-environment mutation and incorrect bar/intent cursors.
Every response acknowledges the stream, execution and tick contracts.

Each observation returns only new intents with their original bar/pass indices,
`intent_base`, `intent_cursor`, `pass_cursor`, `bar_cursor` and `bar_open`.
Observation/commit responses omit output history. `stream_snapshot` explicitly
retrieves plots and optionally complete intents. Host matching and account
authority remain outside Core. Confirmation and history commitment are separate:
closing-fill observations may arrive before commitment.

`backend/app/backtest/pine_stream.py` owns the Host transcript. Its checkpoint
deep-copies the frozen opening, commands, per-response hashes and final cursors.
Recovery starts a new worker, replays each command and checks every response
before returning the reconstructed evaluator. It does not call a matcher or
settle fills. A run coordinator must pair this with the same ledger checkpoint;
the historical Workbench coordinator now adopts this path as described in
[historical ticks](pine-history-tick-workbench.md). Chart and physical/live
clock adoption remain separate work.
Errors, cancellation, identity/acknowledgement failures and replay differences
close and reap the worker. An optional run deadline also bounds replay.

Controlled tests exercise both bridges and actual SDK JSON-lines workers,
ordinary rollback, varip/TA state, requested transactions, known historical
endpoints, half-bar restart, corrupted feedback, 128 same-bar observations and
bounded per-message suffix transport. This does not establish bounded total
journal/runtime memory, long-run latency, complete ledger restart, actual
application tick routing, TradingView equivalence or packaged-app qualification.

Core development candidate `22d301334` combines this lifecycle with the provider
feed API and the realtime last-bar boundary repair. Its full combined gate and
the Host immutable installed-worker gate have independent local receipts.
