# Legacy Indicator Phase 11 Release Audit

## Outcome

Phase 11 closes the legacy-indicator execution plan with narrow versioned
claims:

| Profile | Release maturity | Fixed eligible corpus | Result |
| --- | --- | ---: | --- |
| Pine v4 indicators | preview | 12 | 100% parse, analyze/lower, historical run |
| Pine v3 indicators | preview | 7 | 100% parse, analyze/lower, historical run |
| Pine v2 indicators | experimental | 2 | 100% parse, analyze/lower, historical run |
| implicit Pine v1 indicators | experimental | 1 | 100% parse, analyze/lower, historical run |

No profile is stable. The per-version corpus counts are all below the
provisional 50-authorized-script stable gate, the corpus is an original small
seed rather than a representative market sample, and no external
reference-output oracle is supplied. The implementation supports the
documented fixture-backed indicator subsets; it does not support all old Pine
indicators or legacy strategies.

## Background And Phase Plan

Phases 0-10 established a frozen corpus, closed dialect/mode selection,
canonical legacy lowering, executable v4/v3/v2/v1 slices, versioned MTF
semantics, and cross-host goldens. Phase 11 did not add another compatibility
feature merely to improve a percentage. It closed the evidence and release
boundary in six steps:

1. inventory every executable legacy runtime fixture and the authorized corpus;
2. freeze preview versus experimental maturity from the documented gates;
3. require batch, incremental, realtime, rollback, and MTF evidence from one
   machine-readable release registry;
4. audit adversarial limits, runtime storage, translation latency, cache
   identity, diagnostics, schemas, and source licenses;
5. rerun the fixed corpus twice and write one closeout per profile;
6. synchronize public docs and run the repository release gate before commit.

Legacy strategies remain outside the plan at every step.

## Frozen Corpus Evidence

The corpus manifest remains 29 rows: 22 eligible legacy indicators, one
excluded legacy strategy, and six controls. It contains 12 v4, 7 v3, 2 v2, and
1 v1 eligible sources. All eligible indicators pass source read, parse,
analysis, lowering, and historical execution. There are:

- zero failed eligible stages;
- zero missing required source/chart/request inputs;
- zero scope mismatches;
- zero known-unsupported or unknown diagnostics in successful eligible rows;
- no crash, panic, hang, or silent executable strategy;
- 22 rows without an external reference output, recorded as not supplied
  rather than a false parity pass.

Two consecutive runs with `buildRevision=phase11-release-candidate` produced
byte-identical JSON. Evidence hashes are:

| Asset | SHA-256 |
| --- | --- |
| corpus manifest | `775dd5361a4cbfff954cacb78dc3b66bcd02d5bd6c6689657b8374b7cab0d879` |
| Phase 11 report | `c41d2ffd8067e55b0af04ea7d818014fee42435b00feb75e9f274c7fde108aa8` |
| corpus analyzer | `742f6c253a7dfa8e2cdc87cb032762666e25e68fe09137753aa948fca8aca143` |

The report excludes source text, source paths, and timestamps. The manifest
license class is `original` for every row.

## Release Registry And Execution Modes

`tests/fixtures/legacy/release_profiles.tsv` is a sorted 15-row registry. It
covers every one of the 12 legacy runtime sources and adds v2, v3, and v4 MTF
corpus rows. Each row pins source version, maturity, runtime/MTF category, bars,
request environment, realtime policy, original provenance, and a 4096 retained
value ceiling. Its SHA-256 is
`0755e8a0a5390e84d898598b0e7bb783efecb930011ed86340adc0fdb5807d2c`.

Every row passes historical batch versus incremental equality and realtime
historical handoff. Fourteen rows pass mutated forming update, replacement
forming update, rollback, and final confirmed equality with batch. The v2
lookahead-on MTF row has the correct separate gate: batch history contains the
documented repaint value, while realtime confirmation remains `na` and cannot
leak future requested data. Every MTF row uses its declared provider/chart
contract. Manifest coverage and duplicate/path/maturity/license drift are
test failures.

## Resource, Performance, Cache, And Limit Audit

`scripts/profile_legacy_release.py` runs every registry row through public CLI
analysis and profiled execution. A five-sample audit on the local debug binary
reported:

- median of per-fixture analysis medians: 2.511 ms;
- maximum per-fixture analysis median: 4.125 ms;
- maximum deterministic retained-value count: 114;
- per-row retained-value ceiling: 4096.

The timing includes process startup and is machine-dependent, so it is an
observation rather than a release gate. The retained count covers series,
rolling/valuewhen/collection, visual-output, and drawing snapshot storage and
is enforced in Rust and checked through CLI profile JSON. The profiler SHA-256
at audit time is
`2ab614a9c38b59741abd8694d834c49c58761d6ec14f8eb3a18641ce4abe8395`.

The compile cache key carries translator revision 8 plus exact root/library
names and text. Exact text includes the version directive or its implicit-v1
absence. Tests prove implicit-v1 and explicit-v2 versions of the same body
create two misses/two entries and then independent hits. Translation changes
must still increment the revision.

The v1/v2 graph now has independent generated tests for the 256-node and
4096-edge limits. Existing controls cover unsafe initializers, forward
statement barriers, current cycles, unstable types, parser expression depth,
semantic call depth, lowering allocations, runtime expression depth, bounded
loops, series retention, strings, and collection/output capacities. Oversize
legacy graphs produce one focused diagnostic and no HIR.

## Diagnostics, Schemas, Matrix, And License Audit

A source-to-document token comparison found 14 emitted legacy diagnostics:
13 `E_LEGACY_*` codes and `W_LEGACY_SECURITY_LOOKAHEAD`. Every code is present
in `docs/DIAGNOSTIC_CODES.md`; there is no source-only or documentation-only
legacy code. Phase 11 adds no public diagnostic or schema field. Public
analysis, runtime, and matrix schemas remain 4, 8, and 2 respectively, with
existing CLI/Python/WASM golden parity.

The compatibility matrix now has a release-execution row referencing the
registry and representative v1-v4/MTF fixtures. Feature rows continue to be
support claims for exact tested behaviors; the enclosing language maturity
remains preview or experimental. All release and corpus source rows are marked
`original`. No third-party source was copied into the release evidence and no
private source text enters reports or logs.

## Documentation Closeout

Phase 11 synchronizes the root README, documentation index, language scope,
architecture, semantic model, execution semantics, built-in binding policy,
conformance policy, diagnostics, release notes, host example wording, and the
three profile closeouts. Optional source migration remains deferred because no
general semantics-preserving converter was proved. Direct execution continues
to use the authoritative source version with no host flag.

## Deferred Stable Gates

Each profile needs a frozen representative authorized corpus of at least 50
eligible scripts before stable can be considered. The documented parse (95%),
analyze/lower (85%), and historical run (80%) thresholds must hold without
removing difficult eligible scripts. All executed fixtures must keep
incremental parity; claimed realtime and request profiles must keep their
specific gates; available external reference oracles must pass; and any unknown
diagnostic cluster at or above 2% must be implemented or declared a blocker.

Until those conditions are met, the only accurate product statement is:

> Pine v4/v3 indicator compatibility previews and experimental Pine v2/v1
> indicator subsets, limited to the documented conformance fixtures; no legacy
> strategies and no full backwards-compatibility claim.

## Verification

Focused Phase 11 tests pass for the 15-row release registry, all execution
modes and providers, resource ceilings, the release profiler, cache identity,
and the independent declaration-edge limit. The complete repository
`scripts/verify.sh` gate also passes after the matrix snapshot refresh. Its
closeout evidence includes:

- 207 CLI tests and 531 WASM tests passing in the workspace run;
- 504 installed-wheel Python tests passing;
- the 15-row release integration tests and both profiler unit tests passing;
- the structure guard checking 300 production Rust source files;
- 729 registered CLI runtime snapshots, with 433 required runtime and five
  required complete legacy-analysis Python/WASM assertions;
- successful wasm32 build, Node smoke test, Python wheel build, reinstall, and
  host test run.

The exact final commands are:

```text
git diff --check
cargo fmt --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
python3 -m unittest scripts/tests/test_analyze_legacy_corpus.py
python3 -m unittest scripts/tests/test_profile_legacy_release.py
scripts/verify.sh
```
