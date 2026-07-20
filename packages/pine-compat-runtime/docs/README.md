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
- [Release Notes](RELEASE_NOTES.md): published release history and accumulated
  changes for the next release.
- [Releasing Binary Wheels](RELEASING.md): GitHub Actions wheel matrix, release
  contract, and application update boundary.

## Status And Roadmap Documents

- [Task Breakdown](TASK_BREAKDOWN.md): high-level baseline and ongoing work
  status.
- [Next Internal Capability Plan](NEXT_INTERNAL_CAPABILITY_PLAN.md): recommended
  order for the next small, fixture-backed slices.
- [Long-Term Execution Plan](LONG_TERM_EXECUTION_PLAN.md): completed phases and
  remaining broad backlog.
- [Pure Internal Roadmap](PURE_INTERNAL_ROADMAP.md): interpreter-internal design
  directions.
- [Legacy Indicator Compatibility Execution Plan](LEGACY_INDICATOR_COMPATIBILITY_EXECUTION_PLAN.md):
  indicator-only v1-v4 compatibility, corpus measurement, versioned lowering,
  execution phases, and release gates; legacy strategies are explicitly out of
  scope.
- [Legacy Indicator Phase 0 Baseline](LEGACY_INDICATOR_PHASE0_BASELINE.md):
  reproducible seed-corpus composition, stage rates, input availability, and
  ranked legacy failure clusters before compiler changes.
- [Legacy Indicator Phase 1 Audit](LEGACY_INDICATOR_PHASE1_AUDIT.md): validated
  dialect selection, script-mode gates, strategy exclusion, and public analysis
  schema synchronization.
- [Legacy Indicator Phase 2 Audit](LEGACY_INDICATOR_PHASE2_AUDIT.md): versioned
  rule catalog, scoped fallback resolution, canonical HIR lowering, deterministic
  reports, and translator cache revision.
- [Legacy Indicator Phase 3 Audit](LEGACY_INDICATOR_PHASE3_AUDIT.md): executable
  v4 `study` declarations, the first corpus-selected exact aliases, paired HIR
  and runtime equivalence, and measured corpus improvement.
- [Legacy Indicator Phase 4 Audit](LEGACY_INDICATOR_PHASE4_AUDIT.md): historical
  v4 input overloads and type constants, canonical callsite/override parity,
  strict modern negative controls, and measured corpus improvement.
- [Legacy Indicator Phase 5 Audit](LEGACY_INDICATOR_PHASE5_AUDIT.md): historical
  v4 output signatures, primitive styles, transparency normalization, expanded
  schema 8 visual data, historical/incremental/realtime parity, and measured
  corpus improvement.
- [Legacy Indicator Phase 6 Audit](LEGACY_INDICATOR_PHASE6_AUDIT.md): strict
  legacy expression evaluation, structural history lowering, type-directed RSI
  overloads, versioned session/logical defaults, and measured v4 compatibility.
- [Legacy Indicator Phase 7 Audit](LEGACY_INDICATOR_PHASE7_AUDIT.md): versioned
  legacy security signatures, provider/chart contracts, gaps/lookahead
  alignment, repaint warnings, cross-host parity, and the declaration-timeframe
  fail-closed boundary.
- [Legacy Indicator Phase 8 Audit](LEGACY_INDICATOR_PHASE8_AUDIT.md): executable
  v3 declarations, pre-v4 names/constants and chart metadata, focused untyped
  `na` inference, canonical runtime equivalence, and measured v3 compatibility.
- [Legacy Indicator Phase 9 Audit](LEGACY_INDICATOR_PHASE9_AUDIT.md): executable
  implicit-v1 and v2 declarations, bounded self/forward declaration graphs,
  historical bool/numeric conversions, canonical runtime equivalence, and the
  fully passing committed legacy seed corpus.
- [Legacy Indicator Phase 10 Audit](LEGACY_INDICATOR_PHASE10_AUDIT.md): required
  v1-v4 runtime and complete analysis goldens across CLI, Python, and WASM,
  expanded parity guardrails, automatic source-version API policy, and the
  explicit migration-preview deferral.
- [Legacy Indicator Phase 11 Release Audit](LEGACY_INDICATOR_PHASE11_RELEASE_AUDIT.md):
  final corpus, execution-mode, MTF, resource, cache, schema, license, and
  release-maturity closeout.
- [Legacy v4 Profile Closeout](LEGACY_INDICATOR_V4_PROFILE_CLOSEOUT.md): v4
  preview evidence and deferred stable gates.
- [Legacy v3 Profile Closeout](LEGACY_INDICATOR_V3_PROFILE_CLOSEOUT.md): v3
  preview evidence and known boundaries.
- [Legacy v2/v1 Profile Closeout](LEGACY_INDICATOR_V2_V1_PROFILE_CLOSEOUT.md):
  experimental declaration, conversion, lookahead, and evidence boundary.
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
