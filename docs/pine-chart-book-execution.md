# Frozen chart book execution

Advanced Pine chart research exposes `BOOK_ASSISTED`, `BOOK_DEPTH` and
`BOOK_SAMPLED` alongside the existing BAR and aggregate-print modes. Upload an
explicit JSON object with `symbol`, `exchange`, `market_type`, nonempty
`provenance`, and ordered `events` (`time_ms`, `role`, `payload`). Prints declare
`source_event_kind: AGG_TRADE` and integer `source_sequence`. Quotes use the
existing spread, full-depth or bounded-sample schema for the selected mode.
RAW_TRADE input is a separate Workbench route and is not relabeled as aggregate
prints here. The existing book feature and trade-tape flags must both be enabled.

The snapshot endpoint validates the physical tape against every selected chart
bar's OHLCV and validates book continuity/visibility. Its digest binds the chart
and historical account snapshot, execution mode, physical input and provenance.
Run identity includes the book-input digest. The queued worker refreezes this
same input and rejects changes before executing. The HTTP validator, standalone
worker, colocated child, cost reexecution and chart readback share this contract.
The final bar confirms at the frozen interval endpoint without creating a trade.

The optional `execution_fidelity` argument on `DualClockSimulationKernel`
selects the existing physical `BOOK_ASSISTED`, `BOOK_DEPTH` or `BOOK_SAMPLED`
kernel. The default remains `AGG_TRADE_EXECUTION`, with its existing report and
checkpoint representation. Book modes currently accept aggregate prints plus
ordered book observations and historical account events.

Quotes update actual spread/depth, margin reservations and continuity. They do
not become Pine ticks or fabricate volume. A quote at a bar boundary first
closes the preceding signal bar using only the earlier quote/account state.
Prior orders settle on subsequent prints; sampled quotes remain ineligible for
same-millisecond matching. Full-depth fills retain pessimistic FIFO assumptions;
the report discloses `queue_exact: false` and the actual kernel fill policy.

Checkpoints bind the execution mode, book cursor, depth/consumed liquidity,
account, signal builder and decision history. The physical event budget includes
quotes/account events and remains cumulative across restored pages. A restored
run rejects regressed time, source order or book continuity. Historical marks
and funding keep their separate authoritative account clock.

The physical book policy supplies capacity. Generic BAR/tape participation,
synthetic BAR paths and unconnected latency settings are rejected, rather than
silently ignored. Independent Pine cost scenarios recreate the actual selected
book kernel and reexecute decisions/account feedback; generic latency and
participation scenarios are explicitly not applicable. V2 historical marks,
rules and funding run before market observations on timestamp ties, preserving
the original quote/print source order within the market stream.

Controlled tests cover real spread/depth prices, shared consumed depth,
same-millisecond samples, cumulative event limits, V2 funding/marks and
closing-tick visibility. HTTP tests freeze the real input, dispatch through an
actual installed Pine subprocess and return all chart bars. Checkpoint tests
reconstruct the Pine stream, restore the physical account and reject rematching
any recorded prefix. Frontend tests cover mode/data identity, file validation,
owned fields and the actual upload control. The frontend invalidates snapshots
on edits and discards file reads if their strategy, market or range changed.

These controls are distinct from full current-head Host qualification, rendered
browser/desktop acceptance, long-history/resource qualification, cross-platform
bundles and a public release. Those delivery gates remain required. No test here
establishes exact exchange queue priority or arbitrary TradingView equivalence.
