# Strategy Internal Stage 13 Ledger Ownership Audit

Status: closed on 2026-06-05 as a documentation-only ownership audit. Runtime
behavior, conformance, fixtures, snapshots, matrix output, and public JSON are
unchanged.

Stage 13 Slice 2 reviewed the current broker state split before any positive
multi-entry or `pyramiding` behavior is accepted. The live code already contains
a private `TradeLedger`, but the executable strategy subset remains one
net-long position with legacy singleton broker mirrors.

## Current Owners

`TradeLedger` currently owns an internal vector of `OpenTrade` records and a
cached aggregate `NetPosition`.

Current ledger responsibilities:

- store the one supported open long trade after a successful entry fill;
- mirror entry id, entry price, quantity, entry bar/time, entry commission, and
  current open-trade extremes for the supported single open trade;
- calculate FIFO allocations for future multi-trade exits;
- apply allocations and rebuild aggregate net position in internal tests.

Current ledger limitations:

- `open_long()` clears existing open trades before pushing the new long trade;
- normal runtime paths do not append multiple open trades;
- `update_extremes()` only updates the first open trade;
- allocation helpers are not a public compatibility claim and are not routed
  through accepted multi-entry behavior.

`BrokerState` still owns the executable one-net-long compatibility surface.

Legacy singleton mirrors:

- `position_size`;
- `avg_price`;
- `entry_id`;
- `entry_bar_index`;
- `entry_time`;
- `open_entry_commission`;
- `open_trade_max_high`;
- `open_trade_min_low`;
- `open_trade_equity_on_entry`;
- `open_trade_min_equity_before_entry`;
- `open_trade_max_equity_before_entry`.

Aggregate/accounting state still owned directly by `BrokerState`:

- `cash`;
- `min_equity_before_open_trade`;
- `max_equity_before_open_trade`;
- `max_runup`, `max_runup_percent`;
- `max_drawdown`, `max_drawdown_percent`;
- `max_contracts_held_long`;
- public `orders`, `trades`, `position`, `equity`, and `diagnostics`;
- `closed_trade_metrics`;
- the internal pending-entry and pending-exit `OrderBook`.

## Live Code Evidence

- `crates/pine-runtime/src/strategy/broker/mod.rs` stores both legacy singleton
  mirrors and `trade_ledger`.
- Successful entries call the legacy mirror recorder and then
  `trade_ledger.open_long()`, preserving one-open-trade behavior.
- `crates/pine-runtime/src/strategy/broker/fills.rs` updates both singleton
  mirrors and `trade_ledger` during close, exit, and margin-call reductions.
- `crates/pine-runtime/src/strategy/broker/accounting.rs` still reads singleton
  mirrors for open-trade namespace functions, mark-to-market values,
  runup/drawdown, capital held, and `strategy.position_avg_price`.
- `crates/pine-runtime/src/strategy/broker/exits.rs` and
  `active_entry_brackets.rs` still route matching through singleton
  `position_size`, `avg_price`, and `entry_id` checks.
- `crates/pine-runtime/src/strategy/broker/tests.rs` already covers the current
  ownership invariants:
  - `trade_ledger_mirrors_current_single_long_entry`;
  - `trade_ledger_tracks_partial_and_final_long_reductions`;
  - `trade_ledger_allocates_omitted_entry_by_global_fifo`;
  - `trade_ledger_allocates_matching_entry_by_fifo`;
  - `trade_ledger_applies_allocations_and_rebuilds_net_position`.

## Migration Order

Stage 13 should keep behavior unchanged until each migration point has tests.

1. Keep legacy singleton mirrors as the executable public aggregate source while
   introducing explicit ledger mutation helpers for any future append behavior.
2. Add positive multi-entry behavior only after the broker can update ledger and
   aggregate mirrors from one helper instead of parallel ad hoc assignments.
3. Convert `strategy.opentrades.*()` field functions from singleton
   `trade_num == 0` assumptions to ledger-indexed reads before claiming multiple
   open-trade namespace support.
4. Convert close and exit fills to allocate through `TradeLedger` first, then
   derive aggregate `position_size` and `avg_price` from `NetPosition`.
5. Keep public `StrategyResult` aggregate-only until a separate schema stage
   decides whether open-trade or pending-order output is exposed.

## Boundaries

Slice 2 does not support:

- `pyramiding`;
- multiple runtime open trades;
- short exposure or reversal;
- `strategy.order()`;
- `close_entries_rule`;
- price-based same-tick pyramiding exceptions;
- public pending-order or open-trade ledger output.

The supported strategy subset remains the one recorded in
`tests/fixtures/conformance.tsv`.

## Slice 3 Follow-Up

Stage 13 Slice 3 added `BrokerState::record_open_long_trade()` as the first
private helper for the current long-entry fill ownership handoff. It keeps the
same one-open-trade behavior by updating legacy singleton mirrors and
`TradeLedger` together, and it does not append multiple open trades.

## Slice 4 Follow-Up

Stage 13 Slice 4 added `TradeLedger::append_long()` as an internal append helper
and test-backed weighted-net-position invariant. Runtime `open_long()` still
clears existing open trades before appending, so accepted scripts keep the same
one-net-long behavior.

## Slice 5 Follow-Up

Stage 13 Slice 5 added
`BrokerState::sync_aggregate_position_from_ledger()` and routes the current
long-entry fill handoff through it after `TradeLedger` updates. The helper only
syncs aggregate `position_size` and `avg_price`; entry-id-specific mirrors,
open-trade namespace reads, runup/drawdown state, and public output stay on the
current one-open-trade path.

## Slice 6 Follow-Up

Stage 13 Slice 6 added
`BrokerState::apply_trade_allocations_and_sync_position()` for the existing
long close, supported exit, and long margin-call reduction paths. It keeps
aggregate `position_size` and `avg_price` derived from `TradeLedger` after
allocation updates while preserving legacy entry-id and open-trade mirrors.

## Slice 7 Follow-Up

Stage 13 Slice 7 added the internal `pyramiding_limit` field with a default of
`1` and routes current long-entry admission through `can_open_long_entry()`.
This is still the current no-pyramiding behavior; no public `strategy()`
`pyramiding` declaration is accepted yet.

## Slice 8 Follow-Up

Stage 13 Slice 8 changed `BrokerState::open_trade_count()` to read
`TradeLedger::open_count()` instead of singleton mirrors. Accepted scripts still
produce only `0` or `1` open trades, but the internal count path is ready for
future multi-entry behavior.

## Slice 9 Follow-Up

Stage 13 Slice 9 changed `strategy.opentrades.*` field helpers to read the
requested open-trade index from `TradeLedger::open_at()`. Accepted scripts still
produce only index `0`, but internal tests now cover indexes `0` and `1` before
public multi-entry behavior is accepted.

## Slice 10 Follow-Up

Stage 13 Slice 10 accepts the first public `strategy(..., pyramiding=N)` subset
for positive integer const values and same-direction long market entries.
`StrategySettings::pyramiding_limit` now initializes `BrokerState`, open long
entries append to `TradeLedger` while the limit allows them, and aggregate
`position_size`, `avg_price`, and `max_contracts_held_long` synchronize from
the ledger. Price-based same-tick entry exceptions, shorts, reversals, and
broader multi-entry exit/reporting semantics remain outside this slice.

## Slice 11 Follow-Up

Stage 13 Slice 11 changes `strategy.close(id)` matching from the legacy
singleton `entry_id` mirror to `TradeLedger::open_quantity_for_entry()`.
Supported close quantities now clamp to the requested entry id's open ledger
quantity, so closing one pyramided long entry can leave another entry open with
aggregate `position_size` and `avg_price` resynced from the ledger.
Multi-entry `strategy.close_all()` and `strategy.exit` remain future slices at
this point in the sequence.

## Slice 12 Follow-Up

Stage 13 Slice 12 changes `strategy.close_all()` to allocate the full aggregate
long position through the open-trade ledger. Multi-entry close-all now records
one closed trade per matched ledger entry and clears all pending exits before
resyncing aggregate position state to flat. Multi-entry `strategy.exit` remains
a future slice.

## Slice 13 Follow-Up

Stage 13 Slice 13 is a no-behavior-change split of pending exit state from
`exits.rs` into `pending_exits.rs`. The split keeps `PendingExitBook`,
`PendingExit`, deferred relative exits, trailing state, and quantity helpers in
one data module so the next multi-entry `strategy.exit` slice can change
matching/reservation behavior without pushing `exits.rs` back against the
structure guardrail.

## Slice 14 Follow-Up

Stage 13 Slice 14 changes absolute `strategy.exit` matching from the legacy
singleton `entry_id` mirror to `TradeLedger::open_quantity_for_entry()`.
Supported absolute stop/limit exits can now target an open pyramided long entry
by `from_entry` and fill through ledger allocation while other open entries
remain live. Relative profit/loss tick conversion and broader bracket/trailing
multi-entry semantics remain future slices.

## Slice 15 Follow-Up

Stage 13 Slice 15 adds a broker-only ledger helper for reading the first matched
open entry price by id, then uses it for supported single-trigger
`strategy.exit(..., profit=...)` and `strategy.exit(..., loss=...)` price
conversion. This moves the accepted unique-entry pyramiding subset away from the
aggregate `avg_price` basis without yet implementing same-ID fan-out or
entry-specific bracket/trailing relative legs.

## Slice 16 Follow-Up

Stage 13 Slice 16 changes `fill_pending_exit()` to preserve ledger allocations
when one pending exit closes multiple open trades with the same entry id. Public
orders and closed trades now fan out per allocation, so each matched open trade
keeps its own entry price, entry bar/time, quantity, and proportional commission
instead of being collapsed into one aggregate trade. Omitted-`from_entry`
persistent all-entry exit behavior remains a future slice.

## Slice 17 Follow-Up

Stage 13 Slice 17 extends the entry-specific price basis from single-trigger
`profit`/`loss` exits to supported bracket relative legs. Active and deferred
`stop+profit`, `loss+limit`, and `loss+profit` bracket placement now computes
relative legs from the matched ledger entry price before routing through the
existing pending-exit and allocation logic. Trailing `trail_points` and
omitted-`from_entry` persistent all-entry exits remain future slices.

## Slice 18 Follow-Up

Stage 13 Slice 18 extends the entry-specific price basis to supported trailing
`trail_points + trail_offset` exits. Active trailing placement and deferred
relative trailing resolution now compute activation from the matched ledger
entry price, then reuse the existing trailing activation, ratchet, fill, and
allocation paths. Omitted-`from_entry` persistent all-entry exits remain a
future slice.

## Slice 19 Follow-Up

Stage 13 Slice 19 introduces the first omitted-`from_entry` all-entry exit
path. The runtime encodes omitted `from_entry` as an internal empty-string
sentinel for the supported absolute stop/limit shapes; broker placement treats
that sentinel as the current aggregate open quantity, and pending-exit fills
allocate through `TradeLedger::allocate_exit_fifo(None, qty)`. This closes all
currently open matching long ledger entries while preserving one public exit
order and one closed trade per ledger allocation. Persistent future-entry
behavior and omitted-`from_entry` relative/bracket/trailing forms remain future
slices.

## Slice 20 Follow-Up

Stage 13 Slice 20 keeps the Slice 19 omitted-`from_entry` absolute stop/limit
exit active for later entries. After a later long entry fills, broker entry-fill
paths expand the existing all-entry full stop/limit pending exit to the new
aggregate `position_size` and update its placement bar to the entry fill bar.
The existing pending-exit fill path then allocates through
`TradeLedger::allocate_exit_fifo(None, qty)`, so both earlier and later open
ledger entries close when the persisted absolute exit triggers. Omitted-
`from_entry` relative, bracket, and trailing all-entry exits remain future
slices.

## Slice 21 Follow-Up

Stage 13 Slice 21 adds the first omitted-`from_entry` relative all-entry exit
path for current open entries. The broker now expands a full omitted
`profit=ticks` call into one pending limit exit per currently open unique entry
id, with each limit price converted from that entry's own entry price. The
pending exit fill path remains the existing from-entry allocation path. Duplicate
same-id per-trade relative targets, relative future-entry persistence, `loss`,
bracket, and trailing all-entry forms remained future slices.

## Slice 22 Follow-Up

Stage 13 Slice 22 mirrors Slice 21 for omitted-`from_entry` loss ticks. The
broker expands a full omitted `loss=ticks` call into one pending stop exit per
currently open unique entry id, with each stop price converted from that entry's
own entry price. The duplicate same-entry-id case still preserves the no-op
boundary because correct support requires per-trade targeting beyond the current
`id + from_entry` pending-exit identity. Relative future-entry persistence,
bracket, and trailing all-entry forms remain future slices.

## Slice 23 Follow-Up

Stage 13 Slice 23 extends the same current-open-entry expansion to the omitted-
`from_entry` `loss+profit` bracket shape. The broker expands a full omitted
`loss+profit` call into one pending bracket exit per currently open unique entry
id, with both stop and target prices converted from that entry's own entry
price. The duplicate same-entry-id case still preserves the no-op boundary, and
other omitted-`from_entry` bracket shapes, trailing exits, and relative
future-entry persistence remain future work.

## Slice 24 Follow-Up

Stage 13 Slice 24 adds the omitted-`from_entry` `stop+profit` bracket shape to
the current-open-entry expansion. The broker expands a full omitted
`stop+profit` call into one pending bracket exit per currently open unique entry
id, preserving the absolute stop price and converting the profit target from
each entry's own entry price. Duplicate same-entry-id entries, `loss+limit`,
`stop+limit`, trailing exits, and relative future-entry persistence remain
future work.

## Slice 25 Follow-Up

Stage 13 Slice 25 adds the omitted-`from_entry` `loss+limit` bracket shape to
the current-open-entry expansion. The broker expands a full omitted
`loss+limit` call into one pending bracket exit per currently open unique entry
id, converting the loss stop from each entry's own entry price and preserving
the absolute limit price. Duplicate same-entry-id entries, `stop+limit`,
trailing exits, and relative future-entry persistence remain future work.

## Slice 26 Follow-Up

Stage 13 Slice 26 closes the current-open-entry omitted-`from_entry` bracket
family with the absolute `stop+limit` shape. Unlike the mixed relative bracket
slices, this path does not require per-entry price conversion: the builtin gate
now allows full omitted `stop+limit` brackets to reach the existing all-entry
pending-exit path, which allocates fills through FIFO ledger allocation and
emits one public exit order per closed ledger allocation. Trailing exits,
relative future-entry persistence, and duplicate same-entry-id relative targets
remain future work.

## Slice 27 Follow-Up

Stage 13 Slice 27 adds the omitted-`from_entry` full `trail_price+trail_offset`
trailing shape for currently open pyramided long entries. The builtin gate now
allows that absolute-activation trailing form to reach the existing all-entry
pending-exit path, so trailing activation and later stop fills reuse broker-owned
trailing state plus FIFO ledger allocation. Omitted-`from_entry` `trail_points`
trailing, relative future-entry persistence, duplicate same-entry-id relative
targets, and public pending-order schema remain future work.

## Slice 28 Follow-Up

Stage 13 Slice 28 adds the omitted-`from_entry` full
`trail_points+trail_offset` trailing shape for currently open pyramided long
entries whose entry ids are unique. The broker now expands one omitted
trail-points call into one entry-specific trailing pending exit per current
ledger entry, computing each activation price from that entry's own entry price
and allocating later fills through the existing ledger path. Relative
future-entry persistence, duplicate same-entry-id relative targets, and public
pending-order schema remain future work.
