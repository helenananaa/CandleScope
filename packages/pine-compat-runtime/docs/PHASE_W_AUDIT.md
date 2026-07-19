# Phase W Strategy Exit Reservation Audit

Status: closed on 2026-06-02.

Phase W implements the first deterministic quantity-reservation subset for
multiple `strategy.exit` calls in the existing strategy runtime. The phase keeps
the current long-only, one-net-position, no-pyramiding broker and does not
change the public runtime output schema.

## Supported Surface

The supported Phase W subset is:

- multiple pending `strategy.exit` records for the current matching long entry
  only when each call is a single-trigger exit with explicit fixed `qty` or
  explicit `qty_percent`;
- supported single-trigger families: `stop`, `limit`, `profit`, and `loss`;
- pending exit identity remains `id + from_entry`;
- different identities append pending exits in placement order;
- same-identity calls replace the existing pending exit after releasing the old
  reservation;
- fixed `qty` and `qty_percent` resolve once at placement time to absolute
  reserved close quantities;
- new reservations clamp to remaining unreserved position quantity;
- zero-reservation placements are rejected with strategy diagnostics and leave
  existing pending exits unchanged;
- same-side touched exits fill in placement order;
- when downside and upside candidates are both touched on the same eligible
  historical bar, downside candidates fill and opposite-side candidates remain
  pending if a long position remains;
- filled exits emit existing `strategy.exit` order events and closed trade
  records with absolute filled quantities.

## Unsupported Boundaries

Phase W deliberately does not support:

- short exposure, reversals, pyramiding, or multiple simultaneous entries;
- missing-entry pre-placement of pending exits;
- `qty + qty_percent` in one `strategy.exit` call;
- multiple pending exits for omitted-quantity full-position exits;
- multiple pending bracket reservations;
- multiple pending trailing reservations;
- reservation behavior outside explicit fixed `qty` or `qty_percent`
  single-trigger exits;
- public pending-order records, reservation fields, remaining-quantity fields,
  percent fields, bracket-leg fields, trailing-state fields, exit-reason
  fields, or a runtime schema bump;
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
inputs, trigger-side metadata, or exit reasons.

CLI, Python, and WASM hosts reuse the shared runtime path. None of the host
bindings implements reservation math, fill precedence, or quantity resolution.

## Fixture Evidence

Runtime fixtures for the Phase W reservation subset:

```text
tests/fixtures/runtime/strategy_exit_reservation_qty_stop_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_limit_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_replacement.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_clamp.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_stop_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_mixed_stop_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_replacement.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_clamp.pine
tests/fixtures/runtime/strategy_exit_reservation_mixed_side_precedence.pine
tests/fixtures/runtime/strategy_exit_reservation_state.pine
tests/fixtures/runtime/strategy_exit_reservation_interactions.pine
```

Existing fixed-quantity, percent-quantity, bracket, and trailing fixtures remain
part of the strategy exit regression set and continue to cover the one-pending
behavior outside the Phase W multiple-reservation subset.

## Host Evidence

Host parity is covered by:

- CLI: `strategy_exit_reservation_fixture_has_host_stable_shape`
- Python: `test_run_script_returns_strategy_exit_reservation_fixture_contract`
- WASM:
  `runs_strategy_exit_reservation_fixture_from_csv_to_public_strategy_json`

All three host tests run
`tests/fixtures/runtime/strategy_exit_reservation_mixed_side_precedence.pine`
and assert the same public reservation result while checking that internal
reservation fields are not exposed.

## Documentation Evidence

The Phase W compatibility claim is synchronized in:

- `tests/fixtures/conformance.tsv`
- `tests/snapshots/matrix.json`
- `README.md`
- `docs/CONFORMANCE.md`
- `docs/EXECUTION_SEMANTICS.md`
- `docs/SEMANTIC_MODEL.md`
- `docs/BUILTIN_SIGNATURES.md`
- `docs/LONG_TERM_EXECUTION_PLAN.md`
- `docs/RELEASE_NOTES.md`

The docs keep `strategy.exit` `partial`, keep broad `strategy.*` unsupported,
and explicitly state the unsupported broker tails.

## Verification

Focused verification passed:

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
python3 -m pip install --force-reinstall dist/pine_compat_runtime-0.1.0-cp310-abi3-manylinux_2_35_x86_64.whl
python3 -m pytest python/tests
git diff --check
```

Release verification passed:

```text
scripts/verify.sh
```

`scripts/verify.sh` covered formatting, clippy with `-D warnings`, workspace
tests, structural guardrails, wasm32 checking for `pine-wasm`, Python wheel
build/install, and Python binding tests.
