# H127 fixed-grid mixed-history planning and reads

Related: #127 (coverage planning and bounded historical execution), #130
(K130/B130 consumers), #126 (D126 revision and resource contracts), #132
(capability qualification).

`history.cover_plan` proposes one target using actual source widths, phases,
eligible ranges, required fields, full series identity and estimated row cost.
It prefers lower cost per covered millisecond, with wider blocks as a tie-break.
The bounded backtracking search handles cases where a wide first choice would
otherwise strand the final edge. It is a deterministic heuristic; endpoint
page overhead and global request-cost optimization remain outside this stage.

For an epoch-aligned first 89m bucket, 1h + 15m + 5m + 5m + four 1m inputs
cover exactly eight source bars. Plans for later target phases use the actual
grid again. No coarse candle is proportionally split or relabeled. Adjacent
eligibility ranges may merge; a true gap never disappears. Planning budget
exhaustion raises `CoverBudgetExceeded`, distinct from impossible coverage.

`FixedHistorySource.qualification` identifies the caller's composition evidence.
It is not a new provider qualification registry or proof that data exists.
The supplying owner must verify native coarse/fine field and volume semantics
before offering a source. The live read still checks actual data and revisions.

## Shared read contract

The existing DataManager/QueryEngine facade exposes:

```python
with dm.read_mixed_history_blocks(
    target_key, target_open_ms, target_end_exclusive_ms,
    composition_qualified_sources,
    page_rows=256,
    required_fields=frozenset({"open", "high", "low", "close", "volume"}),
) as read:
    # The handle intentionally exposes no result before its final fence.
    pass
summary, receipt = read.summary, read.receipt
```

Execute this synchronous interface on the existing storage worker. It does
not submit nested executor work. One target bounds the output; each H127 page
is folded with K130 and released before the next read. B130 remains the sole
block/cache/lease owner, and D126 remains the sole durable revision owner.

The adapter validates all eligible source grids using the existing H127
qualification and holds one encompassing B130 multi-source view. Inner page
revisions must match that view. Source changes between spans, changes after
the final read, storage rebinding and cancellation reject the entire result.
Rows, target bounds and explicit trusted closure must prove the complete
original target. Returning a result does not persist it or grant indefinite
freshness; later materialization/adoption must consume D126's revision fence.

If a coarse span has unavailable rows, bounds or required fields, its tentative
pages are discarded and the exact span is replanned using strictly finer
qualified grids. Prior accepted spans remain. Missing finest data stays
unavailable; storage/revision errors are not converted into source gaps or
unbounded retry. The initial plan and all refinements share one position
budget. A failed multi-page span cannot leave volume counted twice.

The `history-query` reservation covers search nodes/path/iterators and the
retained summary states. H127 charges its page/decode work and B130 charges
its blocks/leases using the existing shared budget. The default search limit
is 32,768 positions, maximum 131,072; the memory owner may impose a lower
effective bound. Sources are bounded to 32 and eligibility ranges to 128 per
source; B130's existing dependency limit also applies.

The immutable receipt records initial `planned_rows`/`estimated_cost`, actual
`accepted_rows`, fallback count, total explored positions, physical storage
rows, pages, shared hits, source qualification references, source revisions
and acquisition floor. Abandoned coarse-page reads remain in physical totals.
These estimates do not constitute measured wall-clock or network savings.

## Qualified scope and remaining integration

The executor inherits H127's canonical fixed-grid source admission. Its target
stage accepts fixed buckets only; calendar/session/DST composition needs a
separate BoundarySchedule consumer. Unsupported grids are explicit, with no
fixed-day approximation for calendar months.

Tests use isolated SQLite and the actual facade, K130/B130/H127 owners. They
cover exact mixed/fine arithmetic, phases and prime intervals, source identity
and field isolation, page sizes 1–256, hot reuse, local refinement, unknown
enhancements, revision/deletion, rebinding, cancellation and resource release.
Synthetic coarse/fine parity is deliberately separate from real venue
qualification.

Ordinary chart queries and replay do not gain new mixed capability from this
interface alone. Automatic source qualification/selection, chart/history-task
adoption, mixed calendar sources, request scheduling and real cold-load/
multi-chart performance remain #127 work. The chart picker continues to use
its existing admitted routes until those consumers are integrated.
