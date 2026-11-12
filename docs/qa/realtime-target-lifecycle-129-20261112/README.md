# R129 target detach: state release and suspended-input fencing

Base: `19a1edee9a30bc0ede1dff291cf463aa38b2404c` (PR #373).
Product commit/source hashes are in `source-hashes.json`. Refs #129 / #126;
parent issues remain open.

## Behavior

Previously only compact history slots supplied an input-generation fence. A plain
target removed while a source readback or previous-bucket callback awaited could
resume and create detached state or update a newly attached target. All registered
targets now capture the existing target token before asynchronous work; adoption
and event-driven close loops check it after awaits and before further mutations.
Stale work raises the existing BlockRevisionChanged retry/failure signal. Durable
source projections propagate it to the existing journal; no second revision domain
or silent acknowledgement is introduced. Explicit unregistered maintenance ingest
retains its public contract.

Removal also releases exact-target closed correction builders and component
graphs, in addition to expiring forming state. It preserves canonical storage,
pending independent delivery snapshots, other symbols/markets/semantic identities,
and the interval pipeline's customization hooks. Subsequent canonical readback /
existing replay reconstructs needed state. This does not evict active targets or
claim that empty customizable pipelines now have a global retention bound.

## Proof

- Final baseline reproduction: `before.log.gz`, **six expected failures** against
  the complete pre-change product. They show detached writes, reattachment
  contamination, retained correction state and exact-target release failures.
- `after4.log.gz` / XML: **80 passed** across lifecycle, aggregation, shared input
  and H127/R129 overlay/runtime contracts.
- `expanded.log.gz` / XML: **10 lifecycle cases passed**, adding source delivery
  outage/retry, public customization, semantic identity isolation, duplicate
  registration and explicit maintenance ingest.
- `tests.log.gz` / XML: **1,590 related tests passed**, six existing warnings, on
  the integration product. Architecture/diff checks pass. Cloud integration now
  selects the new lifecycle file; final CI status is recorded in the PR.

Barrier tests exercise both removal and remove/re-add during source readback and
previous-bucket expiry publication. A failed source delivery keeps its detached
snapshot across removal and successfully retries exactly the captured row; freeing
correction builders does not erase the existing delivery obligation.

The first harness incorrectly used historical snapshots for a forming realtime
bar, then waited for a native provisional close even though unconfirmed native
bars expire, then omitted the default-disabled expired event switch. Those attempts
are retained as `before-harness*`, `after`, `after2` and `after3`; one blocked test
process was terminated. The final harness explicitly uses realtime inputs and
enables expiry publication; no product finality policy was relaxed to pass it.

## Same-input resource / reconstruction comparison

`measure.py` uses 16 synthetic symbols, 89 closed one-minute source records each,
one 89m target per symbol, independent default owners and no network or storage.
Both variants use the safe immutable preparation product from PR #373; only the
detach/fencing patch differs. Nine-field closed-result, source-input and rebuilt
row hashes match. Raw JSON includes interpreter/platform/backend paths and timing.

| After all 16 targets detach | Baseline | Product |
| --- | ---: | ---: |
| Retained closed builders | 16 | 0 |
| Retained component references | 1,424 | 0 |
| Reachable Python state values (bytes) | 1,422,246 | 168 |
| Conservative realtime estimate (bytes) | 1,605,632 | 0 |
| Detach CPU total (μs) | 334 | 569 |
| Replay/recreate one target CPU (μs) | 7,723 | 11,723 |

The product trades detached correction reuse for memory release; the explicit
replay reconstructs the same row. Single uncontrolled-host timing samples do not
establish stable latency or performance budgets. This is component ownership
evidence, not RSS/native/continuous multi-chart acceptance. Pending source payloads
and other owners remain independently retained and require separate accounting.

```sh
CANDLE_DATA_DIR="$PWD/output/r129-lifecycle-data" PYTHONPATH=backend python docs/qa/realtime-target-lifecycle-129-20261112/run-regression.py
PYTHONPATH=/scratch/full-baseline/backend python docs/qa/realtime-target-lifecycle-129-20261112/measure.py
PYTHONPATH=backend python docs/qa/realtime-target-lifecycle-129-20261112/measure.py
```

Original issue matrices, global idle/default pipeline retention policy, complete
pending/in-flight owner audit, native reconstruction and sustained performance
qualification continue. Existing rollback retains canonical data and delivery
receipts; it cannot silently resume a removed target's old asynchronous work.
