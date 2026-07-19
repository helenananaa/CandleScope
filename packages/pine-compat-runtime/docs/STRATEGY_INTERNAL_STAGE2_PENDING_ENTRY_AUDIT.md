# Strategy Internal Stage 2 Pending Entry Audit

Status: closed on 2026-06-02.

This audit tracks `docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md` Stage 2:
Pending Entry And Order Timing Foundation. Stage 2 introduces the internal
pending-entry model needed by Pine-compatible order timing. It must not expose
an unstable public pending-order shape.

## Slice 0: Internal Pending Entry Book

Status: closed on 2026-06-02.

Goal: add the first internal pending-entry representation without changing
current `strategy.entry` runtime behavior.

Context checked:

- `docs/STRATEGY_INTERNAL_EXECUTION_PLAN.md` Stage 2 scope and acceptance;
- `crates/pine-runtime/src/strategy/broker/mod.rs`;
- `crates/pine-runtime/src/strategy/broker/exits.rs`;
- `crates/pine-runtime/src/builtins/strategy.rs`;
- `crates/pine-runtime/src/runtime/historical.rs`;
- `crates/pine-runtime/src/tests/strategy.rs`;
- existing strategy runtime fixtures and snapshots.

Findings:

- Current `strategy.entry` runtime dispatch fills immediately at the current
  bar close through `BrokerState::entry_long`.
- Current `strategy.exit` pending records are evaluated after script execution
  on each bar, and creation-bar fills are blocked through
  `last_update_bar_index`.
- Stage 2 needs a separate internal entry-order representation before runtime
  dispatch can move away from immediate entry fills.

Implemented:

- added `crates/pine-runtime/src/strategy/broker/entries.rs`;
- added `PendingEntry`, `PendingEntryBook`, `PendingEntryDirection`, and
  `PendingEntryKind`;
- added `BrokerState::place_pending_market_long_entry` as an internal broker
  API for the current long-market entry subset;
- kept `strategy.entry` runtime dispatch on the existing immediate-fill path;
- added broker tests proving pending market entries:
  - record internal state;
  - do not emit public orders, trades, positions, or result changes;
  - replace the same pending entry id;
  - reject invalid quantity through the existing `E_STRATEGY_QTY` diagnostic;
  - do not queue while the current one-net-long position is already open.

Compatibility boundary:

- No public JSON shape changed.
- No conformance or matrix row changed.
- No Pine behavior was widened.
- `strategy.entry` still fills immediately at the current bar close until a
  later Stage 2 slice explicitly switches runtime dispatch to the pending-entry
  path with fixture-backed timing.
- Entry `limit`, `stop`, and stop-limit forms remain out of scope for Stage 2
  and are still reserved for Stage 5.

Validation:

```text
cargo fmt --all --check
cargo test -p pine-runtime pending_market_entry
cargo test -p pine-runtime strategy
```

Result:

- `cargo fmt --all --check` passed.
- `cargo test -p pine-runtime pending_market_entry` passed with 4 tests.
- `cargo test -p pine-runtime strategy` passed with 189 unit tests plus the
  matching profile fixture.

Next slice candidate:

- Decide and fixture the default historical fill policy for pending market
  entries, then add the broker fill primitive. The likely conservative next
  step is an internal broker-only fill method that makes a pending market long
  entry eligible only after its creation bar, without yet changing runtime
  dispatch.

## Slice 1: Internal Pending Market Entry Fill Primitive

Status: closed on 2026-06-02.

Goal: lock the first broker-only historical fill rule for pending long market
entries without wiring `strategy.entry` runtime dispatch to the pending-entry
path.

Implemented:

- added `PendingEntryBook::take_first_eligible_market_long`;
- added `BrokerState::fill_pending_market_long_entries`;
- selected the first Stage 2 internal historical policy:
  - a pending market entry is not eligible on its creation bar;
  - it becomes eligible on a later bar;
  - the broker-only primitive fills at the provided fill price;
  - only the first eligible pending entry fills, and remaining pending entries
    are cleared to preserve the current one-net-long/no-pyramiding boundary;
  - if a position is already open, the pending-entry book is cleared without
    emitting a second entry.

Compatibility boundary:

- `strategy.entry` runtime dispatch still calls `BrokerState::entry_long` and
  still fills immediately at the current bar close.
- The new fill primitive is broker-only and is not called from
  `HistoricalRuntime`.
- No runtime fixture, conformance row, matrix snapshot, or host output changed.
- Same-calculation `strategy.entry` plus `strategy.exit` attachment is not
  implemented yet; this slice only creates the fill primitive that later slices
  can wire into runtime timing.

Validation:

```text
cargo fmt --all --check
cargo test -p pine-runtime pending_market_entry
```

Result:

- `cargo fmt --all --check` passed.
- `cargo test -p pine-runtime pending_market_entry` passed with 8 tests.

Next slice candidate:

- Wire `strategy.entry` runtime dispatch to the pending-entry path under the
  selected next-bar-open policy, then update runtime fixtures/snapshots and
  strategy documentation for the user-visible timing change.

## Slice 2: Broker-Only Exit Attachment To Pending Entries

Status: closed on 2026-06-02.

Goal: make the broker capable of attaching supported pending exits to active
pending entries before runtime dispatch switches `strategy.entry` to the
pending-entry path.

Context:

- Existing runtime fixtures often call `strategy.entry` and `strategy.exit` in
  the same calculation.
- Switching entry runtime dispatch to pending entries before supporting this
  attachment would turn those exits into `E_STRATEGY_EXIT_ENTRY` diagnostics.
- This slice therefore changes only broker matching logic, not runtime dispatch.

Implemented:

- added `PendingEntryBook::quantity_for_id`;
- updated broker exit placement so `from_entry` may match either:
  - the current open long entry; or
  - an active pending entry id;
- when matching an active pending entry, the pending entry quantity is used as
  the reservation base;
- kept unknown `from_entry` ids on the existing `E_STRATEGY_EXIT_ENTRY`
  diagnostic path;
- added broker tests for:
  - full stop attachment to a pending entry without public fill;
  - fixed-quantity reservation against pending entry quantity;
  - unknown `from_entry` rejection while another pending entry exists.

Compatibility boundary:

- Runtime `strategy.entry` still fills immediately at the current bar close.
- Runtime `strategy.exit` behavior remains unchanged because runtime has not
  been switched to create pending entries.
- No public strategy output shape changed.
- Profit/loss and entry-relative trailing attachment are not widened by this
  slice; they still depend on later runtime design because they derive prices
  from an entry fill price.

Validation:

```text
cargo fmt --all
cargo test -p pine-runtime pending_market_entry
```

Result:

- `cargo fmt --all` completed.
- `cargo test -p pine-runtime pending_market_entry` passed with 11 tests.

Next slice candidate:

- Add the runtime timing switch for market entries with fixtures showing the
  next-bar-open fill policy, while keeping same-calculation absolute
  `strategy.exit` attachment alive.

## Slice 3: Entry-Relative Exit Attachment Guard

Status: closed on 2026-06-02.

Goal: prevent entry-relative exit forms from attaching to pending entries before
the runtime has a deferred price-resolution design.

Context:

- Absolute exit forms such as `stop`, `limit`, and `trail_price` can be stored
  before an entry fill because their trigger prices are already explicit.
- Entry-relative forms such as `profit`, `loss`, and `trail_points` derive
  prices from the entry fill price.
- If runtime dispatch is later switched to pending entries without a guard,
  those forms could otherwise resolve against the current flat broker average
  price instead of the future entry fill price.

Implemented:

- added `BrokerState::reject_entry_relative_exit_for_pending_entry`;
- guarded broker `profit`, `loss`, and `trail_points` placement when
  `from_entry` matches only a pending entry;
- guarded runtime `strategy.exit` dispatch before bracket or trailing paths
  convert `profit`, `loss`, or `trail_points` into prices;
- kept the existing `E_STRATEGY_EXIT_ENTRY` diagnostic for these unsupported
  pending-entry relative forms;
- added broker tests for pending-entry rejection of `profit`, `loss`, and
  `trail_points` attachments.

Compatibility boundary:

- Absolute pending-entry exit attachment from Slice 2 remains available
  internally.
- Entry-relative pending-entry exit attachment remains unsupported until a later
  slice explicitly designs deferred price resolution from the actual entry fill.
- Runtime `strategy.entry` remains on the immediate-fill path.

Validation:

```text
cargo fmt --all --check
cargo test -p pine-runtime pending_market_entry
```

Result:

- `cargo fmt --all --check` passed.
- `cargo test -p pine-runtime pending_market_entry` passed with 14 tests.

Next slice candidate:

- Switch runtime market-entry dispatch to the pending-entry path for absolute
  exit attachment only, then update runtime fixtures/snapshots and document the
  still-unsupported entry-relative same-calculation boundary.

## Slice 4: Runtime Market Entry Next-Bar-Open Fill

Status: closed on 2026-06-02.

Goal: switch `strategy.entry` runtime dispatch to the pending-entry path and
lock the first user-visible historical market-entry timing policy.

Implemented:

- changed runtime `strategy.entry` dispatch to place an internal pending market
  long entry instead of filling immediately at the current bar close;
- filled eligible pending market long entries at the next historical bar open,
  before builtin strategy state variables are published for that bar;
- preserved public strategy output shape: pending entries are internal only, and
  public `orders`/`position`/`equity` records appear only after a real fill;
- kept no-pyramiding behavior by clearing stale pending entries when a position
  is already open;
- kept same-calculation absolute `strategy.exit` attachment to the active entry
  id alive, including fixed `qty` and `qty_percent` reservations against the
  pending entry quantity;
- kept same-calculation entry-relative `profit`, `loss`, and `trail_points`
  attachment unsupported through the existing `E_STRATEGY_EXIT_ENTRY` runtime
  diagnostic path;
- updated strategy runtime tests for next-bar-open entry fills, state/count
  visibility, mark-to-market equity, and existing supported exit dispatch forms.

Compatibility boundary:

- Market entries now fill on the next historical bar open. Scripts do not see the
  position on the entry creation bar.
- `strategy.close` remains a current-bar-close close of an existing filled long
  entry.
- Absolute same-calculation exit attachment is supported only when `from_entry`
  matches the active pending entry id. Arbitrary future binding for unmatched
  ids remains unsupported.
- Entry-relative exit attachment to a pending entry remains unsupported until a
  later slice designs deferred price resolution from the actual fill price.
- No public pending-order, reservation, remaining-quantity, or schema field was
  added.

Validation:

```text
cargo fmt --all --check
cargo test -p pine-runtime pending_market_entry
cargo test -p pine-runtime strategy
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli --bin pine-compat strategy_exit_
cargo test -p pine-wasm strategy
python3 -m pytest python/tests/test_bindings.py -q
cargo test -p pine-runtime runtime_fixtures_match_incremental_append_execution
cargo clippy -p pine-runtime --all-targets -- -D warnings
git diff --check
scripts/verify.sh
```

Result:

- `cargo fmt --all --check` passed.
- `cargo test -p pine-runtime pending_market_entry` passed with 14 tests.
- `cargo test -p pine-runtime strategy` passed with 199 strategy-filtered unit
  tests plus the matching profile fixture.
- `cargo test -p pine-cli runtime_outputs_match_golden_snapshots` passed.
- `cargo test -p pine-cli matrix_output_matches_golden_snapshot` passed.
- `cargo test -p pine-cli --bin pine-compat strategy_exit_` passed with 8
  host-shape tests.
- `cargo test -p pine-wasm strategy` passed with 20 strategy host tests.
- `python3 -m pytest python/tests/test_bindings.py -q` passed with 46 Python
  binding tests after rebuilding and reinstalling the local wheel.
- `cargo test -p pine-runtime runtime_fixtures_match_incremental_append_execution`
  passed.
- `cargo clippy -p pine-runtime --all-targets -- -D warnings` passed.
- `git diff --check` passed.
- `scripts/verify.sh` passed, including workspace clippy, workspace tests,
  structure guardrails, wasm32 check, Python wheel build/install, and Python
  binding tests.

Closeout:

- Stage 2 is closed. Runtime snapshots, conformance metadata, matrix snapshot,
  CLI contract tests, Python bindings, WASM bindings, and incremental execution
  now agree on next-historical-bar-open market entry fills and same-calculation
  absolute exit attachment to pending entries.
- 2026-06-04 follow-up: `docs/STRATEGY_INTERNAL_ACTIVE_ENTRY_EXIT_ATTACHMENT_PLAN.md`
  closed an additional evidence slice for a supported long limit active entry
  with attached absolute stop exit. The follow-up added CLI, Python, WASM, and
  conformance coverage without changing the public output schema or widening
  unmatched future binding.
- Historical next-stage note: Stage 3 small independent strategy utilities were
  the next candidate at Stage 2 close. Later strategy stages have since added
  `strategy.close_all()` and win/loss/even trade count variables, so use current
  conformance and gap-audit status instead of this historical note when choosing
  new work.
