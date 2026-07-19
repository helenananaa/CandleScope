# Phase U Strategy Exit Partial Quantity Execution Plan

Status: closed; Phase U audit and release verification are complete.

Phase U should widen only the current `strategy.exit` quantity surface. It must
not become a broader broker-simulation phase. The target is a deterministic,
fixture-backed partial-exit subset for the existing long-only, no-pyramiding,
one-pending-exit broker, while preserving the current public strategy output
shape and runtime `schemaVersion: 3`.

Every slice should leave the workspace shippable and should keep semantic
claims, broker behavior, public output contracts, fixtures, snapshots, host
bindings, conformance metadata, docs, and release verification in lockstep.

## Current Starting Point

The repository has closed the current strategy progression through Phase S and
has also closed Phase T for WASM request-provider parity. The relevant strategy
baseline is:

- `tests/fixtures/conformance.tsv` marks `strategy`, `strategy.entry`,
  `strategy.close`, strategy equity, strategy state variables,
  `strategy.closedtrades`, `strategy.opentrades`, and `strategy.exit` as
  `partial`.
- Broad `strategy.*` remains `unsupported`.
- `strategy(...)` supports the fixture-backed declaration subset, including
  positive const numeric `initial_capital` and fixed default quantity settings
  through `default_qty_type=strategy.fixed` plus positive const numeric
  `default_qty_value`.
- `strategy.entry(id, strategy.long, qty=...)` opens one long market position
  at the current bar close, with no pyramiding and no short exposure.
- `strategy.close(id)` closes the full matching long position at the current
  bar close and cancels any matching pending exit.
- Strategy state variables are available in strategy-mode historical scripts:
  `strategy.position_size`, `strategy.position_avg_price`,
  `strategy.openprofit`, `strategy.netprofit`, `strategy.equity`,
  `strategy.closedtrades`, and `strategy.opentrades`.
- Single-trigger `strategy.exit` supports `stop`, `limit`, `profit`, and
  `loss` forms for one broker-owned pending full-position exit on the current
  one-net-long entry.
- Bracket `strategy.exit` supports exactly one downside plus one upside leg:
  `stop + limit`, `stop + profit`, `loss + limit`, and `loss + profit`.
- Trailing `strategy.exit` supports exactly `trail_price + trail_offset` and
  `trail_points + trail_offset`.
- Same-side bracket pairs `stop + loss` and `limit + profit`, 3+ trigger
  calls, invalid trailing combinations, partial quantities, missing-entry
  pre-placement, multiple pending exits, pyramiding, short exposure, and
  reversals remain unsupported.
- Runtime output remains `schemaVersion: 3`. `StrategyResult`,
  `StrategyOrderEvent`, `StrategyTrade`, `StrategyPositionSnapshot`, and
  `StrategyEquitySnapshot` shapes are unchanged.
- `StrategyOrderEvent` and `StrategyTrade` already contain `qty` fields, so a
  narrow partial-exit subset can remain explainable through the existing public
  output shape.
- The broker stores one current position with `position_size`, `avg_price`,
  `entry_id`, `entry_bar_index`, and `entry_time`.
- The broker stores a single `pending_exit: Option<PendingExit>` in
  `crates/pine-runtime/src/strategy/broker/exits.rs`.
- `PendingExitTrigger` is currently `Stop(f64)`, `Limit(f64)`,
  `Bracket { downside: f64, upside: f64 }`, or `Trailing(PendingTrailingExit)`.
- `place_exit` validates finite prices, requires a matching current long entry,
  deduplicates identical repeated calls, and otherwise replaces pending state
  with `last_update_bar_index = bar_index`.
- `evaluate_pending_exits` skips the creation or replacement bar via
  `last_update_bar_index >= bar_index`, cancels pending exits when the position
  is flat or `from_entry` no longer matches, and fills stop/limit, bracket, or
  trailing exits on later historical bars.
- `fill_pending_exit` currently closes the entire current position and records
  one `strategy.exit` order event plus one closed trade.
- `crates/pine-sema/src/analyzer/strategy.rs::strategy_exit_arg_family` treats
  `qty` and `qty_percent` as unsupported options.
- Runtime `eval_strategy_exit` in `crates/pine-runtime/src/builtins/strategy.rs`
  does not extract or dispatch `qty` or `qty_percent` arguments.

The current broker module layout is:

```text
crates/pine-runtime/src/strategy/
   mod.rs
   broker/
      mod.rs                 pending evaluation + result projection
      exits.rs               pending-exit identity + placement helpers
      fills.rs               fill trade construction + position reset
      accounting.rs          equity/position/profit/count accessors
      tests.rs               broker unit tests
```

The strategy-focused verification baseline is:

```text
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-runtime --test profile_fixtures
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
python3 -m pytest python/tests
```

The release closeout gate remains:

```text
git diff --check
scripts/verify.sh
```

## Phase U Goal

Design and implement the first deterministic partial-quantity subset for
`strategy.exit` without changing the public strategy output schema.

The default target is:

- Support `qty=quantity` on every currently supported `strategy.exit` trigger
  shape:
  - single-trigger `stop`, `limit`, `profit`, and `loss`;
  - bracket `stop + limit`, `stop + profit`, `loss + limit`, and
    `loss + profit`;
  - trailing `trail_price + trail_offset` and `trail_points + trail_offset`.
- `qty` evaluates at placement time.
- `qty` must evaluate to a finite positive number.
- A requested exit quantity greater than or equal to the current open position
  size closes the full position, preserving the current Phase M/N/R/S behavior.
- A requested exit quantity smaller than the current open position size closes
  only that quantity on trigger, leaves the remaining long position open at the
  same average price, and clears the filled pending exit.
- The existing one-pending-exit model remains. A new exit placement replaces
  the previous pending exit; there is no multi-exit reservation ledger.
- `qty_percent` remains unsupported until Slice 7 unless the Slice 0 design
  gate explicitly confirms its support rules. The recommended implementation
  order is `qty` first, then `qty_percent` as an optional follow-up slice.
- Public runtime JSON, Python dictionaries, and WASM JSON keep the existing
  strategy result shape and runtime `schemaVersion: 3`.

Phase U is successful when supported partial `qty` exits analyze, execute,
round-trip through CLI/Python/WASM, are fixture- and snapshot-covered including
incremental parity, are marked appropriately in `tests/fixtures/conformance.tsv`,
are documented, and pass the full release verification gate, while every
still-unsupported quantity or broker-lifecycle form remains diagnostic-only
unsupported.

## Non-Goals

Do not include these in the Phase U compatibility claim:

- Multiple simultaneous entries, pyramiding, short exposure, reversals, or
  separate long/short accounting.
- Multiple independent pending exits.
- Quantity reservation across multiple exits.
- Public pending-order records, remaining-quantity fields, partial-fill fields,
  exit-reason fields, or a runtime schema bump.
- Missing-entry pre-placement of pending exits.
- `strategy.order`, order modification APIs, `oca_name`, OCA reduce/cancel
  groups, `comment`, `alert_message`, or strategy alert delivery.
- Commission, slippage, margin, currency conversion, percent-of-equity sizing,
  cash sizing, contracts sizing, or custom tick-size host metadata.
- Realtime strategy execution, forming-bar broker rollback, or intrabar path
  reconstruction.
- Same-side bracket pairs, 3+ trigger calls, invalid trailing combinations, or
  any trigger form that is unsupported before Phase U.
- Broad TradingView broker-emulator equivalence beyond the explicit historical
  OHLC rules documented here.

## Phase U Default Design Decisions

Slice 0 must confirm these decisions before behavior changes land. If any
decision changes, update this section first and keep fixtures, docs, matrix
metadata, and implementation aligned with the revised rule.

- Phase U is long-only and uses the current one-net-long broker.
- Phase U keeps one broker-owned pending exit slot.
- The first supported partial quantity argument is `qty`.
- `qty` is accepted only on trigger shapes already supported before Phase U.
- `qty` is evaluated at placement time, after `id` and `from_entry` and before
  the pending exit is stored.
- `qty` is stored on the pending exit record as the requested close quantity.
- If `qty` is omitted, pending exits retain the current full-position behavior.
- If `qty` is finite and positive, the pending exit is accepted.
- If `qty` is non-finite, `na`, zero, or negative, placement is rejected with a
  stable runtime diagnostic and any existing pending exit remains unchanged.
- On fill, the actual closed quantity is `min(requested_qty, position_size)`.
- If actual closed quantity is equal to the current position size, the fill
  closes the position, clears entry identity, records a flat position snapshot,
  and keeps current full-exit behavior.
- If actual closed quantity is smaller than the current position size, the fill
  reduces `position_size`, keeps `avg_price`, `entry_id`, `entry_bar_index`,
  and `entry_time`, records a position snapshot with the remaining size and
  unchanged average price, and clears the filled pending exit.
- Partial exits realize profit only for the closed quantity:
  `(exit_price - entry_price) * closed_qty`.
- Cash increases by `closed_qty * exit_price`.
- `strategy.closedtrades` increases by one for each filled partial exit because
  the public `StrategyTrade` list records one closed trade per fill event.
- `strategy.opentrades` remains `1` after a partial exit if any long position
  remains open, and becomes `0` only when the final remaining quantity is
  closed.
- `strategy.position_size`, `strategy.openprofit`, `strategy.netprofit`, and
  `strategy.equity` continue to read from live broker state.
- Script reads see pending-exit fills on the next bar, matching existing
  pending-exit timing. Public output and equity snapshots include the fill on
  the fill bar.
- Repeating an identical pending exit preserves the original eligibility bar.
  Quantity participates in identity: changing `qty`, including adding or
  removing `qty`, replaces the pending exit and resets eligibility.
- Replacing a partial pending exit with a full pending exit, or a full pending
  exit with a partial pending exit, follows the same replacement rule.
- A supported `qty_percent` follow-up, if selected, converts to an absolute
  quantity at placement time using the current open position size. It does not
  reserve future quantities or track percentages dynamically after placement.
- Until `qty_percent` is implemented, it stays diagnostic-only unsupported with
  a stable semantic diagnostic.

## Rules for Every Slice

- Add fixtures before or alongside behavior changes.
- Keep the compatibility matrix conservative. Only widen the `strategy.exit`
  row when semantic fixtures, runtime fixtures, host coverage, conformance
  metadata, docs, and verification evidence all exist for the exact partial
  quantity subset.
- Preserve indicator behavior. Indicator scripts must not gain broker state or
  strategy output.
- Keep strategy order calls rejected in UDFs and requested-context expressions
  under the existing side-effect policy.
- Keep unsupported quantity arguments diagnostic-only until the same slice both
  accepts the selected semantic forms and routes them into broker placement.
- Treat the broker as deterministic runtime state. Core crates must not depend
  on account services, wall-clock time, host callbacks, filesystem, or network.
- Do not add public pending-order, reservation, or remaining-quantity fields in
  Phase U.
- Do not change runtime `schemaVersion: 3` unless a later schema review opens a
  separate public contract phase.
- Keep CLI, Python, and WASM behavior synchronized. A partial-exit script that
  runs in one host should expose the same public strategy result shape in every
  host.
- Keep snapshots authoritative for public output shapes.
- Keep existing full-position exit fixtures passing unchanged.
- If a slice discovers that partial quantities require a broader broker model,
  stop the behavior slice and record a design-only audit instead of silently
  widening scope.

## Internal Structure Rules

- Keep `BrokerState` as the public strategy runtime facade exported by
  `pine-runtime`.
- Keep pending-exit identity and placement helpers in
  `crates/pine-runtime/src/strategy/broker/exits.rs`.
- Keep fill construction and position reduction logic in
  `crates/pine-runtime/src/strategy/broker/fills.rs`.
- Keep equity, position, profit, and trade-count accessors in
  `crates/pine-runtime/src/strategy/broker/accounting.rs`.
- Keep semantic validation in `crates/pine-sema/src/analyzer/strategy.rs`.
- Keep runtime argument extraction and dispatch in
  `crates/pine-runtime/src/builtins/strategy.rs`.
- Add helper structs or enums only when they reduce real duplication across
  stop/limit/profit/loss, bracket, and trailing placement.
- Treat roughly 800 lines in a production Rust file as a review trigger. If a
  file grows due to partial quantity work, split focused helpers instead of
  expanding a multipurpose module.

## Intended Data Model

Use the existing single pending-exit record and add quantity intent to it.
The exact shape can vary, but it should preserve these semantics:

```text
PendingExit {
  id: String,
  from_entry: String,
  trigger: PendingExitTrigger,
  quantity: PendingExitQuantity,
  last_update_bar_index: usize,
}

PendingExitQuantity:
  Full
  Fixed(f64)
```

Rules:

- `Full` is the default when `qty` is omitted.
- `Fixed(qty)` stores the absolute requested close quantity evaluated at
  placement time.
- `Fixed(qty)` values must be finite and positive before a pending exit is
  stored.
- Quantity participates in placement equivalence. Two pending exits with the
  same trigger but different quantity are different placements.
- Fill code owns clamping `Fixed(qty)` to the current `position_size`.
- Fill code owns deciding whether the position becomes flat or remains open.

## Slice 0: Baseline Lock And Quantity Design Gate

Goal: confirm that Phase U is a narrow partial-exit phase, not a broker
reservation or multiple-pending-exit phase.

Steps:

1. Read the strategy sections in `docs/CONFORMANCE.md`,
   `docs/LONG_TERM_EXECUTION_PLAN.md`, `docs/PHASE_S_AUDIT.md`, and
   `tests/fixtures/conformance.tsv`.
2. Confirm `strategy.exit` currently accepts the Phase M/N/R/S trigger shapes
   and still rejects `qty` and `qty_percent` through semantic diagnostics.
3. Confirm public strategy output already has `qty` fields on order and trade
   records, so no runtime schema bump is required for the first `qty` subset.
4. Confirm the selected `qty` rules:
   - placement-time evaluation;
   - finite positive values only;
   - clamp to current position size on fill;
   - reduce remaining long position when partial;
   - no reservation ledger;
   - no multiple pending exits.
5. Decide whether `qty_percent` stays deferred for the whole phase or becomes a
   late optional slice. The recommended default is to defer it until `qty`
   closeout evidence is stable.
6. Add or update design notes in this document before behavior changes if any
   decision differs from the defaults above.

Suggested commands:

```text
cargo test -p pine-sema strategy_exit
cargo test -p pine-runtime strategy_exit
cargo test -p pine-cli strategy
```

Exit criteria:

- Existing Phase S strategy behavior is green.
- `qty` and `qty_percent` baseline unsupported behavior is understood.
- The exact first supported `qty` subset is recorded.
- No compatibility claim is widened.

Slice 0 decision record, 2026-05-31:

- Current strategy support remains the Phase M/N/R/S subset recorded in
  `tests/fixtures/conformance.tsv`: single-trigger, one-downside/one-upside
  bracket, and trailing `strategy.exit` forms are partial; partial quantity and
  missing-entry forms remain unsupported.
- Phase U will open only fixed `qty` first. `qty_percent` is deferred unless a
  later explicit slice records full semantic, runtime, fixture, host, conformance,
  and docs evidence for it.
- The first positive `qty` subset remains placement-time evaluation, finite
  positive validation, fill-time clamping to current position size, no
  reservation ledger, and no multiple pending exits.
- Analyzer support and runtime dispatch for user-script
  `strategy.exit(..., qty=...)` must open in the same slice. Earlier broker
  internals may support fixed quantities only while the analyzer still rejects
  user-visible `qty` calls.
- Existing public strategy result fields already contain order and trade
  quantities, so Phase U does not require public runtime schema changes.
- Compatibility metadata is not widened in Slice 0.

## Slice 1: Diagnostic Guardrails For Quantity Arguments

Goal: lock the unsupported quantity boundary and diagnostic priority before any
user-visible `qty` support is enabled.

Steps:

1. Update `StrategyExitArgFamily` in
   `crates/pine-sema/src/analyzer/strategy.rs` only if it helps report clearer
   quantity diagnostics. Do not make any `qty` call analyze successfully in this
   slice.
2. Keep `qty` and `qty_percent` diagnostic-only unsupported for every trigger
   shape.
3. Record the intended diagnostic priority for calls that combine quantity
   arguments with unsupported trigger shapes:
   - same-side pairs `stop + loss` and `limit + profit`;
   - 3+ trigger calls;
   - invalid trailing combinations;
   - calls without any trigger.
4. Add or keep negative semantic fixtures for:
   - `qty` on an otherwise-supported single-trigger exit;
   - `qty_percent` if deferred;
   - `qty` with unsupported same-side or 3+ trigger calls;
   - `qty` in indicator scripts;
   - `qty` in requested-context or UDF side-effect contexts if existing broad
     fixtures do not already cover it.
5. If any analyzer refactor is made, keep runtime unreachable for `qty` through
   normal compiled scripts until Slice 4.

Candidate fixture names:

```text
tests/fixtures/sema/unsupported_strategy_exit_qty_stop.pine
tests/fixtures/sema/unsupported_strategy_exit_qty_percent.pine
tests/fixtures/sema/unsupported_strategy_exit_qty_same_side.pine
```

Exit criteria:

- Analyzer still rejects `qty` and `qty_percent`.
- Unsupported trigger-family diagnostics remain stable and documented.
- No runtime behavior or compatibility claim is widened.

Slice 1 decision record, 2026-05-31:

- `qty` and `qty_percent` remain semantic diagnostics for every user-visible
  `strategy.exit` shape.
- Quantity diagnostics are emitted for quantity arguments even when the same
  call also contains an unsupported trigger family. Trigger-family diagnostics
  may be emitted alongside quantity diagnostics; this keeps both boundaries
  visible without allowing HIR lowering.
- Negative fixtures now cover `qty` on an otherwise-supported stop exit,
  deferred `qty_percent`, and `qty` combined with a same-side unsupported trigger
  pair.
- Analyzer support and runtime dispatch remain unopened until the atomic support
  slice.

Verification:

```text
cargo test -p pine-sema strategy_exit
cargo test -p pine-builtins strategy
```

## Slice 2: Broker Pending Quantity Model

Goal: add quantity intent to pending exits while preserving full-exit behavior
when quantity is omitted.

Steps:

1. Add a pending-exit quantity representation in
   `crates/pine-runtime/src/strategy/broker/exits.rs`, for example:
   `PendingExitQuantity::Full | PendingExitQuantity::Fixed(f64)`.
2. Add quantity to `PendingExit`.
3. Update placement equivalence so quantity participates in repeated-call
   identity.
4. Add full-quantity defaults to all existing placement helpers.
5. Add parallel placement helpers or a shared lower-level helper for fixed
   `qty`, without duplicating trigger validation logic.
6. Validate fixed quantity before replacing an existing pending exit:
   - finite;
   - positive.
7. Emit a stable runtime diagnostic for invalid exit quantity, for example
   `E_STRATEGY_EXIT_QTY` with message
   `` `strategy.exit` quantity must be finite and positive ``.
8. Ensure invalid quantity leaves any existing pending exit unchanged.
9. Add broker unit tests for:
   - full exit still closes the whole position;
   - fixed partial quantity is stored;
   - repeated same quantity preserves eligibility;
   - changed quantity replaces pending exit;
   - invalid quantity keeps existing pending exit unchanged.

Exit criteria:

- Existing full-position broker tests pass unchanged.
- Pending exit identity includes quantity.
- Invalid quantity has a stable runtime diagnostic.
- Analyzer still rejects user-script `strategy.exit(..., qty=...)` forms, so the
  new broker quantity path is not yet a public compatibility claim.
- No public output fields change.

Slice 2 decision record, 2026-05-31:

- `PendingExit` now carries `PendingExitQuantity::Full` or
  `PendingExitQuantity::Fixed(f64)`.
- Existing placement helpers continue to create `Full` pending exits, preserving
  the current full-position behavior for all public runtime paths.
- Internal fixed-quantity placement helpers exist for every currently supported
  trigger family, but analyzer guardrails still keep user-script `qty` calls
  diagnostic-only until the atomic support slice.
- Quantity participates in pending-exit placement identity. Repeating the same
  quantity preserves eligibility; changing quantity replaces the pending exit.
- Invalid fixed quantities produce `E_STRATEGY_EXIT_QTY` and leave existing
  pending state unchanged.

Verification:

```text
cargo test -p pine-runtime strategy::broker
cargo test -p pine-runtime strategy_exit
```

## Slice 3: Partial Fill Accounting

Goal: make pending-exit fills close only the actual selected quantity and leave
the remaining long position open when appropriate.

Steps:

1. Update `fill_pending_exit` in
   `crates/pine-runtime/src/strategy/broker/fills.rs` so it computes
   `closed_qty` from the pending quantity:
   - full exits close `position_size`;
   - fixed exits close `min(requested_qty, position_size)`.
2. Keep a defensive runtime diagnostic or no-op guard for impossible
   non-positive `closed_qty`, even though placement validation should prevent
   it.
3. Record `closed_qty` in `StrategyOrderEvent.qty` and `StrategyTrade.qty`.
4. Realize profit only for `closed_qty`.
5. Increase cash by `closed_qty * exit_price`.
6. If `closed_qty >= position_size`, preserve the current flat reset behavior:
   - clear `entry_id`, `entry_bar_index`, and `entry_time`;
   - set `position_size` and `avg_price` to zero;
   - clear `pending_exit`;
   - emit a flat position snapshot.
7. If `closed_qty < position_size`, reduce `position_size` and preserve:
   - `avg_price`;
   - `entry_id`;
   - `entry_bar_index`;
   - `entry_time`.
8. Emit a position snapshot with remaining size and unchanged average price for
   partial fills.
9. Clear the filled pending exit after any fill, including partial fills.
10. Ensure equity snapshots after a partial fill use updated cash plus remaining
    market value.
11. Add broker unit tests for:
    - stop partial fill;
    - limit partial fill;
    - requested quantity larger than position closes full position;
    - partial fill keeps open trade count at `1`;
    - final later exit brings open trade count to `0`;
    - realized and open profit are split correctly after a partial fill.

Exit criteria:

- Full exits still produce identical output to the existing snapshots.
- Partial exits record one order and one trade with partial quantity.
- Remaining position state and equity are deterministic.
- Analyzer still rejects user-script `strategy.exit(..., qty=...)` forms until
  Slice 4 opens the semantic and runtime path together.

Slice 3 decision record, 2026-05-31:

- Pending full exits keep the existing full-position reset behavior.
- Pending fixed-quantity exits close `min(requested_qty, position_size)`.
- Partial fills record the closed quantity in the existing order and trade
  `qty` fields, realize profit only for that quantity, reduce live
  `position_size`, preserve `avg_price` and entry identity, emit a remaining
  position snapshot, and clear the filled pending exit.
- Fixed quantities greater than the current position size clamp to a full close.
- Broker accounting accessors now split realized and open profit after partial
  fills while keeping open trade count at `1` until the final remaining position
  closes.

Verification:

```text
cargo test -p pine-runtime strategy::broker
cargo test -p pine-runtime strategy
```

## Slice 4: Atomic Semantic And Runtime Support For `qty`

Goal: open the selected `strategy.exit(..., qty=...)` surface in one atomic
slice so accepted scripts cannot fall through to full-position runtime behavior.

Steps:

1. Update `StrategyExitArgFamily` in
   `crates/pine-sema/src/analyzer/strategy.rs` so `qty` has its own supported
   quantity family rather than being grouped with `qty_percent`, `oca_name`,
   `comment`, and `alert_message`.
2. Permit `qty` only on trigger shapes already supported before Phase U:
   - single-trigger `stop`, `limit`, `profit`, and `loss`;
   - bracket `stop + limit`, `stop + profit`, `loss + limit`, and
     `loss + profit`;
   - trailing `trail_price + trail_offset` and `trail_points + trail_offset`.
3. Keep `qty_percent` unsupported unless Slice 0 explicitly selected it for
   this phase.
4. Keep `qty` rejected for unsupported trigger shapes:
   - same-side pairs `stop + loss` and `limit + profit`;
   - 3+ trigger calls;
   - invalid trailing combinations;
   - calls without any trigger.
5. Validate only semantic shape in the analyzer. Do not require `qty` to be
   const; runtime should evaluate supported numeric expressions at placement
   time.
6. Extract `qty` in `eval_strategy_exit` in
   `crates/pine-runtime/src/builtins/strategy.rs`.
7. Evaluate `qty` once at placement time, after `id` and `from_entry`.
8. Convert `qty` to the pending-exit quantity representation:
   - omitted means full;
   - present means fixed quantity using `as_f64().unwrap_or(f64::NAN)`.
9. Route single-trigger stop, limit, profit, and loss exits with quantity.
10. Route bracket exits with quantity.
11. Route trailing exits with quantity.
12. Ensure unsupported trigger shapes with `qty` do not silently place a partial
   single-trigger exit.
13. Preserve existing runtime diagnostics for invalid trigger prices, invalid
   profit/loss ticks, invalid trailing offsets, flat state, and mismatched
   `from_entry`.
14. Add positive semantic fixtures for:
   - single-trigger stop with `qty`;
   - bracket with `qty`;
   - trailing with `qty`.
15. Add targeted runtime unit tests if dispatch behavior is not fully covered by
   fixture tests in Slice 5.

Candidate positive semantic fixture names:

```text
tests/fixtures/sema/supported_strategy_exit_qty_stop.pine
tests/fixtures/sema/supported_strategy_exit_qty_bracket.pine
tests/fixtures/sema/supported_strategy_exit_qty_trailing.pine
```

Exit criteria:

- Analyzer and runtime accept the same selected `qty` forms in the same slice.
- Runtime full-exit behavior remains unchanged when `qty` is omitted.
- Invalid `qty` does not replace an existing pending exit.
- `qty_percent` remains diagnostic-only unsupported if deferred.

Verification:

```text
cargo test -p pine-runtime strategy_exit
cargo test -p pine-sema strategy_exit
```

Slice 4 decision record, 2026-05-31:

- `strategy.exit(..., qty=...)` is now a supported semantic shape only for the
  trigger families already supported before Phase U: single stop, limit,
  profit, and loss exits; one-downside/one-upside brackets; and trailing
  `trail_price + trail_offset` or `trail_points + trail_offset`.
- `qty` is accepted by the builtin signature and semantic shape validator, but
  it is not const-validated in the analyzer. Runtime evaluates it exactly once
  at placement time after `id` and `from_entry`.
- Runtime dispatch routes `qty` through fixed-quantity broker placement helpers
  for every supported single, bracket, and trailing exit shape. Omitting `qty`
  keeps the existing full-position placement helpers.
- Invalid runtime quantities use `E_STRATEGY_EXIT_QTY` and preserve any
  existing pending exit. Existing price, tick-distance, trailing, flat-state,
  and mismatched-entry diagnostics remain broker-owned.
- `qty_percent` remains semantic-diagnostic-only unsupported. Calls that use
  `qty` with unsupported trigger families, invalid trailing combinations, or no
  trigger still fail semantic shape validation instead of reaching runtime.
- Positive semantic fixtures now cover stop, bracket, and trailing exits with
  `qty`. Targeted runtime unit tests cover all supported single-trigger and
  bracket quantity dispatch paths, trailing quantity dispatch, and invalid
  quantity preservation.

Verification:

```text
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy_exit
cargo test -p pine-runtime strategy_exit
```

## Slice 5: Runtime Fixtures, Golden Snapshots, And Incremental Parity

Goal: cover the public behavior of partial `qty` exits through the same fixture
pipeline used by the rest of the strategy subset.

Steps:

1. Add runtime fixtures for the minimal positive surface:
   - single-trigger partial stop fill;
   - single-trigger partial limit fill;
   - bracket partial fill;
   - trailing partial fill;
   - quantity greater than position closes full position;
   - repeated identical partial exit preserves eligibility;
   - changed quantity replaces pending exit;
   - partial fill followed by final close or final exit;
   - strategy state variables after partial fill.
2. Reuse existing strategy OHLC fixtures when possible. Add a new CSV only if
   current bars cannot express the selected fill timing clearly.
3. Generate golden snapshots for each new runtime fixture.
4. Add incremental append coverage so each new runtime fixture matches full
   historical execution.
5. Add profile fixture coverage only if partial exits change profile-relevant
   storage growth.
6. Confirm snapshots show:
   - partial order quantity;
   - partial trade quantity and profit;
   - remaining position snapshot;
   - correct equity snapshots;
   - unchanged top-level runtime keys.

Candidate fixture names:

```text
tests/fixtures/runtime/strategy_exit_qty_stop_partial.pine
tests/fixtures/runtime/strategy_exit_qty_limit_partial.pine
tests/fixtures/runtime/strategy_exit_qty_bracket_partial.pine
tests/fixtures/runtime/strategy_exit_qty_trailing_partial.pine
tests/fixtures/runtime/strategy_exit_qty_full_clamp.pine
tests/fixtures/runtime/strategy_exit_qty_repeated.pine
tests/fixtures/runtime/strategy_exit_qty_replacement.pine
tests/fixtures/runtime/strategy_exit_qty_state.pine
```

Snapshot refresh command, only when intentional:

```text
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
```

Exit criteria:

- Runtime snapshots cover every supported partial quantity trigger family.
- Incremental append execution matches full historical execution.
- Existing full-exit snapshots remain stable unless an intentional bug fix is
  documented.

Verification:

```text
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
```

Slice 5 decision record, 2026-05-31:

- Runtime fixtures now cover partial `qty` stop, limit, bracket, and trailing
  fills through the public fixture/snapshot pipeline.
- Additional runtime fixtures cover over-sized `qty` clamping to a full close,
  repeated identical quantity preserving pending-exit eligibility, changed
  quantity replacing the pending exit, and strategy state variables after a
  partial fill followed by a final close.
- The new golden snapshots show partial order and trade quantities, remaining
  position snapshots with unchanged average price, equity after realized and
  open profit split, and unchanged top-level runtime keys with
  `schemaVersion: 3`.
- Incremental append parity covers the new fixtures. The partial trailing
  fixture reuses the existing trailing OHLC CSV so activation, ratchet, and
  later fill timing remain aligned with the established trailing tests.
- No profile-specific fixture was added because Slice 5 did not introduce a
  new profile storage contract beyond the existing strategy state and output
  vectors.

Verification:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
```

## Slice 6: CLI, Python, And WASM Host Parity

Goal: prove partial-exit results are host-neutral and require no binding-level
broker logic.

Steps:

1. Add or extend a CLI strategy host test that runs one representative partial
   quantity fixture and checks:
   - order event quantity;
   - trade quantity;
   - remaining or final position state;
   - unchanged public strategy keys.
2. Add Python binding tests in `python/tests/test_bindings.py` for the same
   representative fixture as a native dictionary.
3. Rebuild and reinstall the Python wheel before running Python tests when
   `crates/pine-python` or linked Rust crates changed:

   ```text
   maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
   python3 -m pip install --force-reinstall dist/*.whl
   python3 -m pytest python/tests
   ```

4. Add WASM host tests in `crates/pine-wasm/src/tests/mod.rs` for the same
   representative fixture.
5. Confirm all hosts use the shared public runtime result contract and do not
   add host-specific fields.

Exit criteria:

- CLI, Python, and WASM expose the same strategy output semantics for partial
  quantity exits.
- No binding owns strategy accounting logic.
- Runtime output remains `schemaVersion: 3`.

Verification:

```text
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/*.whl
python3 -m pytest python/tests
```

Slice 6 decision record, 2026-05-31:

- CLI, Python, and WASM host tests now use the same representative partial
  quantity fixture, `strategy_exit_qty_stop_partial.pine`.
- Host assertions check the existing public strategy contract only: partial
  `strategy.exit` order quantity, partial trade quantity and profit, remaining
  position snapshot with unchanged average price, no pending-order or
  remaining-quantity fields, and runtime `schemaVersion: 3`.
- No host binding owns broker accounting logic. The Python and WASM tests
  exercise the shared runtime result contract exposed through their existing
  serialization layers.

Verification:

```text
cargo fmt --check
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/*.whl
python3 -m pytest python/tests
```

## Slice 7: Optional `qty_percent` Follow-Up

Goal: decide whether to support `qty_percent` in Phase U after `qty` is stable.
This slice may be explicitly deferred in the Phase U audit.

Default recommendation: defer `qty_percent` unless the `qty` subset closes
cleanly and the conversion rule remains small.

If implemented, use these rules:

1. Accept `qty_percent=percent` only on trigger shapes already supported with
   `qty`.
2. Reject calls that specify both `qty` and `qty_percent` with a stable
   semantic diagnostic. Do not choose precedence silently.
3. Evaluate `qty_percent` at placement time.
4. Require a finite positive percentage.
5. Convert to absolute quantity at placement time:
   `position_size * percent / 100.0`.
6. Use the same fixed pending quantity and fill behavior as `qty` after
   conversion.
7. Clamp to current position size on fill.
8. Do not reserve quantities across multiple exits.
9. Add semantic fixtures, runtime fixtures, snapshots, incremental parity, host
   tests, conformance metadata, and docs if support is claimed.

If deferred, keep these explicit negative fixtures or equivalent coverage:

```text
tests/fixtures/sema/unsupported_strategy_exit_qty_percent.pine
tests/fixtures/sema/unsupported_strategy_exit_qty_and_qty_percent.pine
```

Exit criteria if implemented:

- `qty_percent` has the same evidence level as `qty`.
- The public strategy result shape is unchanged.
- No reservation or multiple pending-exit behavior is implied.

Verification if implemented:

```text
cargo test -p pine-sema strategy_exit
cargo test -p pine-runtime strategy_exit
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
python3 -m pytest python/tests
```

Slice 7 decision record, 2026-05-31:

- `qty_percent` is explicitly deferred from Phase U behavior. Supporting it
  would require a separate conformance claim and the same semantic, runtime,
  snapshot, incremental, and host evidence level as fixed `qty`.
- `qty_percent` remains semantic-diagnostic-only unsupported, including calls
  that also specify supported fixed `qty`. No precedence rule is introduced.
- Negative semantic fixtures now cover both `qty_percent` alone and the
  combined `qty + qty_percent` form.

Verification:

```text
cargo test -p pine-sema strategy_exit
cargo test -p pine-runtime strategy_exit
```

## Slice 8: Conformance, Matrix, And Documentation Sync

Goal: update compatibility claims only after behavior and host evidence exists.

Steps:

1. Update `tests/fixtures/conformance.tsv` so the `strategy.exit` row mentions
   the supported partial `qty` subset.
2. Keep broad `strategy.*` unsupported and list remaining quantity boundaries:
   - `qty_percent` if deferred;
   - multiple pending exits;
   - reservation behavior;
   - missing-entry pre-placement;
   - pyramiding, short exposure, and reversals.
3. Refresh `tests/snapshots/matrix.json` only through the matrix snapshot test:

   ```text
   UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
   ```

4. Update docs that describe strategy behavior:
   - `docs/CONFORMANCE.md`;
   - `docs/LONG_TERM_EXECUTION_PLAN.md`;
   - `docs/SEMANTIC_MODEL.md` if semantic boundaries changed;
   - `docs/BUILTIN_SIGNATURES.md` if signature notes changed;
   - `docs/RELEASE_NOTES.md`.
5. Keep docs explicit that Phase U does not add public pending-order fields or
   a runtime schema bump.
6. Run focused matrix and strategy tests.

Exit criteria:

- Conformance metadata, matrix snapshot, docs, and implementation agree.
- Unsupported quantity and broker tails remain explicitly documented.
- No public output schema drift occurs.

Verification:

```text
cargo test -p pine-cli matrix
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
git diff --check
```

Slice 8 decision record, 2026-05-31:

- `tests/fixtures/conformance.tsv` now claims the fixed `qty` subset only after
  semantic, runtime, snapshot, incremental, and CLI/Python/WASM host evidence
  exists.
- The `strategy.exit` conformance row includes the fixed `qty` runtime and
  semantic fixtures, documents placement-time finite positive quantity
  semantics, and keeps `qty_percent`, multiple pending exits, reservation
  behavior, missing-entry pre-placement, unsupported trigger shapes, pyramiding,
  shorts, and reversals out of scope.
- The broad `strategy.*` unsupported row no longer lists now-supported fixed
  `qty` forms as unsupported, but continues to list the remaining broker and
  quantity tails.
- `tests/snapshots/matrix.json` was refreshed through the matrix snapshot test.
- `docs/CONFORMANCE.md`, `docs/LONG_TERM_EXECUTION_PLAN.md`,
  `docs/SEMANTIC_MODEL.md`, `docs/BUILTIN_SIGNATURES.md`, and
  `docs/RELEASE_NOTES.md` now describe the supported fixed `qty` subset and
  the remaining unsupported tails without changing runtime `schemaVersion: 3`.

Verification:

```text
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli matrix
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
git diff --check
```

## Slice 9: Phase U Audit And Closeout

Goal: close Phase U with evidence and keep future broker work scoped.

Steps:

1. Add `docs/PHASE_U_AUDIT.md` after implementation is complete.
2. Record completed slices and the exact supported quantity forms.
3. Record final quantity semantics:
   - placement-time evaluation;
   - finite positive validation;
   - full clamp behavior;
   - remaining-position accounting;
   - trade-count and open-trade behavior;
   - `qty_percent` decision.
4. Record positive semantic, runtime, incremental, CLI, Python, and WASM
   evidence.
5. Record unchanged public runtime schema and unchanged one-pending-exit model.
6. Record remaining broker maintenance tails:
   - `qty_percent` if deferred;
   - quantity reservation behavior;
   - multiple pending exits;
   - missing-entry pre-placement;
   - pyramiding, short exposure, and reversals;
   - `strategy.order` and richer order modification;
   - commission, slippage, margin, and broader sizing modes;
   - strategy alerts and realtime broker rollback.
7. Run focused verification and the full release gate.
8. Update `docs/LONG_TERM_EXECUTION_PLAN.md` only if strategy roadmap wording
   needs to reflect that partial `qty` exits are no longer a broker tail.

Exit criteria:

- `docs/PHASE_U_AUDIT.md` records closure evidence.
- Every supported `qty` trigger family is tested.
- CLI/Python/WASM strategy host surfaces are synchronized.
- Runtime output remains `schemaVersion: 3`.
- The full release gate passes.

Verification:

```text
cargo fmt --check
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-runtime --test profile_fixtures
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/*.whl
python3 -m pytest python/tests
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
cargo test -p pine-cli matrix_output_matches_golden_snapshot
git diff --check
scripts/verify.sh
```

Slice 9 decision record, 2026-05-31:

- `docs/PHASE_U_AUDIT.md` records the closed fixed `qty` subset, evidence, host
  parity, unchanged public output schema, and remaining broker tails.
- Phase U is closed for fixed absolute `qty` on the already supported
  single-trigger, one-downside/one-upside bracket, and trailing exit families.
- `qty_percent`, reservation behavior, multiple pending exits,
  missing-entry pre-placement, pyramiding, shorts, reversals, richer order
  APIs, broker costs, alerts, and realtime rollback remain separate future
  work.
- Runtime output remains `schemaVersion: 3`.
- The final closeout gate is `scripts/verify.sh`.

## Recommended Execution Order

Use this order unless a discovered blocker requires reordering:

1. Baseline lock and quantity design gate.
2. Diagnostic guardrails for quantity arguments while `qty` remains unsupported.
3. Broker pending quantity model.
4. Partial fill accounting.
5. Atomic semantic and runtime support for `qty`.
6. Runtime fixtures, snapshots, and incremental parity.
7. CLI, Python, and WASM host parity.
8. Optional `qty_percent` follow-up or explicit deferral.
9. Conformance, matrix, and documentation sync.
10. Phase U audit and closeout.

## Phase U Closeout Checklist

Complete this checklist before treating Phase U as closed. If an item is
intentionally deferred, record the reason and risk in `docs/PHASE_U_AUDIT.md`.

- [x] Slice 0 confirms Phase U is a partial quantity phase, not a reservation
      or multiple-pending-exit phase.
- [x] `qty` remains diagnostic-only until the same slice opens analyzer support
      and runtime dispatch.
- [x] Slice 1 records quantity diagnostic guardrails without opening analyzer or
      runtime support.
- [x] Slice 2 adds internal pending-exit quantity intent while analyzer support
      remains closed.
- [x] Slice 3 implements partial fill accounting behind the still-closed
      analyzer gate.
- [x] `strategy.exit(..., qty=...)` analyzes for every selected supported
      trigger family.
- [x] `qty_percent` is either implemented with full evidence or remains
      fixture-backed unsupported.
- [x] Unsupported trigger shapes with `qty` remain diagnostic-only.
- [x] Indicator scripts, UDF side effects, and requested-context strategy order
      calls remain rejected.
- [x] Pending exit identity includes quantity.
- [x] Invalid `qty` values produce stable runtime diagnostics and do not
      replace existing pending exits.
- [x] Full exits without `qty` keep existing behavior and snapshots.
- [x] Partial fills record partial order and trade quantities.
- [x] Partial fills reduce remaining long position size and preserve average
      price.
- [x] Quantity larger than the current position closes the full position.
- [x] Strategy state variables behave correctly after partial fills.
- [x] Incremental append execution matches full historical execution for new
      fixtures.
- [x] CLI, Python, and WASM host tests cover one representative partial exit.
- [x] Runtime output remains `schemaVersion: 3`.
- [x] Public strategy result keys and item shapes remain unchanged.
- [x] `tests/fixtures/conformance.tsv` and `tests/snapshots/matrix.json` agree
      with the implemented subset.
- [x] Maintainer docs and release notes describe the supported quantity subset
      and remaining broker tails.
- [x] `docs/PHASE_U_AUDIT.md` records verification evidence and remaining
      strategy tails.
- [x] `scripts/verify.sh` passes.
