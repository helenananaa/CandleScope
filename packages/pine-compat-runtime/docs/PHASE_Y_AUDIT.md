# Phase Y Strategy Exit Trailing Reservation Audit

Status: closed on 2026-06-02.

Phase Y extends the Phase W/X multiple-reservation model to the supported
trailing-stop exits. The phase keeps the current long-only, one-net-position,
no-pyramiding broker and does not change the public runtime output schema.

## Supported Surface

The supported Phase Y subset is:

- multiple pending `strategy.exit` records for the current matching long entry
  when each call is a supported single-trigger, one-downside/one-upside bracket,
  or trailing exit with explicit fixed `qty` or explicit `qty_percent`;
- supported trailing forms remain `trail_price + trail_offset` and
  `trail_points + trail_offset`;
- pending exit identity remains `id + from_entry`;
- different identities append pending exits in placement order;
- same-identity calls replace the existing pending exit after releasing the old
  reservation;
- fixed `qty` and `qty_percent` resolve once at placement time to absolute
  reserved close quantities;
- new reservations clamp to remaining unreserved position quantity;
- zero-reservation placements are rejected with strategy diagnostics and leave
  existing pending exits unchanged;
- single-trigger, bracket, and trailing reservations share the same reservation
  pool for the current matching long entry;
- inactive trailing exits activate on a later eligible bar when
  `high >= activation_price` and never fill on the activation bar;
- active trailing exits are downside candidates, fill before same-bar ratchets
  when `low <= active_stop`, and otherwise ratchet upward only;
- same-side touched candidates fill in placement order;
- when downside and upside candidates are both touched on one eligible
  historical bar, downside candidates fill on that bar in placement order and
  opposite-side candidates remain pending if a long position remains;
- if both legs of one bracket are touched on the same eligible historical bar,
  that bracket contributes its downside stop/loss candidate;
- filled exits emit existing `strategy.exit` order events and closed trade
  records with absolute filled quantities.

## Unsupported Boundaries

Phase Y deliberately does not support:

- short exposure, reversals, pyramiding, or multiple simultaneous entries;
- missing-entry pre-placement of pending exits;
- `qty + qty_percent` in one `strategy.exit` call;
- multiple pending exits for omitted-quantity full-position exits;
- omitted-quantity bracket or trailing reservations;
- same-side trigger pairs, 3+ trigger combinations, or invalid trailing
  combinations;
- reservation behavior outside explicit fixed `qty` or `qty_percent`
  single-trigger, bracket, and trailing exits;
- public pending-order records, reservation fields, remaining-quantity fields,
  percent fields, bracket-leg fields, trailing-state fields, activation fields,
  exit-reason fields, or a runtime schema bump;
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
inputs, trailing state, activation metadata, bracket-leg metadata, trigger-side
metadata, or exit reasons.

CLI, Python, and WASM hosts reuse the shared runtime path. None of the host
bindings implements reservation math, trailing activation, ratchet logic, or
fill precedence.

## Fixture Evidence

Runtime fixtures added for the Phase Y trailing reservation subset:

```text
tests/fixtures/runtime/strategy_exit_reservation_qty_trailing_price_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_trailing_points_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_trailing_replacement.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_trailing_clamp.pine
tests/fixtures/runtime/strategy_exit_reservation_trailing_state.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_trailing_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_mixed_trailing_multi.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_trailing_replacement.pine
tests/fixtures/runtime/strategy_exit_reservation_qty_percent_trailing_clamp.pine
tests/fixtures/runtime/strategy_exit_reservation_trailing_single_downside_order.pine
tests/fixtures/runtime/strategy_exit_reservation_trailing_bracket_downside_order.pine
tests/fixtures/runtime/strategy_exit_reservation_trailing_mixed_side_precedence.pine
tests/fixtures/runtime/strategy_exit_reservation_trailing_activation_mixed_fill.pine
tests/fixtures/runtime/strategy_exit_reservation_trailing_replacement_mixed.pine
tests/fixtures/runtime/strategy_exit_reservation_trailing_mixed_state.pine
tests/fixtures/runtime/strategy_exit_reservation_trailing_host_parity.pine
```

Dedicated bars added for Phase Y:

```text
tests/fixtures/runtime/strategy_exit_reservation_trailing_bars.csv
tests/fixtures/runtime/strategy_exit_reservation_trailing_mixed_bars.csv
tests/fixtures/runtime/strategy_exit_reservation_trailing_host_parity_bars.csv
```

The matching runtime snapshots are in `tests/snapshots/` with the same fixture
stems. Existing Phase R/S/U/V/W/X fixtures remain part of the strategy exit
regression set and continue to cover non-reservation, single-trigger
reservation, bracket reservation, and quantity behavior.

## Host Evidence

Host parity is covered by:

- CLI: `strategy_exit_trailing_reservation_fixture_has_host_stable_shape`
- Python:
  `test_run_script_returns_strategy_exit_trailing_reservation_fixture_contract`
- WASM:
  `runs_strategy_exit_trailing_reservation_fixture_from_csv_to_public_strategy_json`

All three host tests run
`tests/fixtures/runtime/strategy_exit_reservation_trailing_host_parity.pine`
with `strategy_exit_reservation_trailing_host_parity_bars.csv` and assert two
public `strategy.exit` events with absolute quantities `0.75` and `1.25`, fill
prices `3.5` and `3.3`, runtime `schemaVersion: 3`, and no public reservation,
pending, `qty_percent`, trailing-state, activation, or exit-reason fields.

## Documentation Evidence

The Phase Y compatibility claim is synchronized in:

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
cargo test -p pine-runtime --test incremental
cargo test -p pine-cli strategy
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
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
git diff --check
scripts/verify.sh
```

`scripts/verify.sh` covered formatting, clippy with `-D warnings`, workspace
tests, structural guardrails, wasm32 checking for `pine-wasm`, Python wheel
build/install, and Python binding tests.
