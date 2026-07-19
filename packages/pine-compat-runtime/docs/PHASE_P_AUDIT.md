# Phase P Audit: Strategy Broker Structure

Status: closed for structural strategy broker maintenance.

Phase P split the strategy broker internals without changing the Pine
compatibility surface, public runtime schema, host output shapes, or existing
strategy behavior. The baseline remains the Phase G/L/M/N/O fixture-backed
strategy subset recorded in `tests/fixtures/conformance.tsv` and
`docs/PHASE_O_AUDIT.md`.

## Completed Slices

- Slice 0 locked the Phase O baseline, confirmed Phase P as structural
  maintenance, recorded broker line-count pressure, and verified the current
  strategy baseline before moving code.
- Slice 1 moved `crates/pine-runtime/src/strategy/broker.rs` to
  `crates/pine-runtime/src/strategy/broker/mod.rs` without logic changes.
- Slice 2 extracted pending-exit domain types into `broker/exits.rs`.
- Slice 3 moved supported `strategy.exit` placement, replacement, and
  tick-conversion rules into `broker/exits.rs` while keeping the broker facade
  methods unchanged.
- Slice 4 moved close/fill trade construction and position reset behavior into
  `broker/fills.rs`.
- Slice 5 moved equity/profit accounting and read-only strategy state/count
  accessors into `broker/accounting.rs`.
- Slice 6 moved broker-focused unit tests into `broker/tests.rs`.
- Slice 7 ran the public contract regression sweep across CLI snapshots,
  incremental/profile fixtures, WASM strategy tests, and Python bindings.
- Slice 8 selected the next strategy maintenance target as a bracket design
  gate only, keeping combined trigger exits unsupported.
- Slice 9 synchronized architecture, roadmap, and release notes without
  widening conformance.
- Slice 10 closed this audit and ran the full release verification gate.

## Behavior Preservation

Phase P did not add a new strategy compatibility claim.

- `tests/fixtures/conformance.tsv` was not widened.
- Runtime output remains `schemaVersion: 3`.
- Public strategy output remains the existing `orders`, `trades`, `position`,
  `equity`, and `diagnostics` object.
- Python dictionaries and WASM JSON continue to map the shared runtime result.
- The supported `strategy.exit` subset remains stop-only, limit-only,
  profit-only, or loss-only full-position exits for the current one-net-long
  broker model.
- Combined brackets, trailing exits, partial exits, missing-entry
  pre-placement, multiple pending exits, short exposure, pyramiding,
  commission, slippage, margin, strategy alerts, and realtime strategy
  execution remain unsupported.

## Final Module Layout

The final strategy runtime ownership is:

```text
crates/pine-runtime/src/strategy/
   mod.rs
   broker/
      mod.rs
      exits.rs
      fills.rs
      accounting.rs
      tests.rs
```

`BrokerState` remains the public strategy runtime facade exported by
`pine-runtime`. Runtime built-ins continue to dispatch accepted strategy order
calls through broker facade methods. Strategy variable reads continue to use
broker accessors. Historical runtime still evaluates pending exits after script
statements and records equity afterward.

Internal ownership after Phase P:

- `broker/mod.rs`: `BrokerState` fields, constructor, entry handling, pending
  exit evaluation, public result projection, and small shared facade behavior.
- `broker/exits.rs`: pending-exit identity, trigger helpers, exit placement,
  replacement, runtime diagnostics, and profit/loss tick conversion.
- `broker/fills.rs`: `strategy.close` fill behavior, pending-exit fill output,
  cash update, position reset, and position snapshots.
- `broker/accounting.rs`: equity snapshots, open/realized/equity values,
  position accessors, and closed/open trade count accessors.
- `broker/tests.rs`: broker-focused unit tests.

## Verification Evidence

Slice-level verification included:

```text
cargo fmt --check
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy::broker
cargo test -p pine-runtime strategy
cargo test -p pine-runtime strategy_trade_count
cargo test -p pine-runtime strategy_variables
cargo test -p pine-runtime --test incremental
cargo test -p pine-runtime --test profile_fixtures
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test -p pine-cli conformance_metadata_references_existing_fixtures
cargo test -p pine-cli matrix_output_matches_golden_snapshot
cargo test -p pine-wasm strategy
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/*.whl
python3 -m pytest python/tests
git diff --check
```

Closeout verification:

```text
git diff --check
scripts/verify.sh
```

The closeout gate passed on the Phase P closeout workspace.

## Next Strategy Maintenance Target

The next recommended strategy maintenance target is a bracket design gate only.
Combined trigger exits remain unsupported while the project documents:

- same-bar high/low precedence for brackets;
- whether stop/limit and profit/loss pairs are order brackets or mutually
  exclusive replacements;
- how bracket identity interacts with the current one-pending-exit model.

Missing-entry pre-placement, rich reporting metrics, partial exits, pyramiding,
short exposure, and realtime broker rollback remain deferred until separate
larger broker phases are deliberately opened.
