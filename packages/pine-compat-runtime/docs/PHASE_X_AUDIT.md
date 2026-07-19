# Phase X Strategy Exit Bracket Reservation Audit

Status: closed on 2026-06-02.

Phase X extends the Phase W multiple-reservation model from explicit
single-trigger exits to the supported one-downside/one-upside bracket exits.
The phase keeps the current long-only, one-net-position, no-pyramiding broker
and does not change the public runtime output schema.

## Supported Surface

The supported Phase X subset is:

- multiple pending `strategy.exit` records for the current matching long entry
  when each call is either a supported single-trigger exit or a supported
  bracket exit with explicit fixed `qty` or explicit `qty_percent`;
- supported bracket forms remain `stop + limit`, `stop + profit`,
  `loss + limit`, and `loss + profit`;
- pending exit identity remains `id + from_entry`;
- different identities append pending exits in placement order;
- same-identity calls replace the existing pending exit after releasing the old
  reservation;
- fixed `qty` and `qty_percent` resolve once at placement time to absolute
  reserved close quantities;
- new reservations clamp to remaining unreserved position quantity;
- zero-reservation placements are rejected with strategy diagnostics and leave
  existing pending exits unchanged;
- single-trigger reservations and bracket reservations can share the same
  reservation pool for the current matching long entry;
- same-side touched candidates fill in placement order;
- when downside and upside candidates are both touched on one eligible
  historical bar, downside candidates fill on that bar in placement order and
  opposite-side candidates remain pending if a long position remains;
- if both legs of one bracket are touched on the same eligible historical bar,
  that bracket contributes its downside stop/loss candidate;
- filled exits emit existing `strategy.exit` order events and closed trade
  records with absolute filled quantities.

## Unsupported Boundaries

Phase X deliberately does not support:

- short exposure, reversals, pyramiding, or multiple simultaneous entries;
- missing-entry pre-placement of pending exits;
- `qty + qty_percent` in one `strategy.exit` call;
- multiple pending exits for omitted-quantity full-position exits;
- omitted-quantity bracket reservations;
- multiple pending trailing reservations;
- reservation behavior outside explicit fixed `qty` or `qty_percent`
  single-trigger and bracket exits;
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
inputs, bracket-leg metadata, trigger-side metadata, or exit reasons.

CLI, Python, and WASM hosts reuse the shared runtime path. None of the host
bindings implements reservation math, bracket precedence, fill precedence, or
quantity resolution.

## Fixture Evidence

Runtime fixtures added for the Phase X bracket reservation subset:

```text
tests/fixtures/runtime/strategy_exit_reservation_qty_bracket_stop_limit_downside_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_bracket_stop_limit_upside_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_bracket_replacement.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_bracket_clamp.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_bracket_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_mixed_bracket_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_bracket_replacement.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_bracket_clamp.pine
tests/fixtures/runtime/strategy_exit_reservation_bracket_single_downside_precedence.pine
tests/fixtures/runtime/strategy_exit_reservation_bracket_single_upside_order.pine
tests/fixtures/runtime/strategy_exit_reservation_bracket_single_replacement.pine
tests/fixtures/runtime/strategy_exit_reservation_bracket_state.pine
tests/fixtures/runtime/strategy_exit_reservation_bracket_host_parity.pine
```

The matching runtime snapshots are in `tests/snapshots/` with the same fixture
stems. Existing Phase R/S/U/V/W fixtures remain part of the strategy exit
regression set and continue to cover the non-reservation and single-trigger
reservation paths.

## Host Evidence

Host parity is covered by:

- CLI: `strategy_exit_bracket_reservation_fixture_has_host_stable_shape`
- Python:
  `test_run_script_returns_strategy_exit_bracket_reservation_fixture_contract`
- WASM:
  `runs_strategy_exit_bracket_reservation_fixture_from_csv_to_public_strategy_json`

All three host tests run
`tests/fixtures/runtime/strategy_exit_reservation_bracket_host_parity.pine`
and assert two public `strategy.exit` events with absolute quantities `0.5` and
`1`, fill prices `2` and `3`, runtime `schemaVersion: 3`, and no public
reservation or bracket-leg fields.

## Documentation Evidence

The Phase X compatibility claim is synchronized in:

- `tests/fixtures/conformance.tsv`
- `tests/snapshots/matrix.json`
- `README.md`
- `docs/CONFORMANCE.md`
- `docs/EXECUTION_SEMANTICS.md`
- `docs/SEMANTIC_MODEL.md`
- `docs/LONG_TERM_EXECUTION_PLAN.md`
- `docs/RELEASE_NOTES.md`

The docs keep `strategy.exit` `partial`, keep broad `strategy.*` unsupported,
and explicitly state the unsupported broker tails.

## Verification

Focused verification passed:

```text
cargo fmt --check
cargo test -p pine-runtime strategy
cargo test -p pine-runtime --test incremental
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

Canonical release verification passed:

```text
scripts/verify.sh
```

`scripts/verify.sh` covered formatting, clippy with `-D warnings`, workspace
tests, structural guardrails, wasm32 checking for `pine-wasm`, Python wheel
build/install, and Python binding tests.
