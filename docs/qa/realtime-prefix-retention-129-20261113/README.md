# Retire confirmed realtime leaves through qualified history — #129

Base `1ca92972982b9ef5127dccd351fee386c3056496`; product app files
`2334655171a341cf1d61297c238b021e735193e0` (includes #392). The later default
DataManager regression changes tests only; all 1000 native backend hashes still
match the checkout.

## Scope and fences

An existing qualified history prefix previously stayed at its initial seam.
Every later closed component remained in the live overlay for the lifetime of
the large target bucket. On a closed input, an active complete prefix can now
retire its next **128 contiguous closed leaves** using the existing bounded
H127 reader, B130 cache and D126 revision/acquisition fences. Forming inputs do
not trigger this work. Other merge modes, unqualified/no-prefix states, partial
prefixes and closed builders retain their existing paths.

Before dropping any leaf, the reader compares each accepted leaf with trusted
closed canonical readback, including actual times, every supported numeric field
and enhanced-field capabilities. Two opposite leaf corrections cannot be hidden
by an unchanged aggregate. Both read fences cover the full staged prefix. The
owner then checks target generation/builder/prefix identity and the **exact**
public numeric/count/temporal projection before synchronous adoption. Changed
rounding is a reason to defer, never a tolerance adjustment. A retained forming
tail keeps its original acquisition floor. Compaction publishes no extra event
and does not relabel updated_at_ms as a new source observation.

Failed/unavailable/mismatching reads and memory/executor pressure leave accepted
prefix/overlay values intact and allow the normal source input to continue.
One private retry-progress scalar prevents the same failed optional read on
every preview or duplicate close. Initial selection references, canonical raw/
decode work and temporary projection/proof copies use existing memory owners.
There is no added source subscription, writer, persistent cache, queue or timer,
and no limit increase. Existing HISTORY_PREFIX_ENABLED=0 retains the prior
non-prefix rollback route; canonical data and previous QA remain preserved.

This is bounded **optional retention work for an already qualified active
prefix**, not a universal hard tail cap: unconfirmed/gapped/different/stale
canonical seams remain retained. Closed-builder retention, no-prefix targets
and the remaining full reconstruction/resource matrix continue under #129.

## Checks and retained failures

**49 prefix/overlay/runtime cases pass**, including 13 new retention cases. The
production-size controlled case uses a 2048-row prefix and 128-leaf seams; after
258 live closes, two compactions leave two leaves. Tests cover repeated forming/
closed replacement, earlier canonical correction after retirement, missing
coverage, compensated per-leaf corrections, capability mismatch, optional read/
revision/budget failure, duplicate retry suppression, cancellation, detach and
exactly one ordinary publication around a compaction.

The default DataManager test starts its real bridge/router, acquisition and
durable native writer with a controlled ingestion transport. A 2048-row warm
prefix plus 132 source closes performs one compaction, retains four leaves,
persists all 132 native rows through the existing writer, and delivers every
new target result in order to a public preserving subscription. This is
controlled transport, not live exchange/native desktop qualification.

The first capability test accidentally mutated a detached getter snapshot;
it now supplies the unknown-field observation through the accepted input API.
The first publication test used the wrong publisher config attribute; corrected.
The first default-bridge assertion incorrectly required strictly increasing
volumes: the existing warm-prefix refresh can publish the unchanged prior
projection before the next native close. The corrected assertion retains that
behavior while requiring the entire 132-result progression and exact persistence.
The separate publisher test still forbids any extra compaction publication.
All initial failures remain archived.

The full local CCXT/backend selector passes **2111 cases, 63 warnings** before
the additional default-bridge case; that case and the final 49-case suite pass
afterward. All prefix suites now join that selector, where they had been omitted.
Architecture passes. Cloud CI remains the final merge gate.
The same prefix cases join the existing qualified four-platform host workflow;
its path filter now covers the aggregator and history-prefix contract changes.
These are cross-platform host/component checks, not Windows desktop acceptance.

## Same-input resource and cost observations

Complete unchanged base backend versus product, fresh processes, same Python
3.12.15/macOS arm64, real temporary SQLite, two warm plus seven measured windows.
Each seeds the same qualified 2048 prefix, then admits 258 closed 1m components
into a 10007m target. Publisher events are disabled to isolate retention work.
Input construction/seed/final diagnostics are outside the timed window; component
counts read the live owner, without copying a public snapshot per input.

| Observation | Base | Product |
| --- | ---: | ---: |
| Retained tail leaves | 258 | 2 |
| Peak leaves after each input | 258 | 128 |
| Reachable aggregator graph bytes | 298819 | 10231 |
| Deduplicated aggregator + B130 graph bytes | 416437 | 142873 |
| B130 estimated bytes / entries | 434660 / 128 | 488996 / 144 |
| Additional canonical reads / rows after seed | 0 / 0 | 4 / 640 |
| Median process CPU per 258-input window | 415.42 ms | 539.45 ms |
| Median elapsed per window | 421.84 ms | 547.02 ms |

Every final public projection hash matches. Shared cache growth is explicitly
included in the combined graph, not hidden by reporting only the live builder.
The memory-budget snapshot also remains in the raw receipt, but this isolated
aggregator is not the DataManager's registered realtime owner, so that diagnostic
alone is not its joint budget proof. This finite workload costs about **30% more
CPU**, not a performance improvement or RSS/latency/endurance result. A preceding
sample reported a smaller increase; all samples are retained. The earliest
product-only timing copied a getter snapshot per input and is retained but not
used for this comparison. Scripts and complete old backend export remain under
the QA/output paths.

## Native regression

The retained macOS arm64 frontend/runtime/plugin bundle from build
ef8f0e0fa6df299a823f4460b701eb1c3c98361f is cloned, all 1000 tracked backend app
files overlaid, then ad-hoc sealed. This is assembled-backend qualification,
not a fresh release build. Every backend/asar hash and strict signature matches
before and after. No source/backend change follows this package observation.

Fresh empty profile, real public OKX BTC-USDT spot, no seed/response replacement:
45m/90m deep history, unchanged 500-row 1m/5m gate, release/recreation,
save/full exit/restart pass **3450 closed-bar nine-field comparisons**.
All three checkpoints receive actual source frames and saved workspaces;
the owned process trees (9 and 10 processes) fully exit. Screenshots were viewed.
The existing local 127.0.0.1:7897 proxy is process-only, HTTP timeout stays 8s;
no OS networking changes. Runtime logs and ledger work are retained. This flow
does not exercise a 2048-prefix/128-leaf production compaction: that evidence is
the controlled default-bridge and source suites above. No native large-prefix,
forming-value, all-platform, long-run or overall resource claim follows from it.

#126/#127/#129 remain open against their original completion definitions.
