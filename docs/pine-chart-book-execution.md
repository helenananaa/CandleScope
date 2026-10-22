# Chart book execution foundation

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

Controlled kernel checks cover real spread/depth prices, shared consumed depth,
same-millisecond samples, checkpoint equality, cumulative event limits, V2
funding/marks and closing-tick visibility. This establishes the execution-loop
foundation only. Standalone chart snapshot freezing, immutable input identity,
queue/colocated dispatch, cost-scenario factories and the UI entry point must
still be connected and qualified before advertising chart book support. The
existing Workbench book path is a separate, already connected route.
