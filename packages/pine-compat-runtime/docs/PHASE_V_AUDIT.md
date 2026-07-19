# Phase V Audit: Strategy Exit Percent Quantity

Status: closed for the current fixture-backed `qty_percent` partial-exit
subset.

Phase V added deterministic percent quantity support to the existing long-only,
no-pyramiding, one-pending-exit `strategy.exit` broker. The compatibility claim
remains partial and is tied to `tests/fixtures/conformance.tsv`, semantic
fixtures, runtime fixtures and snapshots, incremental parity, CLI/Python/WASM
host tests, docs, and the closeout release gate.

## Completed Slices

- Slice 0 locked the Phase U fixed-quantity baseline, selected the first
  deterministic `qty_percent` subset, confirmed placement-time percent
  resolution, allowed `qty_percent > 100` with fill-time clamping, and kept the
  public strategy output schema unchanged.
- Slice 1 made `qty_percent` a known `strategy.exit` argument with stable
  diagnostics while keeping the analyzer gate closed.
- Slice 2 added internal percent quantity intent and broker helpers behind the
  still-closed analyzer gate, including finite-positive validation, percent to
  absolute quantity resolution, and invalid-percent preservation of existing
  pending exits.
- Slice 3 opened analyzer and runtime support atomically for
  `strategy.exit(..., qty_percent=...)` on the trigger families already
  supported before Phase V, while leaving `qty + qty_percent` and unsupported
  trigger shapes diagnostic-only.
- Slice 4 added runtime fixtures, golden snapshots, conformance metadata, and
  incremental append coverage for partial stop, limit, bracket, trailing,
  `qty_percent=100`, `qty_percent>100`, repeated, replacement, and state-variable
  behavior.
- Slice 5 added representative CLI, Python, and WASM host parity tests for the
  same percent partial fixture and confirmed public host output shapes remain
  unchanged.
- Slice 6 synchronized conformance docs, execution semantics, release notes,
  roadmap wording, and README wording with the fixture-backed subset.
- Slice 7 added this audit, closed the roadmap status, removed stale semantic
  wording, and ran focused verification plus the full release gate.

## Supported Surface

The source of truth is `tests/fixtures/conformance.tsv`.

- `strategy.exit` remains partial.
- Existing single-trigger exits remain supported:
  - `stop`
  - `limit`
  - `profit`
  - `loss`
- Existing one-downside/one-upside brackets remain supported:
  - `stop + limit`
  - `stop + profit`
  - `loss + limit`
  - `loss + profit`
- Existing trailing exits remain supported:
  - `trail_price + trail_offset`
  - `trail_points + trail_offset`
- Phase V adds optional `qty_percent` to each supported trigger family above.
- `qty_percent` is mutually exclusive with `qty`.
- `qty_percent` is evaluated once at placement time.
- `qty_percent` must evaluate to a finite positive number.
- Omitted `qty` and omitted `qty_percent` keep the previous full-position exit
  behavior.
- `qty_percent` resolves to an absolute requested close quantity at placement
  time as `position_size * qty_percent / 100.0`.
- On fill, percent quantity closes `min(resolved_qty, current position size)`.
- `qty_percent=100` is equivalent to a full-position pending exit for the
  current position at placement time.
- `qty_percent > 100` is allowed, but the fill closes no more than the current
  position.
- A percent quantity smaller than the current position leaves the remaining long
  position open at the same average price and clears the filled pending exit.
- Partial fills emit one existing `strategy.exit` order event and one existing
  closed-trade record using the absolute filled quantity.
- `strategy.closedtrades` increases by one per filled partial exit.
- `strategy.opentrades` remains `1` after a partial fill while any supported
  long position remains open, and becomes `0` only when the final remaining
  position closes.

## Unsupported Boundaries

The following remain intentionally out of the Phase V compatibility claim:

- Calls that combine `qty` and `qty_percent`.
- Quantity reservation across multiple exits.
- Multiple independent pending exits.
- Missing-entry pre-placement.
- Same-side bracket pairs `stop + loss` and `limit + profit`.
- 3+ trigger calls and invalid trailing combinations.
- Multiple entries, pyramiding, short exposure, and reversals.
- `strategy.order`, richer order modification, OCA behavior, comments, alert
  messages, and strategy alert delivery.
- Commission, slippage, margin, currency conversion, percent-of-equity sizing,
  cash sizing, contracts sizing, and custom tick-size host metadata.
- Public pending-order records, percent fields, remaining-quantity fields,
  partial-fill fields, exit-reason fields, or a runtime schema bump.
- Realtime strategy execution, forming-bar broker rollback, and intrabar path
  reconstruction.

## Public Output And Host Behavior

Phase V does not add top-level runtime JSON fields, Python dictionary keys, WASM
JSON fields, public pending-order records, percent fields, remaining-quantity
fields, partial-fill fields, exit-reason fields, or a runtime schema bump.
Runtime output remains `schemaVersion: 3`.

Public strategy output remains:

```text
strategy: {
  orders: [],
  trades: [],
  position: [],
  equity: [],
  diagnostics: []
}
```

CLI and WASM share `public_runtime_result_json`; Python maps the same
`StrategyResult` into native dictionaries. Host tests cover
`tests/fixtures/runtime/strategy_exit_qty_percent_stop_partial.pine` and assert
the percent-resolved absolute exit order/trade quantity, remaining position, plot
values, empty diagnostics, and unchanged public strategy keys.

## Fixture Evidence

Compatibility matrix rows:

- `strategy`: `partial`
- `strategy.entry`: `partial`
- `strategy.close`: `partial`
- `strategy equity`: `partial`
- `strategy.position_size`: `partial`
- `strategy.position_avg_price`: `partial`
- `strategy.openprofit`: `partial`
- `strategy.netprofit`: `partial`
- `strategy.equity`: `partial`
- `strategy.closedtrades`: `partial`
- `strategy.opentrades`: `partial`
- `strategy.exit`: `partial`
- `strategy.*`: `unsupported`

Positive semantic fixtures for `qty_percent`:

- `tests/fixtures/sema/supported_strategy_exit_qty_percent_stop.pine`
- `tests/fixtures/sema/supported_strategy_exit_qty_percent_loss.pine`
- `tests/fixtures/sema/supported_strategy_exit_qty_percent_bracket.pine`
- `tests/fixtures/sema/supported_strategy_exit_qty_percent_trailing.pine`

Unsupported semantic fixtures that remain intentionally negative:

- `tests/fixtures/sema/unsupported_strategy_exit_qty_and_qty_percent.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_qty_percent_same_side.pine`
- Existing unsupported same-side, 3+ trigger, invalid trailing, indicator,
  UDF side-effect, requested-context, and missing-entry fixtures remain
  negative.

Runtime fixtures and snapshots:

- `tests/fixtures/runtime/strategy_exit_qty_percent_stop_partial.pine`
- `tests/fixtures/runtime/strategy_exit_qty_percent_limit_partial.pine`
- `tests/fixtures/runtime/strategy_exit_qty_percent_bracket_partial.pine`
- `tests/fixtures/runtime/strategy_exit_qty_percent_trailing_partial.pine`
- `tests/fixtures/runtime/strategy_exit_qty_percent_full.pine`
- `tests/fixtures/runtime/strategy_exit_qty_percent_full_clamp.pine`
- `tests/fixtures/runtime/strategy_exit_qty_percent_repeated.pine`
- `tests/fixtures/runtime/strategy_exit_qty_percent_replacement.pine`
- `tests/fixtures/runtime/strategy_exit_qty_percent_state.pine`
- `tests/snapshots/runtime_strategy_exit_qty_percent_stop_partial.json`
- `tests/snapshots/runtime_strategy_exit_qty_percent_limit_partial.json`
- `tests/snapshots/runtime_strategy_exit_qty_percent_bracket_partial.json`
- `tests/snapshots/runtime_strategy_exit_qty_percent_trailing_partial.json`
- `tests/snapshots/runtime_strategy_exit_qty_percent_full.json`
- `tests/snapshots/runtime_strategy_exit_qty_percent_full_clamp.json`
- `tests/snapshots/runtime_strategy_exit_qty_percent_repeated.json`
- `tests/snapshots/runtime_strategy_exit_qty_percent_replacement.json`
- `tests/snapshots/runtime_strategy_exit_qty_percent_state.json`

Runtime unit coverage:

- `strategy_exit_qty_percent_single_trigger_forms_dispatch_partial_quantity`
- `strategy_exit_qty_percent_bracket_forms_dispatch_partial_quantity`
- `strategy_exit_qty_percent_trailing_dispatches_partial_quantity`
- `strategy_exit_invalid_qty_percent_preserves_existing_pending_exit`

Host and append evidence:

- `crates/pine-cli/src/main.rs` includes golden runtime snapshots for all percent
  quantity runtime fixtures and a targeted host parity assertion for the partial
  stop fixture.
- `crates/pine-wasm/src/tests/mod.rs` asserts the same partial stop fixture JSON
  contract through the WASM host surface.
- `python/tests/test_bindings.py` asserts the same partial stop fixture contract
  as a native dictionary and checks unchanged top-level and strategy keys.
- `crates/pine-runtime/tests/incremental.rs` runs the percent quantity fixtures
  through full historical and incremental append execution.

## Documentation Evidence

Phase V synchronized these user-facing compatibility documents:

- `README.md`
- `docs/CONFORMANCE.md`
- `docs/EXECUTION_SEMANTICS.md`
- `docs/SEMANTIC_MODEL.md`
- `docs/BUILTIN_SIGNATURES.md`
- `docs/RELEASE_NOTES.md`
- `docs/LONG_TERM_EXECUTION_PLAN.md`
- `docs/PHASE_V_EXECUTION_PLAN.md`

## Verification Results

Focused verification:

```text
cargo fmt --check
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-runtime --test profile_fixtures
cargo test -p pine-cli strategy
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-wasm strategy
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/*.whl
python3 -m pytest python/tests
git diff --check
```

Snapshot refresh checks:

```text
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
```

Closeout verification:

```text
scripts/verify.sh
```

Focused verification, snapshot refresh checks, and the closeout release gate
passed on the Phase V closeout workspace.
