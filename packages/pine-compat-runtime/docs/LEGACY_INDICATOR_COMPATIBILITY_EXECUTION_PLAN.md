# Legacy Indicator Compatibility Execution Plan

Status: proposed primary execution plan for the post-v0.1 compatibility stage.

This plan adds direct execution support for legacy Pine-style **indicators**.
It does not add, widen, migrate, or emulate legacy strategies. The intended
delivery order is v4 first, then v3, then the narrower and higher-risk v2/v1
profiles after their behavior is fixture-backed.

The product outcome is straightforward:

```text
copy a legacy indicator into a host
  -> detect its source dialect
  -> translate supported legacy surface forms internally
  -> preserve version-specific behavior where it affects results
  -> execute through the existing canonical HIR/runtime
  -> report every translation and every remaining unsupported boundary
```

The implementation must not depend on users manually converting source code to
v5 or v6 before execution. A source migration command may be added as a later
convenience, but the direct-run path remains the primary contract.

## Decision Summary

- Scope is legacy indicators only.
- Source versions in scope are v1 through v4. Missing version annotations are
  treated as implicit v1, matching the documented legacy language rule.
- Delivery priority is v4, v3, then v2/v1.
- Existing v5/v6 behavior must remain unchanged.
- Legacy names are normalized before canonical built-in lookup; the runtime
  should not grow a second registry containing duplicate old function names.
- Structural and behavioral differences use explicit semantic lowering or
  runtime dialect rules. They must not be approximated with blind text
  replacement.
- The first implementation target is historical indicator execution. Incremental
  append and realtime behavior become mandatory before a legacy version profile
  is called release-ready.
- Real, legally usable indicator failures drive feature order. Raw counts in
  `tests/fixtures/conformance.tsv` remain useful for feature claims but are not
  a substitute for whole-script success measurements.
- Legacy `strategy()` declarations and `strategy.*` calls are an explicit hard
  stop for this plan. They are classified as excluded scope and never counted
  as failed legacy indicators.

## User-Facing Contract

For an eligible legacy indicator, hosts should be able to call the same analyze,
compile, and run APIs already used for modern scripts. The core automatically
selects a dialect from the source annotation.

The expected modes are:

```text
//@version=4  -> legacy v4 indicator profile
//@version=3  -> legacy v3 indicator profile
//@version=2  -> legacy v2 indicator profile
no directive -> implicit legacy v1 profile
//@version=5  -> existing v5 path, no legacy aliases
//@version=6  -> existing v6 path, no legacy aliases
```

Successful legacy execution may report translations such as:

```text
study                    -> indicator
sma                      -> ta.sma
tickerid                 -> syminfo.tickerid
security                 -> request.security
study.resolution         -> indicator.timeframe execution contract
plot.transp              -> version-preserving output color transparency
```

These examples are categories, not blanket support claims. A translation is
supported only when its accepted arguments, qualifiers, evaluation rules, host
data requirements, runtime behavior, and fixtures all agree.

The analyzer must distinguish four outcomes:

1. `canonical`: the source already uses a supported canonical feature.
2. `translated`: a legacy surface form was converted with preserved semantics.
3. `emulated`: execution retained a documented version-specific behavior.
4. `unsupported`: the feature or behavior cannot yet be executed faithfully.

There is no silent `best effort` outcome. If a translation would produce a
plausible but observably different indicator, analysis fails with a precise
diagnostic.

## Terms

`source version`
: The language version selected by the source directive, or v1 when the
  directive is absent.

`dialect profile`
: The collection of name-resolution, typing, default-argument, evaluation, and
  runtime rules associated with a source version.

`canonical feature`
: The existing internal feature name and behavior used by the current semantic
  analyzer and HIR, such as `indicator`, `ta.sma`, or `request.security`.

`legacy translation`
: A source-spanned conversion from a legacy surface form to a canonical feature
  or HIR shape.

`behavior emulation`
: A version-specific execution rule that must remain visible after names have
  been canonicalized, such as v2 `security` lookahead defaults or strict `iff`
  branch evaluation.

`eligible corpus script`
: A script classified as an indicator, legally available for testing, supplied
  with required chart/request data, and not dependent on a feature declared out
  of scope by this plan.

`direct-run success`
: Parse, semantic analysis, HIR lowering, and runtime execution all succeed for
  a fixed input bundle. It does not by itself prove numerical parity.

`parity success`
: Direct-run succeeds and the normalized indicator outputs match an approved
  reference result under the documented comparison rules.

## Hard Scope Boundary

### In Scope

- Detect explicit v1, v2, v3, and v4 annotations.
- Treat a missing version directive as v1.
- Reject invalid or unknown version directives deterministically.
- Parse legacy indicator syntax needed by corpus evidence.
- Translate legacy indicator declarations to the canonical indicator model.
- Translate version-gated built-in functions, variables, constants, parameter
  names, and accepted legacy overloads.
- Preserve supported legacy evaluation and default-value semantics.
- Execute legacy plot, color, level, fill, bar-color, background-color, shape,
  candle/bar, drawing, and alert forms only where the corresponding indicator
  runtime feature is supported or is explicitly added by a legacy slice.
- Support legacy `security()` and declaration-level timeframe behavior through
  the host-neutral request/chart-data boundary when the required semantics and
  provider data are available.
- Add corpus measurement, minimized fixtures, diagnostics, compatibility
  reporting, public schema changes, and host parity tests.
- Add an optional source migration preview after direct execution is stable.

### Explicitly Out of Scope

- Legacy `strategy()` declarations.
- Legacy or modern `strategy.*` order calls in a legacy script.
- Broker emulation, positions, orders, fills, commissions, margin, equity,
  trades, or strategy reports.
- Strategy conversion from v1-v4 to v5/v6.
- Changes under `pine-runtime::strategy` made solely for this plan.
- Counting strategy scripts in legacy indicator compatibility percentages.
- Network fetching from the core runtime.
- Scraping indicator source, protected scripts, private APIs, or market data.
- Claiming complete Pine language compatibility for any version.
- Pixel-identical recreation of a charting UI.
- Automatic conversion of unsupported modern features merely because they
  appear in an old source file.
- Loading unlicensed third-party scripts into the public repository.

### Indicator-Only Admission Rule

The legacy pipeline must classify script mode before general feature analysis:

- `study(...)` is an eligible legacy indicator declaration.
- `indicator(...)` in a v1-v4 source is not silently accepted as a legacy
  declaration; the diagnostic should suggest either `study(...)` or an explicit
  newer source version.
- `strategy(...)` in a v1-v4 source produces a stable legacy-strategy
  out-of-scope diagnostic.
- Any reached or referenced `strategy.*` feature in a legacy indicator produces
  the same out-of-scope classification.
- A source with no recognized indicator declaration remains non-executable and
  receives a declaration diagnostic; it is not silently treated as an
  indicator.

Modern v5/v6 strategies keep their existing independent behavior. This plan
does not remove or modify that current path.

## Current Starting Point

The repository already provides a strong canonical runtime, but it does not yet
provide a systematic legacy dialect layer.

Relevant current behavior:

- `pine-syntax` lexes `//@version=<u16>` into a version token.
- `pine-sema` copies the optional number into the compatibility report and HIR.
- A few runtime rules already branch on the version, such as pre-v6 strict
  logical evaluation and loop-bound differences.
- Built-in lookup is centered on canonical modern names.
- `study`, unqualified legacy TA names, legacy `security`, `iff`, and old output
  parameters are not resolved as one coordinated versioned feature family.
- Unknown legacy names currently become ordinary unknown-function or
  unknown-symbol diagnostics, so the compatibility report can understate the
  real legacy gap.
- The existing `request.security` provider boundary can be reused for part of
  legacy `security`, but only its fixture-backed subset may be claimed.
- The current indicator declaration signature does not by itself provide a
  complete executable `study(resolution=...)` model.
- The existing output runtime already supports canonical colors and many plot
  families, providing a base for version-aware legacy output lowering.

A representative v3 indicator currently reports independent failures for
`study`, `sma`, `tickerid`, `security`, `iff`, and `plot(..., transp=...)`.
That failure shape is the reason this plan introduces a coordinated dialect
layer instead of adding unrelated aliases one by one.

## Version Delivery Policy

Support is delivered in version profiles rather than as one undifferentiated
`legacy=true` switch.

| Profile | Priority | Initial product claim | Main risk |
| --- | --- | --- | --- |
| v4 | 1 | Direct-run preview, then stable indicator subset | Large rename/input/output surface and MTF |
| v3 | 2 | Direct-run preview after v4 is stable | Pre-v4 names, constants, and typing differences |
| v2 | 3 | Experimental until semantic parity gates pass | Lookahead defaults, self/forward references, bool arithmetic |
| v1 | 3 | Implicit-version alias of the verified v1/v2-compatible subset | No annotation, older source shapes, weak type information |

The implementation order does not mean the parser should reject lower versions
until their runtime is ready. Earlier phases should identify them and emit
specific unsupported-profile diagnostics instead of cascading unknown-name
errors.

### v4 First

v4 is the first release target because it is closest to the existing canonical
v5/v6-style runtime. Its highest-value gaps are mostly declaration names,
namespace moves, input forms, output transparency, renamed parameters,
deprecated helpers, and multi-timeframe calls.

### v3 Second

v3 adds the pre-v4 unnamespaced constants and chart metadata variables. Its
ordinary indicator execution model remains close enough to build on the v4
translation framework, but the resolver must account for local-symbol shadowing
before applying aliases.

### v2 and v1 Last

The public migration guide describes v2 as backwards compatible with v1, so the
initial implementation may share one execution profile while retaining the
original source-version value in reports. This simplification is allowed only
for fixture-proven behavior.

v2 introduces materially different behavior that cannot be reduced to renames:

- `security` uses the legacy lookahead-on default.
- self-referenced and forward-referenced declarations may be valid.
- boolean-to-number arithmetic exists in forms rejected by v3 and later.

Those behaviors require dedicated semantic work. They must not be enabled by
loosening the modern resolver or operator checker globally.

## Evidence and Source Policy

Compatibility decisions use the following source order:

1. Public versioned language and migration documentation.
2. Original minimal fixtures written for this repository.
3. User-owned or permissively licensed whole indicators.
4. Deterministic reference outputs supplied by an authorized host.
5. Existing canonical runtime behavior when the older documentation explicitly
   defines it as equivalent.

Useful public references include:

- [Migration guide overview](https://www.tradingview.com/pine-script-docs/migration-guides/overview/)
- [To Pine Script version 2](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-2/)
- [To Pine Script version 3](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-3/)
- [To Pine Script version 4](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-4/)
- [To Pine Script version 5](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/)

Migration documentation is evidence for differences, not permission to copy
implementation code or substantial documentation text. Repository tests and
descriptions must remain original.

## Compatibility Principles

### Preserve the Original Version

Canonical names do not imply canonical modern semantics. The HIR must retain
the source version, and runtime helpers must derive behavior from that version
when a documented difference affects output.

For example:

- Translating `security` to the canonical request subsystem must not erase the
  v2 versus v3 default lookahead difference.
- Translating `iff` to a conditional result must preserve eager evaluation of
  both value arguments.
- Translating `study` to an internal indicator declaration must preserve legacy
  defaults and supported legacy parameter meanings.
- Translating session calls must preserve the source version's default session
  days where that behavior is in the supported profile.

### Canonicalize Once

Legacy surface names should disappear before ordinary built-in lowering. The
runtime executes canonical operations and version behavior flags, not duplicated
legacy built-in dispatch tables.

### Preserve Source Spans

Every translation record, warning, and unsupported diagnostic points to the
original source span. Generated internal expressions may use synthetic spans
for bookkeeping, but user-facing errors must resolve back to the source form
that caused them.

### Respect User Symbols

Legacy alias resolution must not steal names from user code. Resolution order is:

1. lexical locals and parameters;
2. user-defined functions and eligible declarations;
3. imported names where the source version supports them;
4. canonical built-ins explicitly written by the user;
5. version-gated legacy alias catalog;
6. unsupported-known legacy catalog;
7. unknown symbol/function diagnostic.

The exact order must be tested for collisions such as a user-defined `sma`,
`color`, `ticker`, or `n`.

### Fail Closed on Semantic Uncertainty

If documentation and fixtures do not establish a behavior, analysis emits an
unsupported legacy semantic diagnostic. Do not select the newest behavior, the
most visually plausible result, or a host-specific fallback.

### Keep the Core Host-Neutral

Legacy multi-symbol or multi-timeframe features reuse `RequestEnvironment` and
host-provided bars. The core does not discover symbols, download bars, consult
a live clock, or depend on a particular chart application.

### Keep Modern Scripts Strict

Legacy aliases are enabled only for their source-version ranges. A v5 or v6
script using `sma()` must not begin compiling because v4 support was added.
This is a mandatory regression fixture.

## High-Level Architecture

```text
Pine source
  -> lexer/parser
  -> AST with original spans and optional version directive
  -> dialect detection
       source version
       directive origin
       indicator/strategy classification
  -> legacy semantic front-end
       scoped alias resolution
       named-argument mapping
       structural desugaring
       behavior requirement collection
       translation report
  -> existing canonical semantic analyzer
  -> canonical HIR + source version/dialect semantics
  -> existing historical/incremental/realtime runtime
       canonical built-ins
       version-specific behavior policy
       host-provided request/chart data
  -> normalized indicator outputs + compatibility report
```

The legacy front-end belongs primarily in `pine-sema`, not in the host bindings
and not in string preprocessing.

### Why Not Source-to-Source Replacement

Text replacement cannot safely handle:

- lexical shadowing;
- named versus positional arguments;
- source spans after rewriting;
- overload-dependent mappings;
- `iff` eager evaluation;
- legacy `rsi` overload selection;
- v2 self/forward references;
- version-dependent `security` defaults;
- constants whose old raw values were accepted in unique-typed parameters.

An optional migration formatter can be built later from the structured
translation plan. It must not become the compiler implementation.

### Translation Classes

Every legacy rule is assigned one class:

| Class | Example | Implementation owner |
| --- | --- | --- |
| Exact name alias | `sma` to `ta.sma` | `pine-sema::legacy::catalog` |
| Symbol alias | `tickerid` to `syminfo.tickerid` | scoped resolver |
| Constant alias | `red` to `color.red` | scoped resolver/catalog |
| Parameter rename | `resolution` to `timeframe` | legacy call binder |
| Signature reshape | old `input(..., type=...)` | legacy input analyzer/lowerer |
| Expression desugar | `offset(x, n)` to history access | legacy expression lowerer |
| Strict evaluation desugar | `iff(c, a, b)` | HIR lowering with eager temporaries |
| Output adaptation | `transp=` | output-specific legacy lowerer |
| Version default | v2 `security` lookahead | dialect behavior policy |
| Legacy declaration graph | v2 self/forward references | dedicated declaration pass |
| Unsupported known form | unverified legacy overload | precise compatibility diagnostic |

Exact aliases may share a data-driven catalog. Behavioral classes require
focused code and fixtures.

## Dialect Model

Add a closed internal dialect type rather than passing arbitrary `u16` values
through the system unchecked:

```rust
enum PineDialect {
    V1,
    V2,
    V3,
    V4,
    V5,
    V6,
}

enum VersionOrigin {
    ExplicitDirective,
    ImplicitV1,
}
```

The AST may retain the original numeric directive, but semantic entry points
must validate it before analysis.

Derive a compact behavior policy from the dialect:

```rust
struct DialectSemantics {
    strict_logical_operands: bool,
    numeric_to_bool: bool,
    bool_to_numeric_operators: bool,
    bool_can_be_na: bool,
    const_int_division: ConstIntDivision,
    loop_end_evaluation: LoopEndEvaluation,
    security_default_lookahead: LookaheadPolicy,
    default_session_days: SessionDays,
    allows_self_reference: bool,
    allows_forward_reference: bool,
}
```

Only flags supported by fixtures should drive execution. The struct is not a
shortcut for claiming that every historical difference is implemented.
Unsupported required flags remain analysis errors for the affected source.

The HIR may continue storing `language_version`, but runtime code should use one
validated `DialectSemantics` helper instead of scattering numeric comparisons
across unrelated modules.

## Legacy Rule Catalog

The alias catalog should be static, reviewable, version-ranged, and validated
against the canonical built-in registry.

Suggested shape:

```rust
struct LegacyRule {
    source_name: &'static str,
    canonical_name: &'static str,
    min_version: PineDialect,
    max_version: PineDialect,
    kind: LegacyRuleKind,
    support: LegacyRuleSupport,
}
```

Required catalog tests:

- no overlapping rules for the same source name and version unless overload
  dispatch explicitly owns the ambiguity;
- every exact canonical function alias resolves in `PHASE_1_BUILTINS`;
- every canonical symbol/constant alias resolves in the symbol registry;
- unsupported-known rules cannot accidentally lower;
- v5/v6 do not match v1-v4-only rules;
- every supported catalog row has syntax/sema/runtime fixture ownership;
- generated documentation or matrix rows remain stable and sorted.

Do not duplicate a long manual alias list in the runtime, semantic analyzer,
documentation, and tests. One catalog should drive lookup and machine-readable
inventory generation; fixtures still prove behavior independently.

## Intended Module Layout

Keep existing crate ownership and avoid adding a new crate.

```text
crates/pine-syntax/src/
   version.rs                         version token validation helpers if syntax-owned
   lexer.rs                           directive tokenization only
   parser.rs                          legacy syntax parsing and recovery delegation
   ast.rs                             original AST/spans; no runtime policy

crates/pine-sema/src/
   legacy/
      mod.rs                          legacy front-end facade
      dialect.rs                      PineDialect, VersionOrigin, behavior requirements
      catalog.rs                      version-ranged names/constants/parameters
      report.rs                       translations, emulations, migration hints
      declarations.rs                 study and indicator-only mode gate
      resolver.rs                     scoped legacy symbol/function fallback
      calls.rs                        named arguments and legacy overload routing
      expressions.rs                  iff/offset and other structural lowering
      inputs.rs                       old input type constants and signature reshaping
      outputs.rs                      transp/style/output parameter adaptation
      security.rs                     legacy security analysis and canonical request routing
      v2_declarations.rs              self/forward-reference graph, only when activated
   analysis.rs                        validate dialect and invoke legacy facade
   analyzer/                          canonical analysis remains the main path
   lowering/                          consume structured legacy lowering results
   compatibility.rs                   public legacy translation report model

crates/pine-ir/src/
   lib.rs                             source version and only necessary explicit HIR semantics

crates/pine-runtime/src/
   dialect.rs                         validated runtime behavior policy
   builtins/                          canonical built-ins only
   request/                           provider/chart data contracts reused by legacy security
   runtime/                           historical/incremental/realtime orchestration

crates/pine-cli/src/commands/
   analyze.rs                         report legacy details
   run.rs                             existing direct-run path
   corpus.rs                          optional stable corpus command after internal prototype
   migrate.rs                         optional later source migration preview

tests/fixtures/legacy/
   v1/
      syntax/
      sema/
      runtime/
      unsupported/
   v2/
   v3/
   v4/
   cross_version/
   regressions/

scripts/
   analyze_legacy_corpus.py           internal baseline/report prototype
   tests/test_analyze_legacy_corpus.py
```

Production files approaching the repository's structure guardrail should split
by responsibility before the next compatibility family is added. In
particular, do not turn `analyzer/calls.rs`, `lowering/mod.rs`, or
`runtime/historical.rs` into legacy catch-all modules.

## Compatibility Report Contract

The current analysis contract reports language version, executability,
diagnostics, inputs, and supported/unsupported features. Legacy work requires a
structured extension so hosts do not infer translations from human-readable
diagnostic strings.

Proposed analysis shape:

```json
{
  "schemaVersion": 4,
  "languageVersion": 4,
  "languageVersionOrigin": "explicit",
  "dialect": "v4",
  "executable": true,
  "diagnostics": [],
  "inputs": [],
  "compatibility": {
    "supported": [],
    "unsupported": [],
    "legacyTranslations": [
      {
        "sourceFeature": "sma",
        "canonicalFeature": "ta.sma",
        "kind": "exactAlias",
        "span": {"start": 42, "end": 45, "line": 3, "column": 9}
      }
    ],
    "legacyEmulations": [
      {
        "feature": "iff",
        "behavior": "strictBranchEvaluation",
        "span": {"start": 70, "end": 73, "line": 4, "column": 7}
      }
    ]
  }
}
```

Rules:

- `languageVersion` is `1` for implicit v1 sources rather than `null` after the
  new version policy lands.
- `languageVersionOrigin` distinguishes explicit and implicit selection.
- `legacyTranslations` contains only successful structured translations.
- `legacyEmulations` records result-affecting version behavior used by the
  compiled program.
- Unsupported known legacy features appear in `unsupported` and produce an
  error diagnostic.
- Unknown names remain unknown diagnostics, but corpus clustering must keep
  them visible.
- Translation records are deterministic and sorted by source span.
- Duplicate uses may remain separate when their spans differ.
- All Rust, CLI JSON, Python, and WASM projections change together.
- The analysis schema version increments only once for the coordinated public
  change.

Suggested new stable diagnostics:

```text
E_LANGUAGE_VERSION_UNSUPPORTED
E_LEGACY_INDICATOR_DECLARATION
E_LEGACY_STRATEGY_OUT_OF_SCOPE
E_LEGACY_TRANSLATION_UNSAFE
E_LEGACY_SEMANTICS_UNSUPPORTED
E_LEGACY_INPUT_OVERLOAD
E_LEGACY_OUTPUT_OPTION
E_LEGACY_SECURITY_MODE
E_LEGACY_REFERENCE_CYCLE
W_LEGACY_IMPLICIT_V1
W_LEGACY_REPAINTING_LOOKAHEAD
```

Warnings must not substitute for an unsupported error when correctness is
unknown. The v2 lookahead warning is appropriate only after the exact behavior
is implemented and intentionally enabled.

## Corpus and Measurement System

Whole-script evidence is required before feature prioritization.

### Corpus Sources

Allowed corpus inputs:

- original indicators written for this project;
- user-owned indicators supplied for compatibility work;
- permissively licensed indicators with recorded source/license metadata;
- minimized snippets derived from observed failures without retaining protected
  expression logic;
- source-free reference output bundles when the source cannot be committed.

Public repository fixtures follow `COMPATIBILITY_AND_LEGAL.md`. A private local
corpus may contain user-authorized scripts, but reports should identify scripts
by stable opaque id or hash and must not copy source text into logs by default.

### Corpus Manifest

Use a manifest instead of assuming every script shares one bar file:

```text
id
source_path
declared_or_expected_version
chart_bars_path
chart_symbol
chart_timeframe
request_data_manifest
reference_output_path
license_class
expected_scope
notes
```

`expected_scope` is one of:

```text
legacy_indicator
modern_indicator_control
legacy_strategy_excluded
invalid_control
```

Only `legacy_indicator` participates in legacy indicator success rates.

### Pipeline Stages

For every corpus item, record:

```text
discovered
  -> source_read
  -> version_detected
  -> mode_classified
  -> parsed
  -> analyzed
  -> lowered
  -> historical_run
  -> incremental_run
  -> realtime_run
  -> output_compared
```

Each failed stage stores:

- stable diagnostic codes;
- normalized diagnostic fingerprint;
- source version;
- top-level feature/category;
- required host data status;
- whether the failure is known unsupported or unknown;
- first source span only, without source text by default;
- tool/build revision.

### Diagnostic Fingerprints

Cluster failures by structured fields rather than full messages:

```text
stage
diagnostic_code
legacy_source_feature
canonical_candidate
argument_name_or_overload
source_version
```

Line numbers and user identifiers must not fragment equivalent failure
clusters. Human-readable examples can be generated from original minimal
fixtures only.

### Required Metrics

Report by version and corpus family:

- eligible script count;
- parse success count/rate;
- analyze/lower success count/rate;
- historical run success count/rate;
- incremental parity count/rate;
- realtime parity count/rate;
- reference output parity count/rate;
- excluded strategy count;
- missing provider-data count;
- known unsupported count;
- unknown diagnostic count;
- top failure clusters and cumulative coverage;
- median/p95 analysis and runtime cost;
- maximum diagnostics and translation records per script.

Never combine excluded strategies with failed indicators. Never report a single
compatibility percentage without its denominator, version mix, corpus revision,
and stage definition.

### Initial Corpus Gate

Before choosing the first alias batch:

- collect at least 30 eligible v4 indicators if available;
- collect at least 15 eligible v3 indicators if available;
- include ordinary plots, inputs, colors/styles, history, stateful TA calls, and
  multi-timeframe indicators;
- include at least five deliberately invalid controls;
- record whether reference outputs are available;
- publish the baseline report without promising a completion percentage.

If fewer authorized scripts are available, proceed with the available corpus
but report the limitation. Do not fill the gap by scraping public or protected
sources.

## Legacy Difference Inventory

This inventory routes work; it is not a support matrix. Every row remains
unsupported until its phase acceptance criteria pass.

### v4 Surface to Canonical Runtime

High-frequency families:

- `study()` declaration to canonical indicator mode.
- `study` parameter names such as `resolution` and `resolution_gaps`.
- unqualified TA functions and series values to `ta.*`.
- unqualified math functions to `math.*` where the documented mapping and
  canonical implementation exist.
- old `security()` to the request subsystem.
- old `input()` type constants and overloads to `input.*` call shapes.
- removed `iff()` with strict argument evaluation.
- removed `offset()` to history access.
- output `transp` parameters.
- renamed function parameters.
- legacy acceptance of primitive values where later versions require named
  unique constants.
- v4 `rsi` overload behavior.
- v4 session-day defaults.
- old declaration-level timeframe execution.

### v3 Surface to v4/Canonical Runtime

- unqualified color constants to `color.*`.
- old `color(...)` helper to `color.new(...)` where signatures match.
- old input type constants to `input.*` constants/calls.
- unqualified plot style constants to `plot.style_*`.
- unqualified hline style constants to `hline.style_*`.
- unqualified weekday constants to `dayofweek.*`.
- chart timeframe variables such as `period` and `isintraday` to
  `timeframe.*`.
- `interval` to `timeframe.multiplier`.
- `ticker`/`tickerid` variables to `syminfo.*`.
- `n` to `bar_index`.
- untyped `na` declaration forms that v4 later required to be explicitly typed.

### v2/v1 Semantic Surface

- missing directive as v1.
- v1 execution through the fixture-proven v1/v2-compatible profile.
- v2 `security` default lookahead-on behavior.
- v3-and-later lookahead-off default.
- v2 self-referenced series declarations.
- v2 forward-referenced series declarations.
- mutable variables inside `security` expressions.
- v2 boolean arithmetic and conversions.
- numeric-to-bool conversion retained in versions where documented.
- cycle detection and initialization ordering.

## Phase Overview

| Phase | Goal | First version unlocked |
| --- | --- | --- |
| 0 | Freeze scope and build corpus baseline | none |
| 1 | Validate versions and expose legacy reports | diagnostics only |
| 2 | Build the versioned compatibility front-end | framework only |
| 3 | Support v4 declaration and high-frequency aliases | v4 compile subset |
| 4 | Support legacy inputs, constants, and named arguments | broader v4 compile |
| 5 | Support legacy outputs, styles, and transparency | visual v4 subset |
| 6 | Preserve `iff`, `offset`, overload, and session semantics | v4 semantic subset |
| 7 | Execute legacy `security` and declaration timeframes | v4 MTF subset |
| 8 | Add v3 symbol/constant/type compatibility | v3 subset |
| 9 | Add v2/v1 declaration and conversion semantics | v2/v1 experimental |
| 10 | Synchronize hosts and optional migration preview | public integration |
| 11 | Stabilize, audit, and release | versioned claims |

Each phase is independently mergeable. The workspace must stay shippable after
every slice.

## Phase 0: Scope Lock and Real-Indicator Baseline

Goal: replace anecdotal failures with a repeatable indicator-only baseline.

### Tasks

- Add this plan and link it from `docs/README.md`.
- Record the exact strategy exclusion in the corpus classifier.
- Define the corpus manifest and report schema.
- Implement an internal read-only corpus analyzer around existing parse,
  analyze, and run entry points.
- Ensure the analyzer never writes source into reports unless an explicit
  local debug flag is supplied.
- Add hashes/build revision so reports are reproducible.
- Collect authorized v4 and v3 indicators.
- Run the current baseline and rank diagnostic clusters.
- Minimize at least one original regression fixture for each of the top ten
  clusters.
- Record provider-data availability separately from compiler failures.
- Store the baseline report under `data/` only if repository policy and source
  privacy allow it; otherwise store a redacted summary in `docs/` and keep raw
  reports local.

### Deliverables

- corpus manifest format;
- corpus analysis script and tests;
- redacted baseline summary;
- top failure cluster table;
- first minimized legacy fixtures;
- no compiler behavior changes yet.

### Acceptance Criteria

- Strategy scripts are classified as `legacy_strategy_excluded`.
- Missing source, bars, request data, and reference outputs are separate states.
- The same corpus and build produce byte-for-byte stable JSON apart from an
  explicitly excluded timestamp field; preferably omit timestamps entirely.
- Reports contain no source text by default.
- The top failure clusters are actionable feature categories rather than raw
  unique error messages.
- `scripts/verify.sh` remains green.

### Suggested Commits

1. `Document legacy indicator corpus contract`
2. `Add legacy corpus analyzer`
3. `Record legacy indicator baseline`

## Phase 1: Version Policy, Mode Gate, and Public Diagnostics

Goal: make version and script-mode classification explicit before aliases are
implemented.

### Tasks

- Add the closed `PineDialect` model.
- Convert missing directives to source version v1 with `VersionOrigin::ImplicitV1`.
- Reject version 0, versions above the supported language range, duplicate
  directives, and conflicting root/module versions with stable diagnostics.
- Decide and fixture whether whitespace or placement variants of the legacy
  directive are accepted; do not widen by accident.
- Detect `study`, `indicator`, `strategy`, and missing declaration forms before
  cascading function diagnostics.
- Add the legacy strategy out-of-scope gate without changing the modern v5/v6
  strategy path.
- Add legacy translation/emulation fields to the internal compatibility model.
- Bump public analysis schema once and update CLI JSON, Python, WASM, tests, and
  docs together.
- Update `DIAGNOSTIC_CODES.md`.
- Add v5/v6 controls proving no legacy aliases are active.

### Acceptance Criteria

- No directive reports language version 1 and origin `implicit`.
- Explicit v1-v6 directives report the correct validated dialect.
- Invalid versions fail before ordinary semantic analysis.
- v1-v4 `strategy()` reports one clear out-of-scope error without entering the
  broker path.
- v5/v6 strategy and indicator fixtures are unchanged except for the intended
  additive schema fields.
- All public hosts expose equivalent version/origin/legacy report data.
- Schema snapshots are updated in one coordinated change.

### Suggested Commits

1. `Validate Pine language versions`
2. `Gate legacy scripts to indicator mode`
3. `Expose legacy compatibility reports`

## Phase 2: Versioned Legacy Compatibility Front-End

Goal: add the reusable framework before landing a large alias table.

### Tasks

- Add `pine-sema::legacy` with dialect, catalog, resolver, report, and focused
  lowering modules.
- Invoke the legacy facade after module/source validation but before canonical
  call and symbol failure paths.
- Preserve original spans and names in translation records.
- Implement scoped fallback resolution after user declarations.
- Add version-ranged exact alias rules.
- Add unsupported-known rules for recognized legacy features not yet executed.
- Ensure canonical lowering receives canonical names.
- Add translator revision to compile-cache keys or invalidate cache entries when
  the translation catalog/semantics changes.
- Add deterministic ordering and deduplication rules for reports.
- Add catalog validation tests against built-ins and symbols.
- Keep request, input, output, and v2 structural work delegated to specialized
  modules rather than the exact-alias path.

### Acceptance Criteria

- A synthetic exact alias can pass through analysis and lower to the same HIR
  operation as its canonical counterpart.
- A user-defined function with the same name wins over the alias.
- An unsupported-known legacy name produces `E_UNSUPPORTED_FEATURE` or the new
  focused legacy diagnostic, not `E_UNKNOWN_FUNCTION`.
- A truly unknown name remains unknown.
- Translation records use original source spans.
- v5/v6 negative controls reject legacy-only names.
- No legacy name reaches runtime built-in dispatch.

### Suggested Commits

1. `Add versioned legacy rule catalog`
2. `Resolve legacy aliases after user symbols`
3. `Lower legacy aliases to canonical HIR`

## Phase 3: v4 Declaration and High-Frequency Built-In Aliases

Goal: compile and run ordinary single-timeframe v4 indicators using modern
canonical implementations.

### Initial Scope

- `study(...)` without declaration-level timeframe override.
- `title`, `shorttitle`, `overlay`, `format`, `precision`, `scale`,
  `max_bars_back`, and supported drawing-count parameters when they map to the
  current indicator contract.
- Corpus-ranked unqualified TA functions whose canonical `ta.*` signatures are
  already executable.
- Corpus-ranked unqualified TA series variables whose canonical values exist.
- Corpus-ranked unqualified math/string helpers with exact documented mappings
  and canonical implementations.

### Tasks

- Implement `study` declaration translation and mode registration.
- Bind positional and named declaration arguments using the v4 signature before
  canonical validation.
- Keep `resolution` and `resolution_gaps` recognized but unsupported until
  Phase 7, so users receive one precise MTF diagnostic.
- Generate the first alias batch from the top corpus clusters.
- For each alias, add paired legacy/canonical fixtures over identical bars.
- Compare normalized HIR or runtime outputs to prove equivalent lowering.
- Record supported legacy feature names separately from canonical supported
  names in reports.
- Add collision fixtures for user-defined functions and variables.
- Add modern negative controls.

### Acceptance Criteria

- Fixture-backed v4 `study` scripts using the first alias batch analyze and run.
- Legacy and canonical paired fixtures produce identical normalized outputs.
- Unsupported `study(resolution=...)` produces one focused diagnostic.
- Declaration metadata matches the current supported canonical subset.
- Unknown or unsupported alias candidates are not silently accepted.
- Corpus reports show the measured effect of the alias batch.

### Feature Selection Rule

Do not implement an entire historical namespace because a migration table lists
it. Select the smallest batch that covers the largest cumulative share of
eligible failures, then carry every selected alias through fixtures, reports,
hosts, and conformance metadata.

### Suggested Commits

1. `Translate legacy study declarations`
2. `Add first v4 TA alias batch`
3. `Add v4 math and string aliases`
4. `Record v4 alias conformance`

## Phase 4: Legacy Inputs, Constants, and Named Arguments

Goal: execute the input surfaces used by real v4 indicators without weakening
modern qualifier checks.

### Input Work

- Recognize legacy `input(defval, title, type, minval, maxval, step, options, ...)`
  forms by their v4 signature.
- Map verified input type constants to canonical `input.*` calls.
- Preserve return kind and qualifier expected by the legacy source.
- Preserve callsite ids so host overrides continue to work.
- Map positional and named arguments before canonical validation.
- Support only fixture-backed combinations of `options`, bounds, step, group,
  inline, tooltip, and confirmation metadata.
- Reject ambiguous overloads with `E_LEGACY_INPUT_OVERLOAD`.
- Keep host-side source inputs within the current supported override boundary.

### Constant and Unique-Argument Work

- Add version-gated legacy constants only where documented and corpus-relevant.
- Handle legacy primitive values accepted for style/lookahead-like parameters
  through parameter-specific conversion, not global integer/string coercion.
- Ensure canonical unique values cannot leak into arithmetic merely because
  their legacy implementation once had a primitive backing value.
- Preserve local variable shadowing over constant aliases.

### Named-Argument Work

- Maintain a versioned parameter-name table.
- Resolve legacy names before duplicate/missing argument checks.
- Reject calls that provide both a legacy and canonical spelling for the same
  logical parameter.
- Keep the original spelling in diagnostics.

### Acceptance Criteria

- Host input metadata and override behavior match paired canonical fixtures.
- Legacy input calls receive stable callsite ids across analyze/compile/run.
- No v5/v6 qualifier or unique-argument rule is widened.
- Ambiguous legacy overloads fail before runtime.
- Corpus improvement is recorded by input family.

### Suggested Commits

1. `Analyze legacy input overloads`
2. `Lower legacy inputs to canonical callsites`
3. `Map versioned constants and parameter names`
4. `Verify legacy input host parity`

## Phase 5: Legacy Indicator Outputs and Transparency

Goal: make compiled legacy indicators produce faithful normalized visual data.

### Initial Output Families

- `plot`
- `plotchar`
- `plotshape`
- `plotarrow`
- `plotbar`
- `plotcandle`
- `hline`
- `fill`
- `bgcolor`
- `barcolor`

Drawing objects and alert forms may use the same versioned resolver when their
canonical feature is already supported, but they do not block the first v4
output milestone unless corpus evidence ranks them highly.

### Transparency Rules

`transp` is not a simple discarded parameter. The output lowerer must define:

- which legacy functions accept it;
- its default per function and source version;
- accepted qualifiers and value range;
- interaction with an omitted color;
- interaction with a color that already has an alpha channel;
- `na` handling;
- whether dynamic transparency is allowed in the selected version/signature;
- normalized color output after clamping/conversion.

Prefer an output-specific canonicalization helper over synthesizing arbitrary
user-visible `color.new` calls. If a synthetic call is used internally, its
callsite/state behavior and span mapping must be proven harmless.

### Style Rules

- Map old plot/hline style constants through the versioned catalog.
- Support legacy primitive style arguments only when the old signature and
  documented value mapping are exact.
- Reject unknown numeric styles rather than defaulting to a line.
- Preserve linewidth, offset, histogram base, join, track-price, editable,
  show-last, and display behavior only for the current fixture-backed subset.

### Acceptance Criteria

- Paired legacy/canonical output fixtures match normalized colors, styles,
  offsets, visibility metadata, and `na` placement.
- Default transparency differences have explicit cross-version fixtures.
- Realtime rollback does not duplicate or retain stale outputs.
- Incremental append matches full historical execution.
- Unsupported legacy output arguments are reported during analysis.

### Suggested Commits

1. `Translate legacy output style constants`
2. `Preserve legacy output transparency`
3. `Verify legacy output historical parity`
4. `Verify legacy output realtime parity`

## Phase 6: Legacy Expression and Default Semantics

Goal: handle result-affecting v4 behavior that cannot be represented by exact
aliases.

### `iff`

`iff(condition, true_value, false_value)` evaluates both value arguments before
selecting its result. Lowering it directly to the ordinary lazy ternary node is
incorrect for stateful calls.

Preferred lowering:

```text
evaluate condition once
evaluate true argument once into a synthetic temporary
evaluate false argument once into a synthetic temporary
select one temporary without reevaluating either branch
```

The lowerer must preserve:

- source evaluation order;
- independent callsite state;
- tuple/scalar restrictions of the selected support slice;
- qualifier/type merging;
- `na` condition behavior;
- local scope and temporary ownership.

### `offset`

Lower fixture-backed `offset(source, bars)` forms to canonical history access.
Validate the legacy argument contract before applying current history-retention
rules. Dynamic offsets remain within existing runtime guards and
`max_bars_back` behavior.

### Legacy `rsi` Overload

Do not route every v4 `rsi(x, y)` to `ta.rsi(source, length)`. Resolve the
deprecated two-series overload by argument types and lower its documented
formula only after qualifier, `na`, zero-denominator, and history behavior are
fixture-backed. Ambiguous cases fail explicitly.

### Session Defaults

Preserve the version-specific default session-day set for supported `time`,
`time_close`, and session-input forms. Do not rewrite user strings in place;
pass an explicit effective session policy into canonical time evaluation.

### Strict Logical Evaluation

Confirm all v1-v5 indicator paths use strict `and`/`or` operand evaluation and
v6 remains lazy. Add stateful TA calls in right operands to cross-version
fixtures.

### Acceptance Criteria

- Stateful `iff` fixtures prove both value arguments advance on every reached
  call.
- Ordinary ternary behavior remains unchanged.
- `offset` matches canonical history results and retention bounds.
- Legacy `rsi` overload selection is type-directed and explicit.
- Session defaults have weekend-sensitive fixtures.
- v6 lazy evaluation and current pre-v6 strict evaluation do not regress.

### Suggested Commits

1. `Lower legacy iff with strict evaluation`
2. `Lower legacy offset to guarded history`
3. `Support fixture-backed v4 rsi overload`
4. `Preserve legacy session defaults`

## Phase 7: Legacy `security` and Declaration-Level Timeframes

Goal: execute the multi-timeframe indicator family through the existing
host-neutral data boundary.

This phase is deliberately separate because a name alias alone would let
scripts compile and then produce missing or wrong data.

### `security` Analysis

- Recognize v1-v4 `security` signatures and named arguments by version.
- Canonicalize symbol and timeframe expressions only after legacy symbol
  aliases resolve.
- Reuse the request-specific semantic path for the expression argument.
- Preserve side-effect restrictions and requested-context isolation.
- Map verified `gaps` and `lookahead` constants/primitive legacy values.
- Reject lower-timeframe or unsupported expression families explicitly.
- Preserve original source spans in provider diagnostics.

### Version Defaults

- v2/v1 profile: lookahead-on behavior where fixture-backed.
- v3/v4 profile: lookahead-off behavior where fixture-backed.
- Gaps/default merge behavior must be explicit per accepted signature.
- A v2 lookahead-on indicator emits a non-error repainting warning once per
  distinct callsite after the behavior is correctly implemented.

Do not enable v2 lookahead-on by reusing the current higher-timeframe
lookahead-off aligner with a renamed enum. It needs its own alignment fixtures
and implementation.

### Provider Contract

The host supplies:

- chart symbol and timeframe;
- chart bars;
- every requested symbol/timeframe bar stream;
- deterministic metadata needed by the selected subset.

Missing provider data remains a stable runtime error. Corpus reports classify
it as `missing_provider_data`, not as compiler incompatibility.

### `study(resolution=...)`

Declaration-level timeframe execution is a program-context feature, not a
normal function call. Define a host-neutral contract before accepting it:

- the requested execution timeframe;
- chart versus execution context metadata;
- provider lookup key;
- whole-program evaluation on execution-context bars;
- alignment of normalized outputs back to chart bars;
- gap behavior;
- realtime forming/confirmed bar behavior;
- cache identity;
- missing-data errors.

Prefer reusing request provider validation and alignment primitives while
keeping a separate program-level execution coordinator. Do not implement
`study(resolution=...)` by wrapping the entire AST in a fake
`request.security` call unless all output and state semantics are proven
equivalent.

### Acceptance Criteria

- Same-context legacy security matches direct canonical expressions.
- Same- and higher-timeframe provider fixtures match approved reference data.
- v2 and v3 default lookahead produce intentionally different cross-version
  snapshots.
- Requested-context stateful callsites remain isolated from chart state.
- Historical, incremental, and realtime request paths agree for supported
  update sequences.
- Missing provider data is stable across Rust, CLI, Python, and WASM.
- `study(resolution=...)` is either fully fixture-backed for its declared subset
  or remains a precise unsupported feature; no partial silent execution.

### Suggested Commits

1. `Analyze legacy security calls`
2. `Route v3 v4 security through request context`
3. `Implement v2 lookahead alignment`
4. `Design indicator execution timeframe context`
5. `Execute legacy study resolution subset`
6. `Verify legacy MTF host parity`

## Phase 8: v3 Name, Constant, and Type Compatibility

Goal: add the high-value pre-v4 surface after the v4 canonicalization path is
stable.

### Name and Constant Tasks

- Add corpus-ranked color constants.
- Add old `color` helper routing.
- Add input type constants.
- Add plot and hline style constants.
- Add weekday constants.
- Add timeframe metadata variables.
- Map `interval`, `ticker`, `tickerid`, and `n`.
- Add remaining v3 unqualified built-in aliases selected by corpus frequency.
- Prove lexical locals and user functions shadow every alias family.

### Untyped `na` Tasks

v3 permits declaration shapes that v4 later required to be explicitly typed.
Support only inference forms whose type can be proven from assignment/use flow
without weakening modern declarations.

Potential approach:

- collect a v3-only declaration constraint;
- infer one stable scalar type from later assignments and consumers;
- reject conflicts, collection/object ambiguity, or unresolved declarations;
- lower to the canonical typed symbol model;
- retain original v3 diagnostics and spans.

Do not globally infer arbitrary `na` declarations for v4-v6.

### Acceptance Criteria

- The v3 quickstart-style MACD family runs using unqualified `ema`, `sma`, and
  color names.
- All selected pre-v4 constants resolve only in v1-v3.
- `n` and chart metadata aliases lose to local declarations.
- Supported untyped-`na` fixtures infer one stable canonical type.
- Ambiguous declarations fail with a focused legacy semantic diagnostic.
- v4-v6 negative controls remain strict.

### Suggested Commits

1. `Add v3 color and style aliases`
2. `Add v3 chart metadata aliases`
3. `Infer fixture-backed v3 na declarations`
4. `Record v3 indicator conformance`

## Phase 9: v2/v1 Declaration Graph and Conversion Semantics

Goal: support the old behaviors that require semantic graph changes without
destabilizing the canonical resolver.

This is the highest-risk phase. Keep it behind an experimental profile until
the full phase gate passes.

### Self-Referenced Declarations

For a form such as:

```pine
s = nz(s[1]) + close
```

the v2-only declaration pass must:

- identify the legal self-history reference;
- create the canonical series symbol before analyzing its initializer;
- distinguish history reads from same-bar value reads;
- infer a stable type/qualifier;
- lower initialization and per-bar assignment correctly;
- retain history and `na` behavior;
- reject unsupported non-history recursion.

Do not model this as `var`; the expression still computes on each bar.

### Forward-Referenced Declarations

Build a v2-only dependency graph for eligible global scalar series
declarations:

- predeclare candidate symbols;
- classify current-bar and historical dependencies;
- topologically order safe dependencies where legacy semantics permit it;
- detect cycles and emit `E_LEGACY_REFERENCE_CYCLE`;
- reject side effects, outputs, collections, drawings, and unsupported UDF
  interactions in the first subset;
- lower back into deterministic canonical statement order.

Do not relax `ScopeResolver` globally.

### Boolean Arithmetic

Implement explicit v2-only operator coercion rules at semantic lowering:

- accept only documented bool-to-number operator contexts;
- define true, false, and any legacy `na` conversion through fixtures;
- preserve qualifiers;
- insert explicit canonical cast nodes or lowered conditional values;
- reject the same code in v3-v6;
- avoid allowing booleans in arbitrary numeric built-in arguments unless the
  legacy signature documents it.

### Numeric-to-Bool

Preserve numeric-to-bool behavior in supported legacy condition contexts, with
explicit fixtures for zero, nonzero, and `na`. Do not change v6 explicit-bool
requirements.

### v1 Profile

Treat missing version as source version v1. Reuse the v2 execution profile only
for behaviors proven backwards compatible. Keep separate fixtures and report
the original version as v1.

### Acceptance Criteria

- Self-history declarations match approved bar-by-bar snapshots.
- Forward-reference fixtures are deterministic and cycle-safe.
- v2 bool arithmetic differs intentionally from v3.
- v1 no-directive and explicit v2 paired fixtures match only where the shared
  profile is claimed.
- Expression/statement lowering budgets still prevent pathological graphs.
- Modern resolver, type, and operator tests remain unchanged.
- No strategy behavior is admitted through the old declaration graph.

### Suggested Commits

1. `Analyze v2 self history declarations`
2. `Lower v2 self references to canonical series`
3. `Resolve fixture-backed v2 forward references`
4. `Add v2 boolean operator coercions`
5. `Enable implicit v1 execution profile`
6. `Audit v2 v1 indicator semantics`

## Phase 10: Host Integration and Optional Migration Preview

Goal: make legacy compatibility equally observable and executable from all
supported hosts.

### Host Parity

Rust, CLI, Python, and WASM must agree on:

- detected version and origin;
- executability;
- translation/emulation records;
- diagnostics;
- input metadata and overrides;
- chart metadata;
- request data keys and errors;
- normalized indicator outputs;
- runtime schema versions.

Add representative v4, v3, and eventually v2/v1 scripts to the required host
parity manifest. Keep strategy scripts out of this legacy parity set.

### API Policy

Direct legacy support should not require a host option when the source version
is authoritative. An optional safety configuration may disable legacy
execution, but it must not change which semantics a legacy version selects.

Potential API addition:

```text
legacyPolicy = auto | reject
```

Do not add `force_v4` or silently reinterpret explicit v5/v6 code as legacy.

### Migration Preview

After direct execution is stable, an optional command may emit a reviewable
modernized source preview:

```text
pine-compat migrate legacy.pine --target-version 6
```

Requirements:

- generated from structured translations, not regex replacement;
- preserves original source by default and writes only to an explicit output;
- emits unresolved semantic warnings;
- refuses unsafe conversions;
- includes no guarantee that formatting/comments are perfectly preserved in
  the first version;
- is not used internally by `analyze`, `compile`, or `run`.

### Acceptance Criteria

- Required legacy parity fixtures match across all hosts.
- Public JSON/Python/WASM schemas are documented and snapshot-tested.
- `legacyPolicy=reject`, if added, reports a focused policy diagnostic.
- Migration preview never overwrites its input implicitly.
- Direct run remains independent of migration output.

### Suggested Commits

1. `Expose legacy reports across hosts`
2. `Add legacy host parity fixtures`
3. `Add safe legacy migration preview`

## Phase 11: Stabilization, Audit, and Release

Goal: close each version profile with evidence-backed claims.

### Stabilization Tasks

- Re-run the full authorized corpus.
- Minimize every new crash, panic, nondeterministic result, and top unknown
  diagnostic.
- Verify analysis/lowering limits on adversarial legacy sources.
- Profile translation cost and runtime memory.
- Verify compile-cache behavior includes dialect/translator identity.
- Run historical versus incremental parity over all executable legacy runtime
  fixtures.
- Run realtime confirmed/forming/rollback parity for release-ready profiles.
- Run request/provider parity for every supported legacy MTF profile.
- Audit all compatibility matrix rows and docs.
- Audit every new public diagnostic and schema field.
- Audit source/license metadata.
- Update README, language scope, architecture, semantic model, execution
  semantics, built-in signatures, conformance docs, diagnostic codes, release
  notes, and host examples.
- Write a dedicated closeout audit per released profile.

### Release Profiles

Release claims should be narrow and versioned, for example:

```text
Legacy v4 indicator compatibility preview:
- study declarations in the documented subset
- fixture-backed legacy built-in aliases and inputs
- fixture-backed outputs and strict iff behavior
- documented security/provider subset
- no legacy strategies
```

Avoid:

```text
supports all v4 scripts
runs all old Pine indicators
full backwards compatibility
```

### Provisional Corpus Gates

Before calling a profile stable rather than preview:

- the corpus composition and revision are frozen for the release candidate;
- at least 50 eligible scripts exist for that profile when authorized samples
  are available;
- parse success is at least 95%;
- analyze/lower success is at least 85%;
- historical run success is at least 80%;
- every successfully executed fixture passes incremental parity;
- every profile claimed for realtime passes its realtime fixture set;
- every script with a reference oracle either passes parity or is explicitly
  removed from the supported profile with a diagnostic;
- no crashes, panics, hangs, or silent unsupported execution occur;
- unknown diagnostic clusters representing at least 2% of eligible scripts are
  either implemented or documented as a release blocker/known gap.

These percentages are provisional product gates, not compatibility claims.
Revisit them after Phase 0 establishes corpus size and representativeness. Do
not lower a gate merely by removing difficult eligible scripts from the
denominator.

### Release Verification

```text
git diff --check
cargo fmt --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
python -m unittest scripts.tests.test_analyze_legacy_corpus
scripts/verify.sh
```

Use the exact repository-supported test invocation if the corpus analyzer test
framework differs when implemented.

### Suggested Commits

1. `Stabilize legacy indicator execution`
2. `Audit legacy v4 indicator compatibility`
3. `Audit legacy v3 indicator compatibility`
4. `Audit experimental v2 v1 indicator compatibility`
5. `Document legacy indicator release boundary`

## Fixture Strategy

Every supported legacy behavior needs at least one positive and one negative
fixture. Result-affecting behavior needs cross-version fixtures.

### Fixture Families

```text
syntax
  valid version directives
  invalid versions
  legacy line wrapping and declaration syntax
  parser recovery

sema
  exact aliases
  shadowing
  legacy named arguments
  overload selection
  unsupported-known features
  strategy exclusion
  type/qualifier differences

runtime
  paired legacy/canonical indicators
  outputs and colors
  stateful iff
  offset/history
  session defaults
  security alignment
  self/forward references
  bool/numeric conversions

realtime
  stateful TA calls
  var/series rollback
  output rollback
  request context updates

cross_version
  v2 versus v3 security lookahead
  v2 versus v3 bool arithmetic
  v3 versus v4 names/constants
  v4 versus v5 input/output behavior
  v5 versus v6 lazy evaluation controls

regressions
  every corpus-derived compiler/runtime failure
```

### Paired Fixture Rule

When a legacy form is intended to be exactly equivalent to a canonical form,
store both scripts and compare normalized results over the same bars. Do not
copy snapshots manually between them.

When semantics intentionally differ by version, store one logical source family
with separate expected snapshots and explain the difference in fixture notes.

### Fixture Metadata

Every non-original fixture records:

- source;
- license;
- modification/minimization status;
- owner/permission class;
- version;
- expected compatibility stage.

Public fixtures should prefer original minimal snippets even when a private
whole script revealed the bug.

## Output Parity Rules

Direct-run success is not enough for result-affecting translations.

### Exact Comparisons

Compare exactly:

- plot/output count and ordering;
- `na` locations;
- bool, int, string, color, style, and id values;
- timestamps;
- alert payloads in the supported indicator subset;
- diagnostic codes and spans;
- translation/emulation records.

### Floating-Point Comparisons

Use a documented absolute and relative tolerance appropriate to the existing
runtime snapshot policy. Compare:

- readiness/warmup boundary exactly;
- `na` versus numeric exactly;
- sign and infinities exactly where accepted;
- finite values with tolerance;
- stateful series across all bars, not only the final value.

Do not hide alignment errors with a loose numeric tolerance.

### Visual Boundary

The core compares normalized visual data, not rendered pixels. Host layout,
font metrics, anti-aliasing, chart scales, and proprietary UI behavior remain
outside this plan.

## Conformance Matrix Policy

The current matrix remains feature-oriented. Add legacy rows or structured
version notes without duplicating every canonical function blindly.

Recommended rows:

```text
legacy.version.v1
legacy.version.v2
legacy.version.v3
legacy.version.v4
legacy.study
legacy.alias.ta
legacy.alias.constants
legacy.input
legacy.output.transp
legacy.iff
legacy.offset
legacy.security
legacy.self_reference
legacy.forward_reference
legacy.bool_numeric
legacy.strategy
```

`legacy.strategy` remains `unsupported` with the indicator-only reason.

Each aggregate row links to an inventory generated from the rule catalog and to
representative fixtures. Canonical feature rows continue describing the exact
runtime implementation used after translation.

Do not mark `legacy.version.v4` as broadly supported solely because several
alias rows pass. Version-profile notes must state the included surface and the
corpus revision used for the release claim.

## Performance and Resource Safety

Legacy compatibility must not weaken existing guards.

### Compile-Time Safety

- Alias lookup should be constant or logarithmic time.
- Translation walks the AST a bounded number of times.
- v2 dependency graphs have explicit node/edge limits.
- Synthetic lowering counts toward existing HIR node and temporary budgets.
- Expression depth and inline-depth limits still apply.
- Diagnostic and translation record counts have deterministic caps with one
  truncation diagnostic.
- Compile-cache keys include source, libraries, dialect, translator revision,
  and behavior-affecting options.

### Runtime Safety

- Existing loop, history, array, matrix, drawing, request, and output limits
  remain active.
- Strict `iff` evaluation cannot bypass callsite or lowering limits.
- v2 forward-reference lowering cannot create runtime recursion.
- Request/provider data remains immutable during one execution.
- Program-level timeframe execution has bounded caches and history.
- Lookahead behavior is deterministic for fixed bar streams.
- No legacy feature can trigger network or filesystem access from core crates.

### Performance Gates

Track at least:

- analysis time versus the canonical equivalent;
- translation record count;
- HIR node/temp growth from structural lowering;
- runtime time and memory versus paired canonical fixtures;
- request cache entries and requested bars;
- v2 dependency graph size.

Investigate a sustained p95 analysis regression greater than 20% on the legacy
corpus or a material regression on modern controls before release. This is a
review trigger, not permission to trade correctness for speed.

## Public API and Schema Discipline

- Make one coordinated analysis schema bump for legacy reporting.
- Avoid a runtime schema bump unless normalized outputs require new fields.
- Preserve existing v5/v6 values and field meanings.
- Add new fields additively where possible.
- Keep Rust types as the source of truth; bindings serialize rather than
  reimplement classification.
- Include legacy report fields in compile-cache results.
- Keep CLI text diagnostics useful, but treat JSON/Python/WASM structures as the
  machine contract.
- Update host parity requirements in the same change as new public fields.

## Legal, Privacy, and Branding Controls

- Use only public documentation as specification evidence.
- Use original, user-owned, or permissively licensed source fixtures.
- Do not scrape script repositories or protected source.
- Do not redistribute a user's private indicator without explicit permission.
- Default corpus logs to opaque ids and hashes.
- Do not store source excerpts in CI artifacts by default.
- Keep market data caller-provided.
- Preserve the project's non-affiliation and clean-room wording.
- Describe compatibility as a tested subset by version and feature.
- Review any external corpus licensing before making a report public.

## Risk Register

### R1: Alias Collisions

Risk: a legacy built-in alias captures a user-defined function or variable.

Control: scoped fallback resolution, collision fixtures, original-span reports.

### R2: Silent Semantic Drift

Risk: a syntactically successful translation changes stateful evaluation,
defaults, qualifiers, or `na` behavior.

Control: translation classes, paired/cross-version fixtures, fail-closed rules.

### R3: MTF/Repainting Errors

Risk: `security` or `study(resolution=...)` aligns bars incorrectly or hides
legacy lookahead behavior.

Control: separate Phase 7, explicit provider contract, timestamp-level parity,
repainting warning only after correct implementation.

### R4: v2 Resolver Contamination

Risk: self/forward-reference support weakens modern name resolution.

Control: a v2-only predeclaration/dependency pass and modern negative controls.

### R5: Compatibility Percentage Gaming

Risk: difficult scripts are reclassified or removed to improve a headline rate.

Control: frozen corpus revisions, explicit denominators, excluded-scope audit,
stage-specific metrics.

### R6: Public Schema Drift

Risk: CLI, Python, and WASM expose different legacy reports.

Control: one Rust model, coordinated schema bump, host parity manifest.

### R7: Protected Source Leakage

Risk: corpus logs or fixtures expose proprietary indicators.

Control: hashes/opaque ids, no source text by default, minimized original
fixtures, license metadata.

### R8: Scope Creep into Strategies

Risk: shared names or request behavior pull broker work into the phase.

Control: hard legacy strategy diagnostic, no strategy runtime changes, excluded
corpus class, review checklist.

### R9: Alias Catalog Drift

Risk: canonical built-ins change without the legacy table or docs changing.

Control: registry validation tests and generated inventory.

### R10: Compile/Runtime Cost

Risk: multiple translation passes or synthetic lowering make large indicators
too expensive.

Control: bounded passes, budgets, compile-cache identity, corpus profiling.

## Review Checklist for Every Slice

- Is the slice indicator-only?
- Which exact source versions activate it?
- Does a user-defined name shadow the legacy alias?
- Is the change an alias, signature reshape, structural lowering, or behavior
  emulation?
- Are original source spans preserved?
- Does canonical HIR retain every result-affecting legacy rule?
- Are unsupported variants rejected during analysis?
- Are paired or cross-version runtime fixtures present?
- Are incremental and realtime paths affected?
- Does the feature require chart/request provider data?
- Are Rust, CLI, Python, and WASM contracts synchronized?
- Did the public schema change?
- Did conformance metadata and docs change with the implementation?
- Are source/license boundaries satisfied?
- Do v5/v6 negative controls prove no accidental widening?
- Does `scripts/verify.sh` pass?

## Definition of Done

The legacy indicator program is complete only when all of the following are
true for every released version profile:

- Version detection and origin are deterministic.
- Legacy strategy sources fail with the explicit out-of-scope diagnostic.
- The supported translation inventory is machine-readable and fixture-backed.
- Every result-affecting legacy difference is either emulated and tested or
  rejected explicitly.
- Whole-script corpus metrics meet the frozen release gates.
- Historical execution is deterministic.
- Incremental append matches full historical execution.
- Realtime execution and rollback match where realtime support is claimed.
- Multi-timeframe execution uses only host-provided deterministic data.
- Reference parity passes for every script included in the supported parity
  subset.
- Modern v5/v6 behavior has not widened or regressed.
- No crashes, panics, hangs, silent fallbacks, or unbounded translation/runtime
  growth remain.
- Compatibility reports and diagnostics are consistent across hosts.
- Conformance, language, semantic, execution, architecture, diagnostic, and
  release documentation match the shipped subset.
- Fixture ownership and privacy have been audited.
- The full release verification gate passes.

## Recommended Commit Sequence

The exact number of commits may change, but keep each one reviewable and
shippable.

1. `Document legacy indicator execution plan`
2. `Add legacy corpus manifest and analyzer`
3. `Record legacy indicator compatibility baseline`
4. `Validate Pine dialect versions`
5. `Gate legacy sources to indicator mode`
6. `Expose legacy translation reports`
7. `Add versioned legacy rule catalog`
8. `Resolve legacy aliases after user symbols`
9. `Translate legacy study declarations`
10. `Add first v4 TA alias batch`
11. `Analyze legacy input overloads`
12. `Lower legacy inputs to canonical callsites`
13. `Translate legacy output styles`
14. `Preserve legacy output transparency`
15. `Lower legacy iff with strict evaluation`
16. `Lower legacy offset to history access`
17. `Preserve v4 overload and session semantics`
18. `Analyze legacy security calls`
19. `Execute v3 v4 security through request context`
20. `Implement fixture-backed v2 lookahead alignment`
21. `Execute legacy indicator timeframe declarations`
22. `Add v3 names and constants`
23. `Infer fixture-backed v3 na declarations`
24. `Analyze v2 self references`
25. `Resolve fixture-backed v2 forward references`
26. `Add v2 boolean conversion semantics`
27. `Enable implicit v1 execution profile`
28. `Synchronize legacy reports across hosts`
29. `Add safe migration preview`
30. `Stabilize legacy indicator execution`
31. `Audit legacy v4 indicator compatibility`
32. `Audit legacy v3 indicator compatibility`
33. `Audit experimental v2 v1 compatibility`
34. `Document legacy indicator release boundary`

## First Execution Slice

Start with this bounded slice after Phase 0 baseline data exists:

```text
v4 indicator-only
  + explicit //@version=4
  + study(...) without resolution/resolution_gaps
  + top corpus-ranked 20 exact TA aliases whose canonical forms already run
  + ordinary input(defval, title) forms already equivalent to canonical input
  + plot without transp
  - security
  - study resolution
  - transp
  - iff/offset
  - legacy rsi series overload
  - strategies
```

This slice proves the architecture, shadowing rules, reporting, paired fixtures,
and modern negative controls before behavioral rewrites begin. The next slice
should be chosen from the updated corpus report, not automatically from the
remaining list.
