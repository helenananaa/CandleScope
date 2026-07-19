# Documentation Guide

This directory contains current runtime contracts, active roadmaps, design
gates, and completed phase records. Use the hierarchy below so that an older
plan is not mistaken for a current compatibility claim.

## Source-Of-Truth Order

1. [`tests/fixtures/conformance.tsv`](../tests/fixtures/conformance.tsv), its
   referenced fixtures, and generated snapshots define the executable
   compatibility claims.
2. The [root README](../README.md), semantic and execution documents,
   diagnostic references, and release notes describe the current public
   contract.
3. [Task Breakdown](TASK_BREAKDOWN.md),
   [Next Internal Capability Plan](NEXT_INTERNAL_CAPABILITY_PLAN.md), and
   [Long-Term Execution Plan](LONG_TERM_EXECUTION_PLAN.md) track current
   maintenance and future work.
4. Phase plans, phase audits, design gates, and historical review documents
   record how a slice was designed or closed. They remain useful evidence, but
   their roadmap wording does not override the conformance matrix.

Generate the current compatibility matrix with:

```text
cargo run -p pine-cli -- matrix
cargo run -p pine-cli -- matrix --format json
```

## Current Project Documents

- [Architecture](ARCHITECTURE.md): crate boundaries and host-neutral
  architecture.
- [Language Scope](LANGUAGE_SCOPE.md): supported language shape and explicit
  boundaries.
- [Execution Semantics](EXECUTION_SEMANTICS.md): historical and realtime
  execution behavior.
- [Semantic Model](SEMANTIC_MODEL.md): types, qualifiers, calls, collections,
  and imports.
- [Series Model](SERIES_MODEL.md): history, retention, and series storage
  semantics.
- [Built-In Signatures](BUILTIN_SIGNATURES.md): built-in signatures and
  supported argument subsets.
- [Conformance](CONFORMANCE.md): compatibility matrix policy and fixture
  requirements.
- [Diagnostic Codes](DIAGNOSTIC_CODES.md): stable diagnostic codes.
- [Realtime Model](REALTIME_MODEL.md): forming-bar rollback and intrabar state
  behavior.
- [Release Notes](RELEASE_NOTES.md): accumulated changes for the unreleased
  `0.1.0` line.

## Status And Roadmap Documents

- [Task Breakdown](TASK_BREAKDOWN.md): high-level baseline and ongoing work
  status.
- [Next Internal Capability Plan](NEXT_INTERNAL_CAPABILITY_PLAN.md): recommended
  order for the next small, fixture-backed slices.
- [Long-Term Execution Plan](LONG_TERM_EXECUTION_PLAN.md): completed phases and
  remaining broad backlog.
- [Pure Internal Roadmap](PURE_INTERNAL_ROADMAP.md): interpreter-internal design
  directions.
- [Strategy Internal Gap Audit](STRATEGY_INTERNAL_GAP_AUDIT.md): current
  long-only strategy baseline and deferred broker-model work.
- [Next Language Expansion Playbook](NEXT_LANGUAGE_EXPANSION_PLAYBOOK.md):
  process for selecting a language slice.

## Phase Records And Design Gates

Files named `PHASE_*_EXECUTION_PLAN.md`, `PHASE_*_AUDIT.md`,
`STRATEGY_INTERNAL_STAGE*_PLAN.md`, and
`STRATEGY_INTERNAL_STAGE*_AUDIT.md` are implementation and closeout records.
Files named `PURE_INTERNAL_*_DESIGN.md` are design gates for specific semantic
or broker boundaries.

Consult these records when extending the corresponding subsystem, but confirm
the current supported boundary against
[`tests/fixtures/conformance.tsv`](../tests/fixtures/conformance.tsv) and the
latest audit before changing compatibility claims.

## Release Gate

[`scripts/verify.sh`](../scripts/verify.sh) is the canonical local and CI
release gate. It checks Rust formatting and linting, all workspace tests,
source structure, host parity, the real WASM/Node path, the Python wheel, and
Python binding tests.
