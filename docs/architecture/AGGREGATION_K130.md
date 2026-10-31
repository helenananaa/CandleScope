# K130: accepted components and pure aggregation semantics

Stage delivery for [#130](https://github.com/helenananaa/CandleScope/issues/130),
based on main `128b493246756c6f422138cd03ce7bb312e089ab` after merge commits for
#138, #148 and #144. That main's non-QA tree matches the jointly accepted
`71849b3db0a372ff5f1b7d768b3618c089aa94e6` tree exactly.

This provides 130-A's component/summary contract and 130-B's K130 primitives,
reference composition and initial production adapters. B130's block manager,
leases, singleflight, dependency invalidation and retention are a later stage.
H127/R129 and the joint prefix/overlay handoff are not delivered by this PR.

## Ownership and inputs

`aggregation/core.py` accepts D126's frozen `BarData` and `SeriesKey`; it does
not define a second canonical bar. `AcceptedComponent` adds the actual
exclusive end and an optional `InputRevision`. Complete routing identity,
provider, venue, adjustment, session/volume semantics and canonical interval
basis remain in `SeriesKey`. Callers must use distinct semantic keys for
distinct calendars; a plain duration is not sufficient calendar identity.

`InputRevision(series, domain, version)` describes an acquisition view, not a
transport sequence or a per-row update counter. D126's reader must supply the
view token after its normal fencing checks. Combining different tokens for
the same source/domain fails; different domains are retained separately and
never numerically ordered. Missing tokens remain explicitly unknown.
No revision counter, persistence journal or writer is created here. Legacy
adapters use the pure primitives while retaining their existing D126 fences;
they do not yet construct versioned shared blocks from these envelopes.

Source admission selects one accepted version per leaf before aggregation.
The reference reducer sorts input and rejects duplicate/overlapping leaves.
The realtime adapter keeps its existing sequence, monotonicity and explicit
correction policy. A cumulative snapshot replaces its existing component;
corrections rebuild from the accepted index. Extrema are recomputed, never
subtracted from an old maximum/minimum. Native snapshot and tick execution
remain with their existing owners.

## Pure contract

The core has no network, DB, event bus, global session, hidden current time or
async lifecycle. Calendar boundaries and exclusions are explicit facts. Its
runtime import does not load DataManager or SQLite. Source freshness,
calendar/source qualification and mutation admission remain outside it.

`AggregateSummary` contains target identity, immutable `FieldSummary`,
coalesced occupied ranges, explicit closure facts, source view dependencies,
revision availability, source authority and `k130-fsum-v1` algorithm identity.
It contains neither a retained leaf list nor a mutable reference to input.
Ranges cost O(number of holes), and dependencies O(source/domain count).
This is a caller-owned value, not a cache: B130 must charge its actual retained
size to D126 and bound fragmentation before storing it.

- OHLC is chronological first/max/min/last. Additive fields combine sufficient
  statistics, retaining unknown as `None`. Known zero remains a valid value.
- Enhanced fields continue through `kline_metrics` capability and validity
  rules; a masked placeholder cannot become a reported zero.
- Accepted leaf values use the existing eight-decimal query normalization;
  raw-row reconstruction now applies the same boundary before summing, so
  sub-precision quantities cannot differ solely because of the decoder path.
  A final projection also uses eight decimal places. Partial summaries keep
  unrounded totals and combine with `math.fsum`; trade counts use exact ints.
  Same accepted inputs and chronological order reproduce the same projection
  in the tested cases. Arbitrary grouping is compared with absolute tolerance
  `1e-8` or relative tolerance `1e-12`, not a claim of bitwise associativity.
  Unrounded native authoritative records are not rewritten by this contract.
- VWAP is quote total / base total when those volume semantics are compatible;
  consumers must not interpret it as a price for contract-count/inverse volume
  without conversion. Missing sufficient statistics yield `None`.
- Coverage is separate from closure and authority. An occupied contiguous
  prefix with a forming tail can expose enhanced totals; a closed partial
  prefix, overlap, hole or cross-boundary component cannot prove completeness.
- Session exclusions must be explicit; a missing input is not a holiday.
  An empty or fully excluded range does not manufacture a zero-volume candle.

Two explicit close policies preserve the existing source contracts:

| Policy | Consumers | Evidence |
| --- | --- | --- |
| `EXPLICIT` | realtime finalizers, reference authoritative result | Complete exact coverage and every component explicitly closed |
| `SUCCESSOR` | historical query preview compatibility | Complete exact coverage and latest component closed; successor may confirm an earlier missed close |

`AggregateSummary.is_authoritative` always requires explicit closure plus
trusted source quality. Successor inference, wall-clock expiry and software
shutdown cannot manufacture authority. Persisted/adopted state is not a
summary flag; the existing commit owner still decides those transitions.

## Initial production adapters

| Path | K130 consumption | Execution owner retained |
| --- | --- | --- |
| Fixed history | Shared additive totals, field projection and coverage/finality policy; optimized one-pass scanner | #127 grouping, pagination, source demand and materialization |
| Streaming history | Same fixed reducer after bounded reverse-page assembly | #127 `FixedHistoryStream` |
| Calendar/session/month history | Shared field reducer and explicit calendar prefix proof | Existing interval/calendar policy |
| Strict stored reconstruction | Shared fields; actual source calendar ends and explicit closed-source qualification | Reconciler / existing writer |
| Live custom components | Shared fields and range proof after existing snapshot admission | #129 component index and lifecycle |
| Live amendment/finalizer | One shared coverage proof, including exact target end | Existing finalizer / durable delivery |

Fixed history does not allocate `AcceptedComponent` per row or run a realtime
pipeline. Its optimized scanner is a contract-tested alternative backend.
Live snapshots cache normalized immutable scalar references once at admission;
they do not repeat source normalization for every target rebuild. Legacy
BarState diagnostic counters are retained behind their field mask; only
qualified fields appear in public values.

Two boundary corrections are intentional: a source ending beyond a target
does not close it; and coarse `SessionCalendar` daily labels use the canonical
end, matching their expected-open grid, rather than adding 24h to an actual
09:30 label. Strict reconstruction also uses the actual end of a source month
instead of treating every month as 30 days. Existing source authority and
native-vs-derived replacement rules are preserved.

## Next interfaces and rollback

B130 can consume these values plus D126's existing commit/fencing and common
budget interfaces. It owns bounded storage, block versions, build deduplication,
leases and dependency invalidation. It must reject mismatched algorithm/view
tokens and must not infer persisted/adopted status from complete coverage.
H127 and R129 then consume B130; this stage adds no second downloader,
revision ledger, publication journal or initialization state machine.

Rollback is a source-code revert of this stage and rebuild of transient state.
There is no new persisted format, background owner or feature toggle requiring
dual writes. Keep all D126 revisions, deletion evidence and source receipts.
The phase does not declare #130 or the 157-item product acceptance complete.
