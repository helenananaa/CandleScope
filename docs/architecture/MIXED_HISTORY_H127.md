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

## Default closed-query integration

`QueryEngine` now offers the mixed executor to ordinary **closed** range and
`query_before` pages after the existing target-materialization probe. Provider
`MarketChannelCapability.history_composition` owns a typed, immutable policy;
the optional capability-schema-v3 property names native grids, fields, identity,
boundary/finality scope and evidence. It grants no new chart interval admission.
Initially only Binance USD-M default trade/base K-lines select 1m/5m/15m/1h,
using the official archive nine-field qualification in the linked QA report.
Spot, other providers, calendar/session and forming/latest pages keep their
existing executor. Native sources are read from canonical storage, not fetched
by a new downloader.

Independent native coarse candles cannot conceal known finer canonical input.
Before a span is accepted, the consumer checks all finer native grids, including
grids which are not selectable by the composition policy. Any existing finer
row (including partial/untrusted input) forces strictly finer replanning. A
coalesced D126 deletion footprint also prevents using coarse data to reconstruct
withdrawn fine history. An absent finer row alone is insufficient after deletion.
The current conservative policy may reject more work than mathematically needed;
it does not compare revision counters across sources or use wall-clock freshness.

One outer B130 view covers the page's candidate and precedence sources. Inner
target revisions and the bounded D126 `read_series_changes` evidence must match
it. Storage, policy/resolver and rollout configuration are checked again at the
final fence. Stale/unavailable revision evidence returns retryable pending, not
a source gap or a new-generation fallback. Only afterwards do the existing
materialization registry/writer and cache adopt the targets. Source revisions
continue to invalidate family materializations through the existing D126 owner.

The original single-base route is preferred when it is at least as coarse as
the qualified sources, or a count probe finds its complete bounded one-page
input range already local. Counts only select an executor: they never prove
grid, fields, finality or coverage. Larger fine-only targets can use H127's
bounded pages instead of reserving a large base window. Query diagnostics retain
discarded mixed work, scalar count-result rows, raw precedence probes, H127
storage reads/rows and block hits. A scalar count is one SQL result row, not one
additional candle. Revision polls/SQLite internal I/O are separate from these
canonical query counters.

Finer-presence probes are now grouped across at most 32 target plans at a time.
The repository's optional `query_bars_range_presence` accepts up to 256 half-open
windows for one full series identity and returns ordered booleans using one SQL
statement. Known disjoint/untouched durable source envelopes require no probe;
overlapping deletion evidence still rejects coarse input. The per-query working
index is limited to 4096 windows and charged 4MiB, then cleared for the next
batch. Initial plan search has its own bounded temporary reservation; this is
not another shared/persistent cache. Refinement spans outside the initial batch
and stores without the optional API retain bounded single-row probes. The
encompassing multi-source fence also covers these preflight reads.

Diagnostics distinguish `mixed_presence_reads` (SQL calls),
`mixed_presence_rows` (scalar boolean results), `mixed_probe_rows` (raw finer
rows) and `mixed_page_rows` (H127 input candles). Total `storage_rows` therefore
includes scalar probe/count results and must not be presented as candle count.
See the probe QA report for same-source before/after counts and measured limits.

`QueryConfig.mixed_custom_history=False` restores single-base reads. In-flight
mixed work is fenced if the switch changes; valid target materialization and
all source data/revisions remain. No migration or second writer is involved.

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

## Qualified cold backfill

`plan_fixed_batch` exposes a bounded prefix plus resume cursor, with distinct
source-unavailable, row, target and position limits. Backfill consumes batches
of at most 32 covers inside a single closed request of at most 512 targets,
16,384 native rows and 131,072 total explored positions. Its temporary proposal
and search reservations use the existing common memory budget. No unbounded
continuation state or new shared cache is persisted.

`backfill.mixed_plan` offers qualified Binance USD-M closed, epoch-zero fixed
requests to the existing engine. It reads canonical inputs through bounded
256-row pages, checks finer precedence and source revisions, and produces
native missing-run tasks plus the full exact source windows. Cost selection
compares estimated REST pages against the original single-base route. Small
cold requests which fan out into more requests retain that route. Counts and
source declarations never prove actual final coverage. Native component
`ledger_range` bounds prevent the parent custom interval from authorizing a
whole fine archive download for a tiny edge. This is a bounded REST heuristic,
not a global archive/network-cost optimizer.

Fetching, physical admission, normalization, archive routing and quota deferral
remain with existing owners. Committed native inputs survive deferral and are
reused on retry. After those commits, reconciliation checks finer precedence
again, including additional rows imported under the same acquisition. A stale
coarse proposal cannot conceal that finer history. K130 reduces the canonical
source windows; D126/materialization registry remain the only target writer.
Unknown enhancements or missing input leave the target incomplete, with no
false write-error count. Confirmed wholly empty upstream evidence is retained
without inventing a target. Target coverage never grants minute coverage.

For a large ordinary closed query whose absent mixed input would otherwise hit
the legacy base-window limit before detecting a gap, the query returns the
actual target demand to the existing DataManager/BackfillCoordinator scheduler.
Only known semantic coverage failures permit that demand; budget, I/O and stale
binding failures do not become market gaps. `auto_backfill=False` detects
without submitting. `BackfillConfig.mixed_custom_history=False` (environment
`BACKFILL_MIXED_CUSTOM_HISTORY=false`) restores original planning; an in-flight
switch rejects old mixed materialization and preserves canonical data.

The default integration does not yet combine a closed mixed prefix with a live
forming tail or broaden replay/calendar admission. Full archive-aware cost
selection, first-screen/warmup scheduling and real cold-load/multi-chart/native
performance remain #127 work. The measured
SQL-probe overhead is explicitly retained in the QA report; fewer source candles
is not a claim of lower wall-clock latency.
