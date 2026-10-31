# Explicit Pine tick schedule foundation

2026-10-22 development checkpoint. This is adapter/transport qualification;
the ordered Goal remains active. Product admission still rejects calculation
flags that lack a connected Host tick clock. Persistent same-bar streaming,
historical/physical clock drivers and packaged use remain required.

The Core exports `EXTERNAL_TICK_SCHEDULE_SCHEMA_VERSION=1` and a separate
100,000-observation-per-bar limit. The bridge advertises
`candlescope.pine-tick-schedule/1` only when both values match. It augments the
existing explicit schedule contract; it does not change default activation or
the released engine/plugin locks. Old Core builds retain their existing
65-evaluation route and cannot claim the new capability.

Callers must supply `execution_tick_contract` together with an explicit
`execution_schedule`. Historical tick contexts require negotiation. Larger
groups require the additive contract. The underlying byte limits and deadlines
still apply independently; the observation bound is not a throughput promise.
Historical observations carry progressive price/volume input and the actual
Host account. Market confirmation is independent of historical Pine bar state.
Tick observations do not spend the fill-loop recursion budget. Old historical
fill contexts preserve their separate full-bar scheduling behavior.

The adapter preserves chart/account seconds, converts those fields to Core
milliseconds once, and preserves the exact event clock. Historical tick
requested-data observations use this event clock. Full historical fill
observations retain their prior canonical-close cutoff. No new contract permits
future account/execution tapes to enter a worker. Native reference behavior for
canonical historical requested contexts is documented separately in the Core.

Both adapter routes acknowledge the tick contract. The Host checks this reply
and reaps a worker that omits it. Tick negotiation is part of the frozen prefix;
an append cannot change it. Complete-prefix reconstruction and appended
execution produce identical results, and restarting a worker reproduces the
same transcript. These checks do not establish constant-cost processing of
an evolving, uncommitted bar.

Development receipts live under
`output/pine-host/completion-goal/tick-schedule-20261022/candidate-01/`.
The current targeted receipts include 20 bridge cases against the new Core and
32 Host transport cases, including actual IPC on both routes, suffix-byte
reduction, reconstruction, restart, invalid negotiation and missing-ACK process
cleanup. Old-Core bridge controls separately pass 18 cases and deliberately
skip the two new-capability cases. Core targeted Python checks pass 69 cases;
candidate-01 complete gate passed 7,979 Rust, 1,946 Python and 172 tooling
checks. The immutable installed Host gate passed 668 cases with no skips.

Fresh live reference observations then exposed a preexisting Core defect in
explicit realtime static nested requests. The candidate-01 installed worker
reproduces the failure through actual IPC: direct values follow each observed
price while nested values repeat the outer final close. Both the failing Core
and IPC receipts remain preserved. Candidate-02 rebuilds the repaired Core;
its additional installed-worker controls cover all OHLCV fields on both routes,
both history-flag settings, suffix append and restart reconstruction.
Candidate-02 passed 7,982 Rust, 1,956 installed-wheel Python and 172 tooling
checks, formatting, strict Clippy, structure, host parity and generated WASM/Node
checks on Core `1f259afcbe063b9347029aea80a582f2a037d616`. All 10,327 frozen
files remained unchanged. The installed worker uses the exact qualified native
bytes (SHA-256 `032db6e3c27cbc03319bf3b03003e409c0c1ce98e4c5598af8d7110d9dfb2c6a`).
The corrected Host gate in `historical-02/` passed 688 cases across 51 modules,
zero failures/errors/skips, in 994.985 seconds. Its 3,678 source fingerprints,
runtime files and registry stayed unchanged. Separate bridge checks passed 112
cases with 12 optional Renko skips; transport controls passed all 52 cases.
Neither candidate admits unconnected product clocks or qualifies a persistent
same-bar streaming lifecycle.

The ordinary indicator route has a separate confirmed follow-up: growing
requested rows rebuild its current realtime session and lose `varip` state.
Complete acquisition/plugin reproduction observes requested array length 2 to 3
while the current-chart counter remains 3 instead of advancing to 4. A naive
repair using the existing auto-recalculating provider API executes twice for one
combined chart observation. Both failures are preserved under this phase's
output directory; provider-only transactions and Host lifecycle repair remain
required. These indicator failures do not change the scope of the qualified
external strategy transport above.

Formal packaging still pins an earlier Core source. Its existing Renko event-row
patch does not apply unchanged to the new source. Moving the package pin must
retain those event semantics and qualify the actual patched packaged binary;
development-wheel receipts cannot substitute for that validation.
