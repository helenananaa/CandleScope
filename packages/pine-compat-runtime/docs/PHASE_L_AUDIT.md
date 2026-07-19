# Phase L Audit: Strategy Usability

Status: closed for the current fixture-backed strategy usability subset.

Phase L widened the Phase G long-only strategy runtime with observable
strategy state, a fixed default quantity declaration subset, and a documented
`strategy.exit` design boundary. The compatibility claim remains intentionally
partial and is tied to `tests/fixtures/conformance.tsv`, runtime snapshots,
semantic fixtures, host binding tests, and the closeout release gate.

## Completed Slices

- Slice 0 locked strategy state-variable diagnostics before implementation:
  known Phase L variables were kept strategy-mode-only, unknown `strategy.*`
  names stayed on the broad unsupported strategy path, and no public output
  shape changed.
- Slice 1 added `strategy.position_size` and
  `strategy.position_avg_price` as read-only strategy-mode historical series
  floats.
- Slice 2 added `strategy.openprofit`, `strategy.netprofit`, and
  `strategy.equity` for the existing long-only broker model.
- Slice 3 hardened strategy state variables across supported control flow, pure
  UDF arguments, constant history references, incremental append execution, and
  profile retention.
- Slice 4 added the fixed default quantity subset:
  `default_qty_type=strategy.fixed` with positive const numeric
  `default_qty_value`. `strategy.entry(id, strategy.long)` may omit `qty` only
  when that declaration default is configured; explicit `qty` still overrides
  the default.
- Slice 5 kept `strategy.exit` unsupported and recorded the design questions
  that must be answered before a future stop/limit or pending-exit subset can
  be implemented.

## Supported Surface

The source of truth is `tests/fixtures/conformance.tsv`.

- `strategy` remains partial. The supported declaration subset is `title`,
  `shorttitle`, `overlay`, `max_bars_back`, positive const numeric
  `initial_capital`, and fixed default quantity settings using
  `default_qty_type=strategy.fixed` plus positive const numeric
  `default_qty_value`.
- `strategy.entry` remains partial. The supported form opens one long market
  position at current bar close with `strategy.long`, either explicit positive
  numeric `qty` or the configured fixed default quantity, one net long position,
  and no pyramiding.
- `strategy.close` remains partial. The supported form closes the full matching
  long entry id at the current bar close. Missing, mismatched, or repeated
  closes are no-op events.
- Strategy state variables are partial and strategy-mode-only:
  `strategy.position_size`, `strategy.position_avg_price`,
  `strategy.openprofit`, `strategy.netprofit`, and `strategy.equity`.
- The state variables behave as ordinary read-only series floats in supported
  expression contexts, including branches, switches, loops, pure UDF arguments,
  and constant history references. Direct mutation, indicator-mode reads, and
  requested-context reads remain rejected.
- `strategy.exit`, richer order types, short exposure, pyramiding, partial
  exits, percent/cash/contracts sizing, commission, slippage, margin, currency
  conversion, strategy closed/open trade namespaces, strategy alerts, and
  realtime strategy execution remain unsupported.

## Public Output And Host Behavior

Phase L did not add top-level runtime JSON fields, Python dictionary keys, or
WASM JSON fields. Strategy state variables are observed through ordinary
runtime outputs such as `plot`.

Strategy-mode runtime output keeps runtime `schemaVersion: 3` and the Phase G
top-level `strategy` object:

```text
strategy: {
  orders: [],
  trades: [],
  position: [],
  equity: [],
  diagnostics: []
}
```

CLI and WASM share `public_runtime_result_json`; Python maps the same strategy
result into native dictionaries. Phase L host tests cover strategy entry with
fixed default quantity, position/profit/equity state variables, history
references, UDF argument use, and close behavior through those public surfaces.

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
- `strategy.*`: `unsupported`

Runtime fixtures and snapshots:

- `tests/fixtures/runtime/strategy_no_order.pine`
- `tests/fixtures/runtime/strategy_entry.pine`
- `tests/fixtures/runtime/strategy_default_quantity.pine`
- `tests/fixtures/runtime/strategy_default_quantity_override.pine`
- `tests/fixtures/runtime/strategy_close.pine`
- `tests/fixtures/runtime/strategy_equity.pine`
- `tests/fixtures/runtime/strategy_position_state.pine`
- `tests/fixtures/runtime/strategy_profit_state.pine`
- `tests/fixtures/runtime/strategy_variable_interactions.pine`
- `tests/snapshots/runtime_strategy_empty.json`
- `tests/snapshots/runtime_strategy_entry.json`
- `tests/snapshots/runtime_strategy_default_quantity.json`
- `tests/snapshots/runtime_strategy_default_quantity_override.json`
- `tests/snapshots/runtime_strategy_close.json`
- `tests/snapshots/runtime_strategy_equity.json`
- `tests/snapshots/runtime_strategy_position_state.json`
- `tests/snapshots/runtime_strategy_profit_state.json`
- `tests/snapshots/runtime_strategy_variable_interactions.json`

Semantic fixtures:

- `tests/fixtures/sema/supported_strategy_declaration.pine`
- `tests/fixtures/sema/supported_strategy_initial_capital.pine`
- `tests/fixtures/sema/supported_strategy_default_quantity.pine`
- `tests/fixtures/sema/supported_strategy_entry.pine`
- `tests/fixtures/sema/supported_strategy_close.pine`
- `tests/fixtures/sema/supported_strategy_position_state.pine`
- `tests/fixtures/sema/supported_strategy_profit_state.pine`
- `tests/fixtures/sema/supported_strategy_variable_interactions.pine`
- `tests/fixtures/sema/unsupported_strategy_initial_capital.pine`
- `tests/fixtures/sema/unsupported_strategy_default_quantity.pine`
- `tests/fixtures/sema/unsupported_strategy_entry_indicator.pine`
- `tests/fixtures/sema/unsupported_strategy_entry_short.pine`
- `tests/fixtures/sema/unsupported_strategy_entry_stop_limit.pine`
- `tests/fixtures/sema/unsupported_strategy_entry_qty.pine`
- `tests/fixtures/sema/unsupported_strategy_entry_missing_qty.pine`
- `tests/fixtures/sema/unsupported_strategy_close_indicator.pine`
- `tests/fixtures/sema/unsupported_strategy_state_indicator.pine`
- `tests/fixtures/sema/unsupported_request_strategy_state.pine`
- `tests/fixtures/sema/unsupported_strategy_state_mutation.pine`
- `tests/fixtures/sema/unsupported_strategy_state_variables.pine`
- `tests/fixtures/sema/unsupported_strategy_unknown_variable.pine`
- `tests/fixtures/sema/unsupported_strategy_orders.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_stop.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_limit.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_profit_loss.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_trailing.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_partial_quantity.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_missing_id.pine`

Profile and append evidence:

- `crates/pine-runtime/tests/incremental.rs` runs every runtime fixture through
  full historical and incremental append execution.
- `tests/fixtures/profile/strategy_variable_history.pine` and
  `crates/pine-runtime/tests/profile_fixtures.rs` assert static one-bar history
  retention for strategy state history references.

## Verification Results

Slice-level verification included:

```text
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-runtime --test profile_fixtures
cargo test -p pine-builtins strategy
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
python3 -m pytest python/tests
cargo test --workspace
git diff --check
scripts/verify.sh
```

The closeout verification command was:

```text
git diff --check
scripts/verify.sh
```

It passed on the closeout workspace. This gate includes `cargo fmt --check`,
`cargo clippy --workspace --all-targets -- -D warnings`,
`cargo test --workspace`, `python3 scripts/check_structure.py`,
`cargo check -p pine-wasm --target wasm32-unknown-unknown`,
`maturin build --manifest-path crates/pine-python/Cargo.toml --out dist`,
wheel reinstall through `python3 -m pip install --force-reinstall dist/*.whl`,
and `python3 -m pytest python/tests`.

No indicator runtime snapshots changed during Phase L closeout. The matrix
snapshot changed only when conformance metadata changed for the supported and
unsupported strategy surface.

## Maintenance Tails

- `strategy.exit` stop/limit exits and any pending-order output contract.
- Short entries, reversal behavior, and short exposure.
- `strategy.order` and richer order modification semantics.
- Pyramiding and multiple simultaneous entries.
- Partial exits, repeated exit modification, and mixed stop/limit trigger
  precedence.
- Commission, slippage, margin, currency conversion, cash sizing, contracts,
  and percent-of-equity sizing.
- Strategy closed-trade and open-trade namespaces.
- Strategy reporting helpers beyond the first position/profit/equity variables.
- Strategy alerts and alert placeholders.
- Realtime strategy execution and forming-bar broker rollback.
- Host-specific broker APIs or chart UI behavior outside the public runtime
  contract.

## Structure Check

Strategy declaration and order semantic validation is owned by
`crates/pine-sema/src/analyzer/strategy.rs`. Strategy-specific runtime state is
owned by `crates/pine-runtime/src/strategy`. Public strategy result structs are
in `crates/pine-runtime/src/output/strategy.rs`, and host bindings map those
shared structs without duplicating broker logic.

The closeout structure guard passed. Future executable strategy order work
should keep adding strategy-specific validation and broker behavior in these
owned modules rather than expanding generic call or runtime dispatch logic.

## Closeout Checklist

- Strategy state variables are documented as partial and fixture-backed.
- Indicator and strategy modes remain separated.
- Public host behavior is synchronized across Rust runtime, CLI, Python, and
  WASM.
- Unsupported strategy order types and broker settings remain explicit.
- Runtime snapshots and matrix snapshots catch accidental compatibility
  widening.
- `docs/LONG_TERM_EXECUTION_PLAN.md`, `docs/CONFORMANCE.md`,
  `docs/LANGUAGE_SCOPE.md`, `docs/EXECUTION_SEMANTICS.md`, and
  `docs/RELEASE_NOTES.md` agree on the closed Phase L surface.
- `scripts/verify.sh` passes on the closeout workspace.
