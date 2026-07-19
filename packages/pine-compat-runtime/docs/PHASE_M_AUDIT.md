# Phase M Audit: Strategy Exit and Order Lifecycle

Status: closed for the current fixture-backed strategy exit subset.

Phase M widened the Phase G/L long-only strategy runtime with a narrow
`strategy.exit` lifecycle. The compatibility claim remains intentionally
partial and is tied to `tests/fixtures/conformance.tsv`, runtime snapshots,
semantic fixtures, host binding tests, and the closeout release gate.

## Completed Slices

- Slice 0 locked the strategy-exit boundary before positive support was
  claimed. The first executable target was restricted to full-position
  stop/limit exits for the current one-net-long broker, with combined,
  profit/loss, trailing, partial quantity, requested-context, and function
  side-effect forms kept fixture-backed unsupported.
- Slice 1 added semantic staging for accepted `strategy.exit` calls in
  strategy-mode scripts while unsupported variants continued to produce stable
  diagnostics.
- Slice 2 added broker-owned pending exit state. Accepted exit calls can place
  or replace one internal pending exit for the matching current long entry;
  `strategy.close(id)` cancels the matching pending exit.
- Slice 3 implemented stop exits:
  `strategy.exit(id, from_entry, stop=price)` fills the full long position on a
  later historical bar when `low <= stop`, at the stop price.
- Slice 4 implemented limit exits:
  `strategy.exit(id, from_entry, limit=price)` fills the full long position on
  a later historical bar when `high >= limit`, at the limit price.
- Slice 5 closed the combined stop/limit bracket boundary as unsupported for
  Phase M. Same-bar high/low precedence must be designed before bracket
  compatibility is claimed.
- Slice 6 hardened exit interactions across supported branch, switch, loop,
  strategy state, history-reference, and incremental append execution paths.
- Slice 7 kept the public runtime schema unchanged. Filled exits are represented
  by the existing strategy `orders`, `trades`, `position`, `equity`, and
  `diagnostics` fields, without adding public pending-order, partial-fill, or
  exit-reason fields.

## Supported Surface

The source of truth is `tests/fixtures/conformance.tsv`.

- `strategy.exit` is partial. Supported forms are
  `strategy.exit(id, from_entry, stop=price)` and
  `strategy.exit(id, from_entry, limit=price)` only.
- The call is strategy-mode-only and uses the current long-only strategy
  runtime. `id` and `from_entry` identify the exit order and matching source
  entry. The current subset supports one net long entry, one broker-owned
  pending full-position exit, and no pyramiding.
- A supported exit can be created only for the matching current long entry.
  Missing or mismatched entries produce stable strategy diagnostics and do not
  create orphan pending exits.
- Repeating an unchanged accepted exit call preserves the original eligibility
  bar. Replacing the exit with a different supported trigger creates a new
  pending exit that is not eligible on the replacement bar.
- New or replaced pending exits are not eligible on the same bar. Stop exits
  fill on a later historical bar when `low <= stop`; limit exits fill on a
  later historical bar when `high >= limit`. Both fill at the configured exit
  price.
- Filled exits close the full current long position. The closed trade keeps the
  source entry id, while the order event uses the exit id and
  `strategy.exit` direction.
- Supported exit calls can appear in the same fixture-backed statement contexts
  as other supported strategy side effects, including branches, switches, and
  loops. Strategy state reads and constant history references around the fill
  follow the existing series model.

Unsupported Phase M variants remain explicit:

- combined stop plus limit brackets.
- `profit`, `loss`, trailing, partial quantity, and reservation behavior.
- missing-entry or pre-entry pending exits.
- multiple simultaneous entries, pyramiding, short exposure, and reversals.
- `strategy.order` and richer order modification semantics.
- commission, slippage, margin, currency conversion, cash sizing, contracts,
  and percent-of-equity sizing.
- strategy alerts, alert placeholders, strategy closed/open trade namespaces,
  host-specific broker APIs, chart UI behavior, and realtime strategy execution.

## Public Output And Host Behavior

Phase M did not add top-level runtime JSON fields, Python dictionary keys, or
WASM JSON fields. Runtime output remains `schemaVersion: 3`.

Strategy-mode runtime output keeps the existing top-level `strategy` object:

```text
strategy: {
  orders: [],
  trades: [],
  position: [],
  equity: [],
  diagnostics: []
}
```

A filled Phase M exit appends a `StrategyOrderEvent` with the exit id,
`direction: "strategy.exit"`, full position quantity, fill bar index, time, and
fill price. The corresponding closed trade keeps the source entry id and exit
price, clears the position snapshot, and updates the normal equity snapshot.

CLI and WASM share `public_runtime_result_json`; Python maps the same strategy
result into native dictionaries. Host tests cover representative stop and limit
exit contracts through CLI snapshots, Python dictionaries, and WASM JSON.

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
- `strategy.exit`: `partial`
- `strategy.*`: `unsupported`

Runtime fixtures and snapshots:

- `tests/fixtures/runtime/strategy_exit_stop.pine`
- `tests/fixtures/runtime/strategy_exit_limit.pine`
- `tests/fixtures/runtime/strategy_exit_interactions.pine`
- `tests/snapshots/runtime_strategy_exit_stop.json`
- `tests/snapshots/runtime_strategy_exit_limit.json`
- `tests/snapshots/runtime_strategy_exit_interactions.json`

Semantic fixtures:

- `tests/fixtures/sema/supported_strategy_exit_stop.pine`
- `tests/fixtures/sema/supported_strategy_exit_limit.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_stop_limit.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_profit_loss.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_trailing.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_partial_quantity.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_missing_id.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_function_side_effect.pine`
- `tests/fixtures/sema/unsupported_request_strategy_exit.pine`

Host and append evidence:

- `crates/pine-cli/src/main.rs` includes golden runtime snapshots for stop,
  limit, and interaction fixtures.
- `crates/pine-wasm/src/tests/mod.rs` asserts stop and limit exit JSON
  contracts.
- `python/tests/test_bindings.py` asserts stop and limit exit dictionary
  contracts.
- `crates/pine-runtime/tests/incremental.rs` runs every runtime fixture through
  full historical and incremental append execution.

## Verification Results

Slice-level verification included:

```text
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-runtime --test profile_fixtures
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
python3 -m pytest python/tests
cargo test --workspace
git diff --check
```

Snapshot refresh commands were run only when public runtime or matrix snapshots
changed:

```text
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
UPDATE_SNAPSHOTS=1 cargo test -p pine-wasm analysis_outputs_match_golden_snapshots
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

## Maintenance Tails

- Combined stop/limit bracket exits and same-bar high/low precedence.
- Profit/loss tick helpers if they require mintick, entry-relative conversion,
  or same-bar precedence rules beyond the first stop/limit subset.
- Trailing stops.
- Partial exits and quantity reservation behavior.
- Missing-entry pre-placement and multiple pending exits.
- Short entries, reversals, and short exposure.
- `strategy.order` and richer order modification semantics.
- Multiple simultaneous entries and pyramiding.
- Commission, slippage, margin, currency conversion, cash sizing, contracts,
  and percent-of-equity sizing.
- Strategy closed-trade and open-trade namespaces.
- Strategy alerts and alert placeholders.
- Realtime strategy execution and forming-bar broker rollback.
- Host-specific broker APIs or chart UI behavior outside the public runtime
  contract.

## Structure Check

Strategy declaration and order semantic validation is owned by
`crates/pine-sema/src/analyzer/strategy.rs`. Built-in signatures are registered
in `crates/pine-builtins`. Strategy-specific runtime state is owned by
`crates/pine-runtime/src/strategy`, and public strategy result structs are in
`crates/pine-runtime/src/output/strategy.rs`.

The closeout structure guard passed through `scripts/verify.sh`, checking 129
production Rust source files. Future richer broker behavior should stay in the
strategy-owned analyzer and runtime modules rather than expanding generic call
dispatch or public host bindings first.

## Closeout Checklist

- The exact `strategy.exit` subset is documented as partial and fixture-backed.
- Unsupported exit variants remain explicit and tested.
- The conformance matrix and matrix snapshot agree on supported and unsupported
  strategy exit behavior.
- Public host behavior is synchronized across Rust runtime, CLI, Python, and
  WASM without a runtime schema bump.
- Runtime snapshots cover stop, limit, and interaction behavior.
- `docs/LONG_TERM_EXECUTION_PLAN.md`, `docs/CONFORMANCE.md`,
  `docs/LANGUAGE_SCOPE.md`, `docs/EXECUTION_SEMANTICS.md`,
  `docs/SEMANTIC_MODEL.md`, and `docs/RELEASE_NOTES.md` agree on the closed
  Phase M surface.
- `scripts/verify.sh` passes on the closeout workspace.
