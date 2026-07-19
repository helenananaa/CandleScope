# Phase O Audit: Strategy Reporting Counts

Status: closed for the current fixture-backed strategy reporting count subset.

Phase O added the first narrow strategy reporting variables without opening a
larger broker-simulation phase. The compatibility claim remains intentionally
partial and is tied to `tests/fixtures/conformance.tsv`, runtime snapshots,
semantic fixtures, host binding tests, incremental execution, and the closeout
release gate.

## Completed Slices

- Slice 0 locked the Phase N baseline and confirmed that Phase O should support
  only `strategy.closedtrades` and `strategy.opentrades` count variables.
- Slice 1 added semantic and type staging for both read-only `series int`
  variables while keeping indicator-mode, requested-context, mutation, and rich
  reporting forms rejected.
- Slice 2 added broker-owned closed/open trade count accessors and focused
  broker tests for flat, entry, no-pyramiding, close, pending-exit fill, and
  mismatch behavior.
- Slice 3 routed runtime variable reads through those broker accessors and
  covered same-bar `strategy.close`, delayed pending-exit visibility, and
  constant history references.
- Slice 4 added runtime fixtures, golden snapshots, and incremental append
  coverage for normal close and pending-exit count scenarios.
- Slice 5 hardened CLI, Python, and WASM public host behavior for representative
  count scripts while keeping the public strategy output shape unchanged.
- Slice 6 synchronized conformance metadata, semantic/execution/conformance
  docs, release notes, the long-term roadmap, and the matrix snapshot.
- Slice 7 closed this audit and ran the full release verification gate.

## Supported Surface

The source of truth is `tests/fixtures/conformance.tsv`.

- `strategy.closedtrades` is partial: a strategy-mode historical `series int`
  count of closed trades recorded by the current long-only broker.
- `strategy.opentrades` is partial: a strategy-mode historical `series int`
  count of open trades represented by the current no-pyramiding long-only
  broker. It is `1` when the supported long position is open and `0` when flat.
- Both variables are read-only and usable in supported expressions, branches,
  switches, loops, pure UDF arguments, and constant history references.
- Supported `strategy.close(id)` calls mutate broker state immediately, so later
  statements on the same bar see updated count values.
- Pending `strategy.exit(...)` fills are evaluated after script statements on
  the historical bar. Script reads on the triggering bar see pre-fill counts;
  script reads on the next bar see updated counts.
- Indicator-mode usage, requested-context usage, and direct mutation remain
  rejected.

Unsupported Phase O variants remain explicit:

- Strategy closed-trade and open-trade namespace functions such as
  `strategy.closedtrades.profit(...)`,
  `strategy.closedtrades.entry_price(...)`, and
  `strategy.opentrades.entry_price(...)`.
- Public open-trade records.
- Public pending-order records, partial-fill fields, and exit-reason fields.
- Rich reporting metrics such as drawdown, win/loss trade counts, and runup.
- Broader broker behavior from the Phase N maintenance tails, including
  combined brackets, trailing stops, partial exits, pyramiding, short exposure,
  commission, slippage, margin, strategy alerts, and realtime strategy
  execution.

## Public Output And Host Behavior

Phase O did not add top-level runtime JSON fields, Python dictionary keys, WASM
JSON fields, public open-trade records, public pending-order records, partial
fill fields, or exit-reason fields. Runtime output remains `schemaVersion: 3`.

The count variables are script state only. Scripts can expose them through
ordinary outputs such as plots. Public strategy output remains:

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
result into native dictionaries. Host tests cover representative count plot
values and the unchanged strategy object shape.

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

Runtime fixtures and snapshots:

- `tests/fixtures/runtime/strategy_trade_counts.pine`
- `tests/fixtures/runtime/strategy_exit_trade_counts.pine`
- `tests/snapshots/runtime_strategy_trade_counts.json`
- `tests/snapshots/runtime_strategy_exit_trade_counts.json`

Semantic fixtures:

- `tests/fixtures/sema/supported_strategy_trade_counts.pine`
- `tests/fixtures/sema/supported_strategy_trade_count_interactions.pine`
- `tests/fixtures/sema/unsupported_strategy_state_indicator.pine`
- `tests/fixtures/sema/unsupported_request_strategy_state.pine`
- `tests/fixtures/sema/unsupported_strategy_state_mutation.pine`
- `tests/fixtures/sema/unsupported_strategy_state_variables.pine`

Host and append evidence:

- `crates/pine-cli/src/main.rs` includes golden runtime snapshots for both
  representative count fixtures.
- `crates/pine-wasm/src/tests/mod.rs` asserts representative count plot values
  and unchanged strategy JSON object shape.
- `python/tests/test_bindings.py` asserts representative count plot values and
  unchanged strategy dictionary keys.
- `crates/pine-runtime/tests/incremental.rs` runs the new runtime fixtures
  through full historical and incremental append execution.

## Verification Results

Slice-level verification included:

```text
cargo fmt --check
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli conformance_metadata_references_existing_fixtures
cargo test -p pine-cli strategy
cargo test -p pine-wasm strategy
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/*.whl
python3 -m pytest python/tests
git diff --check
```

Snapshot refresh commands were run only when public runtime or matrix snapshots
changed:

```text
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
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

- Strategy closed-trade and open-trade namespace functions.
- Public open-trade records.
- Public pending-order records, partial-fill fields, and exit-reason fields.
- Rich metrics such as max drawdown, win trades, loss trades, runup, and
  detailed per-trade reporting helpers.
- Combined trigger brackets and same-bar high/low precedence.
- Trailing stops.
- Partial exits and quantity reservation behavior.
- Missing-entry pre-placement and multiple pending exits.
- Short entries, reversals, and short exposure.
- `strategy.order` and richer order modification semantics.
- Multiple simultaneous entries and pyramiding.
- Commission, slippage, margin, currency conversion, cash sizing, contracts,
  and percent-of-equity sizing.
- Strategy alerts and alert placeholders.
- Realtime strategy execution and forming-bar broker rollback.
- Host-specific broker APIs or chart UI behavior outside the public runtime
  contract.

Recommended next stage: keep future strategy work as maintenance slices unless
a larger broker phase is deliberately opened for brackets, partial exits,
multiple pending exits, short exposure, or realtime broker rollback.

## Structure Check

Strategy declaration, order, and state-variable semantic validation is owned by
`crates/pine-sema/src/analyzer/strategy.rs`. Built-in series value types are
registered in `crates/pine-builtins/src/constants/series.rs`. Strategy-specific
runtime state and count accessors are owned by `crates/pine-runtime/src/strategy`.
Runtime variable evaluation is in `crates/pine-runtime/src/builtins/variables.rs`,
and public strategy result structs remain in
`crates/pine-runtime/src/output/strategy.rs`.
