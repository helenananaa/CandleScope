# Phase Z Strategy Exit Omitted-Quantity Boundary Audit

Status: closed on 2026-06-02.

Phase Z closes the omitted-quantity `strategy.exit` boundary for the current
long-only, one-net-position, no-pyramiding broker. It does not add a new
reservation subset and does not change the public runtime output schema.

## Supported Surface

The supported Phase Z boundary is:

- omitted `qty` and omitted `qty_percent` exits keep full-position
  one-effective-pending behavior;
- different `id + from_entry` identities replace the previous omitted
  full-position pending exit rather than appending another reservation;
- the replacement behavior applies to supported single-trigger, bracket, and
  trailing exit forms;
- a later omitted full-position exit clears earlier explicit fixed-`qty` or
  `qty_percent` reservations for the current matching long entry;
- explicit fixed-`qty` and `qty_percent` single-trigger, bracket, and trailing
  reservations remain the only fixture-backed multiple-pending reservation
  subset;
- filled exits emit existing `strategy.exit` order events and closed trade
  records with absolute filled quantities.

## Unsupported Boundaries

Phase Z deliberately does not support:

- omitted-quantity multiple pending reservations;
- missing-entry pre-placement of pending exits;
- short exposure, reversals, pyramiding, or multiple simultaneous entries;
- `qty + qty_percent` in one `strategy.exit` call;
- same-side trigger pairs, 3+ trigger combinations, or invalid trailing
  combinations;
- reservation behavior outside explicit fixed `qty` or `qty_percent`
  single-trigger, bracket, and trailing exits;
- public pending-order records, reservation fields, remaining-quantity fields,
  percent fields, bracket-leg fields, trailing-state fields, activation fields,
  trigger-side fields, exit-reason fields, or a runtime schema bump;
- `strategy.order`, `strategy.cancel`, `strategy.cancel_all`, OCA APIs, rich
  order types, commission, slippage, margin, percent-of-equity sizing, cash
  sizing, contracts sizing, realtime strategy handoff, or intrabar path
  reconstruction.

## Public Output And Hosts

Runtime output remains `schemaVersion: 3`.

Strategy-mode public output remains a `strategy` object with exactly:

```text
orders
trades
position
equity
diagnostics
```

The public output exposes absolute order and trade `qty` values only. It does
not expose pending exits, reservation ledgers, remaining quantities, percent
inputs, bracket-leg metadata, trailing state, activation metadata, trigger-side
metadata, or exit reasons.

CLI, Python, and WASM hosts reuse the shared runtime path. None of the host
bindings implements replacement, reservation clearing, or reservation math.

## Fixture Evidence

Broker tests added for Phase Z:

```text
omitted_quantity_single_trigger_with_new_identity_replaces_instead_of_appending
omitted_quantity_bracket_with_new_identity_replaces_instead_of_appending
omitted_quantity_trailing_with_new_identity_replaces_and_resets_eligibility
omitted_quantity_exit_replaces_explicit_reservation_pool
explicit_reservation_after_omitted_quantity_replaces_full_then_appends_supported_reservations
```

Runtime fixtures added for the public omitted-quantity boundary:

```text
tests/fixtures/runtime/strategy_exit_omitted_single_replacement.pine
tests/fixtures/runtime/strategy_exit_omitted_bracket_replacement.pine
tests/fixtures/runtime/strategy_exit_omitted_trailing_replacement.pine
tests/fixtures/runtime/strategy_exit_omitted_replaces_reservations.pine
```

The matching runtime snapshots are in `tests/snapshots/` with the same fixture
stems. They show one public exit path for each fixture: `XL`, `XB2`, `XT2`, and
`XFULL` respectively.

## Host Evidence

Host parity is covered by:

- CLI:
  `strategy_exit_omitted_replaces_reservations_fixture_has_host_stable_shape`
- Python:
  `test_run_script_returns_strategy_exit_omitted_replaces_reservations_contract`
- WASM:
  `runs_strategy_exit_omitted_replaces_reservations_from_csv_to_public_strategy_json`

All three host tests run
`tests/fixtures/runtime/strategy_exit_omitted_replaces_reservations.pine` with
the default runtime bars and assert one public `XFULL` `strategy.exit` event,
absolute quantity `2`, runtime `schemaVersion: 3`, stable `strategy` keys, and
no public pending, reservation, remaining-quantity, `qty_percent`,
trigger-side, activation, or exit-reason fields.

## Documentation Evidence

The Phase Z compatibility claim is synchronized in:

- `tests/fixtures/conformance.tsv`
- `tests/snapshots/matrix.json`
- `README.md`
- `docs/CONFORMANCE.md`
- `docs/EXECUTION_SEMANTICS.md`
- `docs/SEMANTIC_MODEL.md`
- `docs/LONG_TERM_EXECUTION_PLAN.md`
- `docs/RELEASE_NOTES.md`

The docs keep `strategy.exit` `partial`, keep broad `strategy.*` unsupported,
and explicitly state that omitted-quantity multiple reservations remain
unsupported.

## Verification

Focused verification passed:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
cargo test -p pine-cli strategy
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-wasm strategy
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/pine_compat_runtime-0.1.0-cp310-abi3-manylinux_2_35_x86_64.whl
python3 -m pytest python/tests
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-cli matrix
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo run -q -p pine-cli -- matrix
git diff --check
```

Canonical release verification passed:

```text
git diff --check
scripts/verify.sh
git status --short
```

`scripts/verify.sh` covered formatting, clippy with `-D warnings`, workspace
tests, structural guardrails, wasm32 checking for `pine-wasm`, Python wheel
build/install, and Python binding tests.
