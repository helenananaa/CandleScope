# Shared history snapshots and screened tape batches

This extends the durable-delta/multi-track work with remaining CPU/memory-copy
improvements and bounded waiting-order/held-position tape paths.

## History-sized work removed from ordinary updates

Broker order maps, fills, closed trades and warnings are shared until the first
actual mutation of a candidate. Mutation detaches the relevant collection before
writing, preserving rollback and historical frames. Open orders are cached against
the committed map identity; all committed order mutations replace that map.

Unchanged encoded components now also share readonly JSON trees internally.
Ordinary market updates do not recursively copy every old ledger/fill/order object.
Public broker snapshots still return detached normal containers. Nested mutations
cannot poison internal cached state. The optional native decoder is used only
when the encoder established native integer compatibility; oversized integers
retain their exact stdlib fallback.

Canonical objects are composed from byte fragments. Hashing streams those
fragments instead of building repeated full-history temporary byte strings.
Canonical bytes and hashes remain unchanged. Complete exports still require work
proportional to their output size; this is not a constant-time full export format.

## Delta construction

The SQL profile identified repeated decode/validation of just-produced checkpoints
and their bases after broker snapshot work was reduced. Fresh codec output now
carries a private immutable logical receipt captured before encoding. The writer
can consume that representation directly. Plain imported bytes continue through
the normal strict decoder; the receipt is not a wire-format change.

A disposable base cache retains up to four entries, each at most 4 MiB of raw JSON.
Exact bytes identify a cached base, preserving corruption checks and correctness
after transaction rollback/base-id reuse. Compressed size is not used as the cache
budget; imported compressed bases without a trusted raw-size receipt are not
retained. Large/imported bases remain correct through the existing decoder path.

## Orders and held positions

Under the existing optimization switch, flat ONE_WAY tape accounts with resting
orders batch only their screened interaction-free prefix. The first triggering
event still executes alone through the coordinator. A stop-on-event service test
checks the first strict-cross fill, its timestamp, and the peer track boundary.

Held ONE_WAY tape positions with no funding/book/historical-account dependency
may batch a constant-valuation prefix. Planning stops reading that prefix on a
price change; the changed-price event runs individually through the account/risk
barrier. Within a constant-price broker batch, one account valuation is sufficient
and preserves peak/drawdown. A 100-trade test checks one valuation and full snapshot
equality to scalar execution. Varying-price, cross-account and HEDGE risk paths
retain their precise execution or previously certified shared-range algorithms.

## Measurements

Synthetic broker microprobe: same one-unit position and one resting order, ten
warm apply-plus-internal-snapshot measurements at each history length:

| Accumulated fills | Before this work | Shared history |
| --- | ---: | ---: |
| 1 | 0.307 ms | 0.688 ms |
| 401 | 16.753 ms | 2.045 ms |
| 2001 | 82.963 ms | 7.267 ms |

These are individual medians, not guarantees. Tiny histories have no material
copy cost to amortize. The improvement at large histories is the intended benefit.

The real-service synthetic HEDGE comparison uses 50 round trips (101 fills) and
four subsequent BASE_BAR commands. It compares readonly sharing with a detached
recursive-copy emulation on the same current engine; other optimizations remain
enabled on both sides. Final state hashes match.

| Mode | Four-command median |
| --- | ---: |
| Detached history copies | 127.404 ms |
| Shared readonly history | 60.652 ms |

Receipt: `output/replay-history-snapshot-final-20260911.json`. Reproduce from
`backend`:

```powershell
python -m scripts.replay_history_snapshot_benchmark --round-trips 50 --output receipt.json
```

This is a synthetic service test, not a browser or
production-archive latency claim. Earlier measurements without logical-receipt
reuse did not establish a stable service improvement and remain separate receipts.

The first combined main/worker profiling attempt failed because the runtime does
not allow overlapping cProfile tools; the successful SQL-only profile serialized
its probes and located the repeated decoder work. No profiler remains installed
in production code. A first stop-on-fill fixture used price equality, while this
tape model requires a strict limit cross; the fixture was corrected without
changing execution semantics.

## Validation and current limits

The broad replay run passed 158 tests in 232.68 seconds. Focused runs cover native
and stdlib JSON parity, oversized integers, immutable aliases, copy-on-write,
failed writes, full/delta recovery, raw-size cache bounds, funding/liquidation,
waiting orders, changing prices, constant held prices and first-fill stopping.
The final eight multi-track cases passed in 23.36 seconds; their receipt is
`output/replay-order-position-batch-final-20260911.xml`. The final snapshot/tape
unit run passed 20 tests, including the one-valuation/100-trade case. Ruff and
diff whitespace checks pass.

Full wire encoding and new/changed history still have output-sized costs. This
work does not bypass risk checks to turn arbitrary positioned tape scans into
endpoint-price jumps. Existing optimization-switch defaults are unchanged.
No live database migration, service restart, commit or push was performed.
