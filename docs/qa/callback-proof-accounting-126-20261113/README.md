# Live callback proof accounting — #126

Base `b36f9ade239432133eaee76919a9b5720106c0ec`. Accounting product/first cost
head `31067190ba784e2b9e30ccba5f02e8a42970839f`; final combined product
`7cde07bc593e2a4bd294dbd54770d0eaf4896ce5` also incorporates #390's strict
legacy fallback. No publication, finality, storage or subscriber contract changes.

## Gap and ownership

A callback may mutate its own public BarState.source_refs copy. Replacing an
existing nested proof with a large value does not change outer dictionary
cardinality. Accepted immutable component weights therefore cannot account for
that live callback graph. The full old backend reproduces both current and
previous-bar failures: growing a nested proof by 1 MiB changes the reported proof
bytes by zero (before.log).

Publisher frames remain the owner. A transient set of their current/previous bar
IDs selects live proof-graph traversal only for active callback snapshots. Builder,
pending retry and unexposed publication copies retain their cached accepted
weights. No new snapshot, persistent object index, timer, queue, cap increase or
data deletion is introduced. Foreign mutable component entries retain their
existing traversal. mutable_callback_states reports the deduplicated exposed
states. Shared immutable references can still be overcounted; this is not a hard
allocator/RSS cap or a complete joint admission/retention policy.

Focused final regression: **55 passed, 5 warnings**; combined regression before
the inherited legacy fix: **1940 passed, 6 warnings**. Tests preserve mutation of
both current and previous callback snapshots, unchanged index cardinality,
original-state isolation, weak-reference release of the nested payload, and
error/cancellation cleanup. Initial focused failures came from attempting to
weak-reference a slotted BarState; the corrected harness observes the actual
weak-referenceable nested payload. Those logs are retained. Architecture passes.
After incorporating the strict legacy fallback, the final complete CI selector
passes **2037 tests, 63 warnings** locally. The subsequent parent-branch merge
changes only QA files: the entire backend tree is byte-identical to tested 7cde.

```sh
CANDLE_DATA_DIR="$PWD/output/callback-proof-tests" PYTHONPATH=backend python docs/qa/callback-proof-accounting-126-20261113/run-regression.py
python backend/scripts/check_architecture.py
```

## Accounting and CPU cost

Same deterministic accepted components, fresh processes, Python 3.12.15/macOS
arm64, default DataManager owners registered but not started; its storage bridge
is inactive. No source/network qualification in these probes. Source construction,
publication copying and optional full heap diagnostics are outside usage timing.
Two warm plus seven callback measurements are recorded. All callback payload
hashes match between full old/new backends; original state stays unchanged.

| Components / growth | Held source-ref estimate, old → new bytes | Registered reachable heap, both versions | Callback usage CPU median, old → new µs |
| --- | ---: | ---: | ---: |
| 97 / none | 400444 → 349332 | 345990 | 22 → 293 |
| 97 / 1 MiB | 400444 → 1397949 | 1394607 | 17 → 297 |
| 10007 / none | 40851036 → 35547624 | 33810425 | 44 → 28386 |
| 10007 / 1 MiB | 40851036 → 36596241 | 34859042 | 45 → 29274 |

The old estimate misses all growth; the live traversal reflects it. A decrease
for unchanged proofs is different accounting of shared references, not physical
memory savings. Owner release returns to 192 estimated bytes in every case.
Consumer-owned returned values are outside this engine owner; no whole-process
RSS release is asserted.

**The callback path is O(proof graph size)**: roughly 28 ms for 10007 proofs in
this controlled sample, not a performance improvement. An additional final-head
probe records ordinary resident-builder usage outside callbacks separately;
that cached path remains approximately 10 → 9 µs for the same 10007 components.
This distinguishes in-flight mutable accounting from ordinary input state. It
does not qualify stable latency, total aggregation/preview cost or sustained
application load. Cost reduction must preserve actual mutable-growth visibility;
closed-state retention/reconstruction and joint-resource qualification remain
part of #126/#129. No larger limit or hidden measurement scope is used.

## Native package

Both 310 and final 7cde packages pass fresh empty-profile real OKX BTC-USDT spot:
45m/90m viewport and explicit deep history, unchanged 500-row 1m/5m readiness,
custom target recreation, save, full process exit and restart/restore. Each run
compares **3450 closed bars over nine fields** (628/533 initial and recreated,
628/500 restarted), checks saved workspace state, actual 1m/15m/30m/45m/90m
frames at all three checkpoints, no page errors and both complete 10-process
exits. Counts from overlapping runs are not added together.

Each is an APFS clone of the retained macOS arm64 app with all 1000 committed
backend/app files overlaid and ad-hoc sealed. Source/asar hashes and deep strict
signatures are verified before/after. Frontend/runtime/plugins remain from base
build ef8f0e0fa6df299a823f4460b701eb1c3c98361f. This is assembled-backend
qualification, not a clean frontend/release build, Windows or Intel acceptance.
The existing local 127.0.0.1:7897 proxy is supplied only to isolated processes;
the default 8-second timeout and system network settings are unchanged.

Final native logs retain 25 warning/error lines, including a custom-write fence
retry and coordinator/custom-query work. Ledger summaries, originals and raw
receipts are retained; a passing workflow is not a clean ledger or long-duration
acceptance. Historical crosshairs are visible; forming/header price is not an
assertion in the closed-bar comparison. Only ephemeral contextToken strings are
redacted from archived receipts; numeric active_read_tokens are retained.

#126/#127/#129 remain subject to all original uncompleted writer/resource,
streaming, shared initialization, retention/rebuild, demand-preview, performance
and runtime matrices. This accounting correction alone does not complete them.
