# H127 minimum versioned history read interface

This delivers the minimum 127-D handoff from #127 to future #129 initialization,
on D126 + K130 + B130 (PR #174). It does not implement the mixed-source planner,
network scheduling, or realtime prefix/overlay state machine.

## API and acceptance point

```python
source = SeriesKey("BTC-USDT-SWAP", "1d", exchange="okx", market_type="futures")
cursor = None
while True:
    with data_manager.read_history_blocks(
        source, start_ms, end_ms, max_rows=256, direction="asc",
        cursor=cursor, cancel=cancel_event,
        required_fields=("open", "high", "low", "close", "volume"),
    ) as page:
        # These immutable values are valid only within this leased context.
        # Stage consumer-owned work, but do not publish/adopt it here.
        staged = consume(page.blocks)
    receipt = page.receipt
    # Apply the consumer's D126 revision/generation fence at actual adoption.
    # A successful historical read is not a persisted/adopted result.
    if not receipt.complete:
        handle_unavailable(receipt.unavailable_ranges, receipt.missing_fields)
        break
    accept_staged(staged, receipt.revisions)
    cursor = receipt.continuation
    if cursor is None:
        break
```

Use this synchronous API on the existing storage executor, not the event loop.
DataManager delegates to QueryEngine, which owns canonical row access and I/O
diagnostics. No new HTTP endpoint or realtime initializer is introduced.

One context owns one page. B130 read views verify source revisions before and
after the whole context. The immutable receipt and continuation are available
only after a successful exit; cancellation, caller errors, changed sources,
storage rebind, or failed revision reads leave no successful receipt. Reading
`page.blocks` after exit raises. Closed page handles retain only their receipt,
not released blocks or decoded rows. Consumers retaining raw values after
lease expiry own their lifetime and memory accounting.

The receipt is a historical snapshot proof, not a perpetual assertion that the
source is still current. R129 must check its own generation and the D126/B130
revision contract when adopting a staged prefix. Historical prefix and live
overlay ownership and publication remain R129/J work.

## Qualified v1 sources

- Canonical native fixed-epoch intervals from 1m through 1d on Binance/OKX,
  using the legacy default full series identity and declared native capability.
- A configured calendar must explicitly be AlwaysOpenCalendar. Without a
  calendar service, the restricted built-in continuous crypto grids are used.
  Unknown/session calendars, non-default identities, derived/weekly/monthly/
  zoned intervals and unaligned endpoints are rejected, never replaced by 1m.
- Endpoints are actual half-open milliseconds on the source grid. The range
  must end at or before the currently elapsed source boundary. Time passing
  only caps the request; it does not create source finality.
- Full canonical rows retain actual close_time. Rows must lie on the requested
  grid, have the exact source end, and carry existing trusted-final provenance
  and closure evidence. The compact chart projection cannot prove actual ends
  and is not used for this interface.

This is stored-history qualification. It does not prove native coarse/fine
interchangeability, introduce another exchange source, or change canonical
quality arbitration. Accepted components and all summary mathematics come from
K130, including normalization, unknown enhancements and coverage.

## Paging, quality and continuation

Each request scans at most 256 expected source slots. Ascending and descending
continuations advance by the page's requested boundary, not by returned rows,
so an empty page cannot loop forever. Blocks within every page are chronological.
The same caller may change page size on continuation without overlap.

The receipt separates requested range, page range, unavailable closed coverage,
missing required fields, page completeness, and continuation. No continuation
means only the end of the requested range, not source/listing exhaustion.
Unavailable coverage may be missing, untrusted, forming, or malformed-boundary
data; it is not proof of a provider gap and does not submit repairs. Unknown
enhanced fields remain unknown. Callers explicitly select required fields.

The stateless cursor carries full source identity, original range, direction,
required fields, next position, and the source revision vector. A changed
source or storage/process binding rejects continuation, even if a new database
has the same numeric revision. Unrelated-series changes and rolled-back writes
do not invalidate it. No cursor registry, tombstone ledger or snapshot database
is added. Cross-process cursor portability is not supported.

## Ownership, sharing and limits

The reader reuses DataManager's single B130 manager. Globally aligned groups of
16 source rows identify canonical source blocks; clipped edges use their actual
ranges. The bounded `h127-canonical-v1` input qualifier separates these proven
committed inputs from legacy in-memory projections. It is not another algorithm
or durable revision. Different consuming target intervals can use the same
source blocks. The initial B130 query adapter's input-digest keys are distinct.

A warm page performs no candle-row read or decode; revision checks still use
D126. A partially cold page performs one bounded canonical range read, then
pure summary builders run outside storage/manager locks. Simultaneous cold
readers may each read a page, but identical block construction joins B130's
singleflight. This stage does not claim cold I/O/decode singleflight or replace
the existing history scheduling infrastructure.

All leases release on context exit, including failures. Cancelling an owner or
joiner does not cancel another consumer's shared construction. Active pins,
retired blocks and rebuilds obey B130 limits; no second retained block cache is
introduced. Cache-only probes never launch a builder.

The existing D126 history-query owner reserves 32 KiB for bounded page metadata.
Only a cold read also reserves `(expected_slots * 4096) + 4096` bytes for raw rows
and decoding; raw retained values exceeding half that allowance are rejected.
Decoded inputs are dropped before caller work. B130 separately reserves build
work and charges retained summaries. Limits are conservative Python-value
allowances, not an allocator/RSS hard cap. Budget exhaustion is an explicit
MemoryBudgetExceeded exception, never a manufactured missing range.

Fixed-size diagnostics report attempted page reads, candle reads/rows, cache
hits, accepted/partial pages, accepted blocks, failures and cancellations.
Revision I/O is separate from candle-row reads. The API neither warms BarCache,
starts network/backfill work, nor writes target materialization. Existing
query/reconciler/materialization and durable delivery owners remain unchanged.

## Qualification and remaining work

`test_history_block_reader.py` exercises the actual DataManager/SQLite boundary,
both paging directions, fields/finality, bounds, source errors, amendment and
deletion (including empty deletion and another SQL process), rollback, rebind,
consumer failures, owner/joiner cancellation, budget pressure and released-value
lifetime. It is included in the backend contract CI suite.

The companion QA probe reads a copy of recorded public native-app market rows,
checks cold/warm I/O and independent Decimal output, and demonstrates cursor
invalidation on an isolated copy. This is backend interface qualification, not
a new native release or evidence that R129 already consumes this interface.

Mixed-source planning, cold read coalescing, broader source/calendar identities,
history priority/fairness and the actual R129 initialization remain separate
127-A/B/C and R129/J stages. Rollback removes this reader and its facade method;
there is no new durable format, writer or migration to reverse.
