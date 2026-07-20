# Legacy Indicator Phase 9 Audit

## Outcome

Phase 9 makes the fixture-backed Pine v1/v2 indicator subset executable. A
source without a version directive now runs as implicit v1, while explicit v2
uses the same historical declaration, input, output, alias, request, and
runtime surface. The implementation adds a bounded declaration dependency
graph for self-history and forward references, the removed v1/v2 bool-to-number
arithmetic conversion, and the pre-v6 numeric-to-bool condition conversion.

All 22 eligible legacy indicators in the unchanged Phase 0 corpus now parse,
analyze, lower, and complete historical execution: 1 of 1 v1, 2 of 2 v2, 7 of
7 v3, and 12 of 12 v4. This is a result for the committed small corpus, not a
claim that arbitrary Pine v1/v2 scripts are supported. Legacy strategies remain
out of scope and still stop before ordinary semantic analysis.

## Historical Background

The version boundary was checked against TradingView's official
[v1-to-v2 migration guide](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-2/),
[v2-to-v3 migration guide](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-3/),
and current description of
[script structure and version directives](https://www.tradingview.com/pine-script-docs/language/script-structure/).

Those sources establish the Phase 9 rules:

- a source without `//@version` uses Pine v1;
- v2 was backward-compatible with v1 for the fixture-backed surface;
- v2 allowed a variable to refer to itself or to a variable declared later,
  while v3 removed those declaration forms;
- v2 arithmetic implicitly converted bool values to numbers, with `true`
  becoming `1.0` and `false` becoming `0.0`;
- numeric values converted to bool with zero and `na` false and other values
  true; the project scopes that historical conversion to v1-v5 and retains
  v6's bool-only condition rule;
- v2 `security` used lookahead-on by default. Phase 7 already implemented that
  merge rule, so Phase 9 only had to admit the whole v1/v2 indicator program.

The migration guide demonstrates a source conversion, not a safe general
runtime algorithm. Phase 9 therefore implements a bounded, fixture-backed
graph instead of evaluating arbitrary cyclic declarations or repeatedly
executing source until values stabilize.

## Phase Plan And Decisions

The phase used seven gates:

1. establish the official v1/v2 version and conversion boundaries;
2. separate ordinary sequential declarations from declarations that actually
   need legacy graph resolution;
3. predeclare one canonical scalar symbol for each active graph node and
   compute a stable lowering order;
4. lower removed implicit conversions to explicit canonical `float(...)` and
   `bool(...)` HIR nodes;
5. prove batch, incremental, realtime, CLI, Python, and WASM behavior from
   shared fixtures and a host-neutral golden;
6. rerun the unchanged legacy corpus twice and synchronize conformance and
   public documentation;
7. run the repository-wide release gate from a clean build before committing.

No source text is rewritten. Graph dependencies, source bindings, inferred
types, and conversion sites are recorded by source-context/span identity.
Lowering emits only ordinary canonical symbols, history nodes, calls, and
operators. The runtime therefore contains no separate v1/v2 expression parser
or declaration evaluator.

## Bounded Declaration Graph

The graph activates only when a top-level untyped declaration contains a real
self-reference or a reference to a declaration at the same or a later source
position. Ordinary backward-only declarations retain the established
single-pass analysis and source lowering order.

For an active graph:

- the dependency closure is computed over candidate global declarations;
- current-bar and positive-static-history edges are classified separately;
- active scalar symbols are predeclared once, so self-history reads and the
  final declaration write share series identity;
- current-bar forward edges are resolved by a stable topological sort;
- history-only cycles are allowed only when fixed-point analysis infers one
  stable scalar type for every node;
- a current-bar cycle is rejected rather than assigned an arbitrary order;
- the lowering plan changes only the graph declaration positions and retains
  every non-candidate statement in its original relative order.

The hard limits are 256 active nodes and 4096 dependency edges. Candidate
initializers must be side-effect-free scalar expressions. Inputs, outputs,
requests/security, user-defined calls, mutation, tuples, and complex control
flow cannot become graph nodes. A current-bar forward dependency also cannot
cross a non-declaration statement barrier. These restrictions prevent graph
resolution from changing callsite order, output order, request ownership, or
observable side effects.

The focused failure codes are:

| Code | Boundary |
| --- | --- |
| `E_LEGACY_REFERENCE_GRAPH` | duplicate or structurally invalid graph declaration |
| `E_LEGACY_REFERENCE_GRAPH_LIMIT` | more than 256 active nodes or 4096 edges |
| `E_LEGACY_REFERENCE_GRAPH_UNSAFE` | initializer is outside the pure scalar subset |
| `E_LEGACY_FORWARD_REFERENCE_UNSAFE` | current dependency crosses a statement barrier |
| `E_LEGACY_REFERENCE_CYCLE` | current-bar dependency cycle |
| `E_LEGACY_REFERENCE_TYPE` | no one stable scalar type can be inferred |

Each unsupported fixture produces exactly one focused diagnostic and no HIR.
The size-limit test generates a graph above the public node limit without
committing an oversized source fixture.

## Historical Conversion Semantics

In v1/v2 arithmetic operators `+`, `-`, `*`, `/`, and `%`, a bool operand is
analyzed as a float-compatible value. Lowering inserts an explicit canonical
`float(...)` call at the operand site; it does not teach the runtime arithmetic
operators to accept bool globally. The same source remains a type error in
v3-v6.

For v1-v5, numeric and `na` values used by ternary/if/while/switch conditions,
`not`, `and`, or `or` lower through an explicit canonical `bool(...)` call.
Zero and `na` become false; every other numeric value becomes true. Pine v6
keeps strict bool-only analysis. Existing v1-v5 strict `and`/`or` evaluation
also remains intact: conversion does not introduce v6 short-circuit behavior.

Synthetic conversion calls count against lowering limits and receive ordinary
callsite and series identities. Compatibility reports expose
`v1.bool_arithmetic`/`v2.bool_arithmetic` and
`v1.numeric_to_bool` through `v5.numeric_to_bool` emulation records. Exact HIR
tests prove that the inserted nodes are canonical calls rather than hidden
runtime flags.

## v1/v2 Executable Surface

The historical v1/v2 `study` table contains `title`, `shorttitle`, `overlay`,
and `precision`. The focused input and plot families reuse the already verified
pre-v4 historical binders. `sma` and `ema` begin at v1 and lower through the
same canonical `ta.*` implementation used by later legacy versions.

Implicit v1 and explicit v2 versions of the shared `study`/`input`/`sma`/`plot`
fixture produce equivalent normalized HIR and exact runtime values. The larger
v2 core covers self-history, current and historical forward references, bool
arithmetic, numeric/`na` conditions, numeric logical operands, and `not`.

The catalog translator revision is `8`, which isolates stale semantic cache
entries from the new v1/v2 surface. Existing source-symbol precedence and
modern v3-v6 negative controls remain unchanged.

## Runtime, Realtime, And Host Evidence

`tests/fixtures/legacy/v2/runtime/core_legacy.pine` is paired with an explicit
v6 canonical rewrite. Both run on the same committed bars and produce the same
eleven plot arrays and metadata. The v2 program also produces the same results
under historical batch execution, incremental bars, and realtime historical
loading; self-history reads committed prior-bar state rather than an aliased
initializer series.

The primary persisted assets are:

- `tests/fixtures/legacy/v1/runtime/shared_v1.pine`;
- `tests/fixtures/legacy/v2/runtime/shared_v2.pine`;
- `tests/fixtures/legacy/v2/runtime/core_legacy.pine`;
- `tests/fixtures/legacy/v2/runtime/core_canonical.pine`;
- `tests/fixtures/legacy/v2/runtime/core_bars.csv`;
- three focused graph failures under `tests/fixtures/legacy/v2/unsupported`;
- v3 and v6 conversion negative controls;
- `tests/snapshots/runtime_legacy_v2_core.json`.

CLI, Python, and WASM analysis tests assert the executable dialect, conversion
and graph emulation records, and absence of the old declaration admission
failure. Python and WASM consume the CLI-generated runtime golden. The golden
is registered as host-required evidence, so deleting or silently dropping one
host assertion fails the parity guard.

During broad regression, two implementation defects were caught and fixed.
The graph failure short-circuit now reacts only to diagnostics created by graph
preparation, preserving pre-existing modern diagnostics. The conversion
lowering hook also uses one recursive expression frame, retaining support for
the repository's deepest matrix fixtures without increasing their stack
requirement.

## Corpus Effect

The unchanged 29-item Phase 0 manifest was run twice at build revision
`phase9`; the reports were byte-for-byte identical with SHA-256:

```text
9ec2ce471d14e82f639b737c4b581555e37e60f7f911fb602a09cddb20ab4d89
```

The manifest SHA-256 remained:

```text
775dd5361a4cbfff954cacb78dc3b66bcd02d5bd6c6689657b8374b7cab0d879
```

Rates retain the denominator of 22 eligible legacy indicators:

| Stage | Passed | Attempted | Eligible denominator | Rate |
| --- | ---: | ---: | ---: | ---: |
| Parse | 22 | 22 | 22 | 100% |
| Analyze | 22 | 22 | 22 | 100% |
| Lower | 22 | 22 | 22 | 100% |
| Historical run | 22 | 22 | 22 | 100% |

There are no remaining failure clusters, unknown diagnostics,
known-unsupported diagnostics, scope mismatches, or missing required inputs in
the eligible corpus. All five deliberately invalid controls still fail at
their intended stage, the modern control executes, and the legacy strategy is
excluded from the denominator and compiler path.

The corpus still contains only original small project fixtures. Its 100% rate
does not measure the user's full indicator library and must not be used as a
general Pine v1-v4 compatibility percentage. Phase 10 must expand the
authorized corpus and use actual failure frequency to choose any additional
compatibility work.

## Deferred Boundary

- Arbitrary cyclic declaration evaluation, graph nodes with side effects,
  statement-crossing current dependencies, non-scalar graph types, and graphs
  above the public limits are not supported.
- v1/v2 output families beyond the fixture-backed plot subset are not claimed.
- Consumer-only or multi-kind historical type inference is not claimed.
- `study(resolution=...)` remains fail-closed under the whole-program execution
  boundary documented in Phase 7.
- Lower-timeframe requests and requested expressions outside the Phase 7
  provider subset remain unsupported.
- Legacy strategies remain permanently out of scope.
- The corpus analyzer still marks incremental, realtime, and reference-output
  comparison as `notRun`; dedicated runtime tests provide incremental and
  realtime evidence for the Phase 9 core.

## Verification

The phase gate includes formatting, catalog validation, graph and conversion
resource-limit tests, canonical HIR checks, historical/incremental/realtime
runtime equivalence, CLI/WASM host tests, the Python installed-wheel suite,
runtime and matrix goldens, two deterministic corpus runs, and the
repository-wide:

```text
scripts/verify.sh
```

The complete gate passed on 2026-07-19. It included all workspace Rust tests
(including 205 CLI and 528 WASM tests), structural and Clippy guardrails, the
real WASM Node smoke path, a freshly built and reinstalled Python wheel with
501 passing binding tests, and the host parity guard over 727 registered CLI
runtime snapshots and 431 required Python/WASM golden assertions.
