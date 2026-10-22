# Chart strategy historical tick execution

Chart `PINE_ENGINE` revisions with `calc_on_every_history_tick=true` now use the
negotiated external observation stream for BAR runs. Compilation probes the
empty explicit schedule; it does not mistake the older unscheduled external
profile for a missing language feature. Submission requires `ORDER_INTENT` and
the stream capability. Physical/realtime every-tick admission remains separate.

The existing chart OHLC matcher supplies four partial OHLC/quarter-volume frames
per bar. Prior orders match first; newly created market orders can settle at the
observation vertex, except the final vertex uses the existing next-open/explicit
closing option. Fill bookkeeping, order ownership and Host risk admission remain
authoritative. V2 retains real marks, historical rules and shared capacity.
There is one Pine execution per vertex; the closing bookkeeping call does not
record an additional empty strategy decision.

The provider freezes the complete canonical history before execution, with
bounded materialization for iterator inputs. It initializes endpoint/static
window metadata without future account feedback. Core's retained indices start
at zero; the chart/kernel still traverse the actual earlier bars and account
events. Reports distinguish observed historical tick count from actual retained
Pine executions and disclose the input skip. Unresolved dynamic window discovery
remains explicitly rejected pending its observed-feedback/rebase integration.

Each step sends only one new observation and receives only new order intents.
The source/environment is frozen; the full history plan is not re-compared on
each step. The provider preserves a closed worker's last checkpoint for normal
post-run inspection. A restore replays the stream before the matching ledger is
restored, verifies every response, and compares the actual replayed intent list
with the provider checkpoint. Known historical source, metadata, cursor and
request-feed mismatches reject recovery. The lower-level provider can also
reconstruct an unconfirmed group; product durable checkpoints remain complete
chart bars, with interrupted intrabar work discarded and reconstructed.

Independent cost scenarios use fresh providers, accounts and the same clock.
Tests cover direct/serial adapters, the supervised whole-run process, V1/spot/V2,
calculation-window skips, actual half-bar feedback reconstruction, interrupted
kernel recovery, and foreign requested data revealed at the canonical historical
chart close on every synthetic vertex, with append-only deltas. Realtime clocks
retain actual observation limits. These are controlled installed-worker results.
Observed aggregate-trade ticks have their own [clock](pine-chart-realtime-ticks.md).
Connected live acceptance, dynamic discovery, total resource qualification, TradingView-wide
consistency and the formal packaged binary remain separate work.
