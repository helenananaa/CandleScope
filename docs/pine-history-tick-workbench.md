# Workbench historical OHLC ticks

Development Workbench runs with `calc_on_every_history_tick=true` negotiate
`candlescope.pine-history-tick/1` and the external observation stream. This
selects the explicit OHLC path independently of fill-recalculation opt-in.
Physical tape/book profiles retain explicit rejection pending their own clock
integration. The chart strategy provider now has its own connected BAR path;
see [chart history ticks](pine-chart-history-ticks.md).

The kernel matches prior orders, delivers one strategy observation at each
OHLC vertex, then settles only newly eligible market orders at that vertex.
The final vertex leaves new markets for the next opening unless the existing
closing-tick option is enabled. Price orders keep their later-event eligibility.
Orders created by fill reports do not join the observation's captured market
set. Exported market eligibility reflects the observation vertex at which it
became effective. Continuous crossings retain the shared path matcher.

Ordinary state rolls back; varip persists; one confirmed observation commits
Pine history. Fill and liquidation reports still reach Host allocation/risk
bookkeeping, but do not create duplicate Pine executions under the every-history-
tick profile. Each frame carries the actual account. V2 retains historical marks,
funding, liquidation, working-order margin and shared participation capacity.
The original minimum-notional policy is retained, including its reduce-only
behavior; no account rule is relaxed to force a native-broker comparison.

Historical requested feeds use the canonical chart close at every synthetic
vertex. Eligible rows arrive once at the first vertex; later vertices carry
empty deltas. Requested scalars and lower-timeframe arrays retain ordinary
historical merge rules while account and order observations remain progressive.
Bounded fresh TradingView samples support this property for completed bars and
same/lower/higher requested contexts. Realtime data still uses the actual
observed clock; later chart bars remain unavailable. These samples do not
establish arbitrary script, feed or broker equivalence.

The fixed historical plan supplies endpoint metadata and calculation windows
without future account frames. Skipped bars still apply actual Host account
events; their script groups remain empty. Retained Core cursor/intent indices
start at zero, and Host decision records retain the original chart index.
Unresolved dynamic window discovery remains explicitly unsupported pending the
observed-feedback/rebase implementation.

Workbench submission, cost reruns and replay use the same clock. Durable
recovery validates its transcript and reconstructs Pine before restoring the
matching ledger. A live replay worker reuses the exact matching checkpoint;
seeking backwards, loading another checkpoint or eviction reconstructs it.
The existing two-worker bound, cancellation, deadlines and error cleanup apply.
Core reexecution never rematches recorded fills. Source/identity changes reject
recovery. Closed-bar durable checkpoints remain the supported product boundary;
the lower-level stream also supports half-bar evaluator reconstruction.

Controlled coverage includes actual Workbench V1, spot and V2 submissions,
native OHLC/account/TA controls, observed requested data, shared capacity,
next-open/closing fills, V2 liquidation without duplicate executions,
calculation-window skips and durable snapshot/restore endpoint parity.
Long-history resource qualification, chart/provider adoption, physical/live
ticks, dynamic discovery and formal packaged acceptance remain separate work.
