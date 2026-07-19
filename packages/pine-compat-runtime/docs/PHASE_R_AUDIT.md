# Phase R Audit: Strategy Exit Brackets

Status: closed for the current fixture-backed bracket subset.

Phase R turned the Phase Q bracket design gate into the first positive
`strategy.exit` bracket implementation. The compatibility claim remains
partial and is tied to `tests/fixtures/conformance.tsv`, semantic fixtures,
runtime fixtures and snapshots, incremental parity, host binding tests, docs,
and the closeout release gate.

## Completed Slices

- Slice 0 locked the Phase Q/P/N/M baselines, kept conformance conservative,
  and added this execution plan as the Phase R playbook.
- Slice 1 extended broker pending-exit state with bracket placement while
  preserving the one-pending-exit model and public output shape.
- Slice 2 evaluated pending brackets with deterministic stop/loss-first
  same-bar both-hit precedence.
- Slice 3 routed the four supported bracket forms through runtime
  `strategy.exit` dispatch while preserving single-trigger behavior.
- Slice 4 added semantic guardrails: same-side pairs and 3+ trigger calls
  remain diagnostic-only unsupported, while exactly one downside plus one
  upside trigger analyzes.
- Slice 5 added runtime fixtures, golden snapshots, and incremental append
  coverage for bracket fills, creation-bar ineligibility, repetition,
  replacement, invalid legs, state timing, both-hit precedence, and interaction
  contexts.
- Slice 6 added CLI, Python, and WASM host parity tests for a bracket fixture
  without adding binding-level broker logic.
- Slice 7 synchronized conformance metadata, matrix snapshot, maintainer docs,
  release notes, and roadmap status, then ran the release closeout gate.

## Supported Surface

The source of truth is `tests/fixtures/conformance.tsv`.

- `strategy.exit` remains partial.
- Single-trigger stop, limit, profit, and loss exits remain supported for the
  current one-net-long broker.
- Supported bracket forms are exactly:
  - `stop + limit`
  - `stop + profit`
  - `loss + limit`
  - `loss + profit`
- A bracket has exactly one downside leg and one upside leg. Downside legs are
  `stop=price` and `loss=ticks`; upside legs are `limit=price` and
  `profit=ticks`.
- Profit and loss tick distances convert once at placement time from
  `strategy.position_avg_price` using the fixed default `syminfo.mintick`.
- A bracket is one broker-owned pending full-position exit. Repeating an
  identical bracket preserves the original eligibility bar; changing either leg
  kind, price, or exit identity replaces the pending exit and resets
  eligibility.
- New and replaced exits are not eligible on the creation or replacement bar.
  Later historical bars fill when `low <= stop/loss price` or
  `high >= limit/profit price`.
- If both bracket legs are touched on the same eligible historical bar, the
  downside stop/loss side fills first.
- A filled bracket emits exactly one `strategy.exit` order event using the exit
  id, records one closed trade under the source entry id, clears the position,
  and updates normal position and equity snapshots.

## Public Output And Host Behavior

Phase R did not add top-level runtime JSON fields, Python dictionary keys, WASM
JSON fields, public pending-order records, bracket-leg metadata, partial-fill
fields, exit-reason fields, or a runtime schema bump. Runtime output remains
`schemaVersion: 3`.

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
`StrategyResult` into native dictionaries. Host tests cover a shared
both-hit bracket fixture and assert one exit order event, one closed trade, and
the stop/loss-first fill price.

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

Positive semantic fixtures:

- `tests/fixtures/sema/supported_strategy_exit_stop_limit.pine`
- `tests/fixtures/sema/supported_strategy_exit_stop_profit.pine`
- `tests/fixtures/sema/supported_strategy_exit_loss_limit.pine`
- `tests/fixtures/sema/supported_strategy_exit_loss_profit.pine`

Unsupported semantic fixtures that remain intentionally negative:

- `tests/fixtures/sema/unsupported_strategy_exit_stop_loss.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_limit_profit.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_three_triggers.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_four_triggers.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_profit_qty.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_loss_qty_percent.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_trailing.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_profit_trailing.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_partial_quantity.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_missing_trigger.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_named_missing_trigger.pine`
- `tests/fixtures/sema/unsupported_strategy_exit_missing_id.pine`

Runtime fixtures and snapshots:

- `tests/fixtures/runtime/strategy_exit_bracket_stop_limit_limit_fill.pine`
- `tests/fixtures/runtime/strategy_exit_bracket_stop_limit_stop_fill.pine`
- `tests/fixtures/runtime/strategy_exit_bracket_loss_profit_profit_fill.pine`
- `tests/fixtures/runtime/strategy_exit_bracket_loss_profit_loss_fill.pine`
- `tests/fixtures/runtime/strategy_exit_bracket_mixed_pairs.pine`
- `tests/fixtures/runtime/strategy_exit_bracket_creation_bar.pine`
- `tests/fixtures/runtime/strategy_exit_bracket_repeated.pine`
- `tests/fixtures/runtime/strategy_exit_bracket_replacement.pine`
- `tests/fixtures/runtime/strategy_exit_bracket_invalid_leg.pine`
- `tests/fixtures/runtime/strategy_exit_bracket_both_hit.pine`
- `tests/fixtures/runtime/strategy_exit_bracket_state.pine`
- `tests/fixtures/runtime/strategy_exit_bracket_interactions.pine`
- `tests/snapshots/runtime_strategy_exit_bracket_stop_limit_limit_fill.json`
- `tests/snapshots/runtime_strategy_exit_bracket_stop_limit_stop_fill.json`
- `tests/snapshots/runtime_strategy_exit_bracket_loss_profit_profit_fill.json`
- `tests/snapshots/runtime_strategy_exit_bracket_loss_profit_loss_fill.json`
- `tests/snapshots/runtime_strategy_exit_bracket_mixed_pairs.json`
- `tests/snapshots/runtime_strategy_exit_bracket_creation_bar.json`
- `tests/snapshots/runtime_strategy_exit_bracket_repeated.json`
- `tests/snapshots/runtime_strategy_exit_bracket_replacement.json`
- `tests/snapshots/runtime_strategy_exit_bracket_invalid_leg.json`
- `tests/snapshots/runtime_strategy_exit_bracket_both_hit.json`
- `tests/snapshots/runtime_strategy_exit_bracket_state.json`
- `tests/snapshots/runtime_strategy_exit_bracket_interactions.json`

Host and append evidence:

- `crates/pine-cli/src/main.rs` includes golden runtime snapshots for all
  bracket fixtures and a targeted host parity assertion for the both-hit
  bracket fixture.
- `crates/pine-wasm/src/tests/mod.rs` asserts the same both-hit bracket JSON
  contract through the WASM host surface.
- `python/tests/test_bindings.py` asserts the same both-hit bracket contract as
  a native dictionary.
- `crates/pine-runtime/tests/incremental.rs` runs bracket fixtures through full
  historical and incremental append execution.

## Verification Results

Slice-level verification included:

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
python3 -m pip install --force-reinstall dist/pine_compat_runtime-0.1.0-cp310-abi3-manylinux_2_35_x86_64.whl
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

It passed on the closeout workspace.

## Deferred Broker Tails

- Same-side pairs `stop + loss` and `limit + profit`, and 3+ trigger forms.
- Trailing stops.
- Partial exits, `qty`, `qty_percent`, and reservation behavior.
- Missing-entry pre-placement.
- Multiple entries, pyramiding, short exposure, and reversals.
- Multiple pending exits and public pending-order records.
- Commission, slippage, margin, richer sizing, strategy alerts, and realtime
  broker rollback for brackets.
