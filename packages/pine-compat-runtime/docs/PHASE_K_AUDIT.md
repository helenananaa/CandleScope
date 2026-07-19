# Phase K Release Infrastructure Audit

Phase K is closed for the current executable indicator subset. Future work in
this area should be treated as release-contract maintenance unless a later
feature phase changes public output, conformance metadata, or verification
requirements.

## Completed Slices

- Slice 1, public output schema versioning:
  `6c17e2d Add public output schema version`.
  CLI, Python, and WASM machine-readable public outputs expose
  `schemaVersion: 1`.
- Slice 2, shared public output serialization:
  `4b1334c Share runtime output serialization`.
  CLI and WASM runtime JSON use shared runtime serialization helpers, while
  Python tests assert the same public runtime key contract.
- Slice 3, golden JSON snapshots:
  `9bfefa7 Add golden JSON snapshots`.
  Checked-in snapshots cover representative CLI runtime output, matrix JSON,
  and WASM analysis output.
- Slice 4, conformance metadata gate:
  `47833d8 Harden conformance metadata validation`.
  The matrix metadata parser rejects malformed rows, duplicate features, invalid
  statuses, empty or missing fixtures, and status/fixture mismatches.
- Slice 5, release verification entry point:
  `0066f21 Add release verification entry point`.
  `scripts/verify.sh` is the canonical local and CI release gate.
- Slice 6, performance/profile fixture gates:
  `ca9470e Add runtime profile fixture gates`.
  Deterministic profile fixtures cover long TA histories, many stateful
  callsites, array-heavy scripts, and dynamic history bounded by
  `max_bars_back`.
- Slice 7, release documentation and closeout:
  release notes, conformance maintenance rules, this audit, the Phase K
  execution checklist, and the long-term roadmap now agree on the release
  contract.

## Closure Evidence

- Public schema contract:
  `PUBLIC_OUTPUT_SCHEMA_VERSION` is the source of truth for runtime public
  output schema versioning. CLI, Python, and WASM public machine-readable
  outputs are tested for top-level `schemaVersion`.
- Shared runtime output:
  CLI and WASM runtime JSON use shared runtime helpers for normal and profiled
  runtime output. Python keeps explicit dictionary conversion with key-contract
  tests.
- Snapshot coverage:
  `tests/snapshots/` contains strict JSON snapshots for CLI runtime outputs,
  CLI matrix JSON, and WASM analysis JSON. Snapshot refresh commands and review
  rules are documented in `docs/CONFORMANCE.md`.
- Matrix coverage:
  `tests/fixtures/conformance.tsv` is the release matrix source of truth.
  `pine-compat matrix --format json` emits `schemaVersion` and fixture-backed
  `features` entries.
- Verification:
  `scripts/verify.sh` runs Rust formatting, clippy, workspace tests, WASM target
  checking, Python wheel build, wheel reinstall, and Python tests. CI runs this
  same entry point.
- Profile coverage:
  `cargo test -p pine-runtime --test profile_fixtures` is part of the workspace
  test suite and catches severe storage growth for profile-covered runtime
  paths.

## Verification Results

The Phase K closeout verification command was:

```text
scripts/verify.sh
```

It passed on the closeout workspace. This command includes:

- `cargo fmt --check`
- `cargo clippy --workspace --all-targets -- -D warnings`
- `cargo test --workspace`
- `cargo check -p pine-wasm --target wasm32-unknown-unknown`
- `maturin build --manifest-path crates/pine-python/Cargo.toml --out dist`
- `python3 -m pip install --force-reinstall dist/*.whl`
- `python3 -m pytest python/tests`

## Remaining Maintenance Tails

These are not blockers for closing Phase K:

- At Phase K closeout, `schemaVersion` remained `1`; later intentional
  consumer-visible output changes must decide whether to increment it and must
  refresh snapshots.
- Python output conversion is intentionally explicit rather than generated from
  the runtime JSON helper. Keep the key-contract tests in lockstep with any
  shared runtime output change.
- Profile gates use deterministic `RuntimeProfile` storage thresholds rather
  than wall-clock timing. Add a benchmark harness later only when stable timing
  data is needed.
- The compatibility matrix remains only as broad as the checked-in fixture
  metadata. New feature claims must add fixtures and metadata in the same
  change.

## Recommended Next Stage

Start Phase E next if visible Pine feature expansion is the priority. Phase E
should begin with a minimal fixture-backed drawing-object output, then design
mutation, deletion, rollback, limits, snapshots, and schema-version impact
before widening drawing coverage.

Choose Phase F instead only if multi-symbol or multi-timeframe data is the next
product need. Phase F should preserve the Phase K matrix and snapshot rules
before accepting any `request.*` compatibility claim.
