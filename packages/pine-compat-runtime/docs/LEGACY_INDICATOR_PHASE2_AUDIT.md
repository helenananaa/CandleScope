# Legacy Indicator Phase 2 Audit

## Outcome

Phase 2 adds the reusable, versioned legacy compatibility front-end without
claiming an executable v1-v4 indicator profile. The production catalog contains
only known focused forms that remain unsupported. A synthetic test catalog
proves that exact function and symbol aliases can pass through semantic
analysis and produce canonical HIR while preserving source evidence.

`study()` remains blocked by the Phase 1 declaration diagnostic. Legacy
strategy declarations and `strategy.*` references remain a hard out-of-scope
stop. Phase 3 is still responsible for admitting `study()` and enabling the
first corpus-selected production alias batch.

## Background Audit

The existing compiler already had the three mechanisms needed for safe scoped
fallback:

- `Analyzer::analyze_program` registers user-defined functions before it
  analyzes statements;
- `ScopeResolver` and span-keyed bindings identify lexical variables and
  parameters at each use;
- lowering retains the source-context id and original AST span for each
  expression.

The compatibility front-end therefore does not rewrite source text and does
not clone or mutate the AST. Text replacement would lose lexical shadowing and
source positions, while a separate AST scope implementation would duplicate
the canonical analyzer's name-resolution rules.

## Implemented Design

### Rule catalog

`pine_sema::legacy` exposes a sorted, version-ranged catalog model:

```text
LegacyRule
  source_name
  canonical_name
  min_version / max_version
  LegacyRuleKind
  LegacyRuleSupport
```

Lookup uses binary partitioning by exact source name, followed by the small set
of same-name version/kind candidates. Catalog validation rejects:

- unsorted rows;
- inverted or modern-version ranges;
- overlapping rows in the same resolution domain;
- supported exact function targets absent from the built-in registry;
- supported exact symbol targets absent from the built-in value/constant
  registries;
- exact rows without canonical targets; and
- focused behavioral rows incorrectly marked for exact lowering.

The production catalog records `study`, legacy `input`/output surfaces,
`security`, `rsi`, `iff`, and `offset` as known focused work. They are not exact
aliases and cannot accidentally lower. The `sma -> ta.sma` and
`tickerid -> syminfo.tickerid` rows used by Phase 2 are synthetic unit-test
rules only; they are not production support claims.

### Resolution order

Exact function aliases are consulted only after canonical method and
user-defined function resolution fail. Exact symbol aliases are consulted only
after the lexical scope fails. Canonical names explicitly written by the user
continue through the ordinary built-in path and do not create translation
records.

The tested fallback order for the Phase 2 surface is:

1. lexical variable or parameter;
2. user/imported function;
3. canonical built-in explicitly named by the source;
4. applicable exact legacy rule;
5. applicable unsupported-known rule;
6. ordinary unknown function/symbol diagnostic.

### Canonical lowering

When an exact rule resolves, the front-end stores a lowering entry keyed by
source-context id and the original callee/value span. Semantic validation uses
the canonical built-in signature. HIR lowering then consumes the stored target
and emits only the canonical call or built-in value name. Runtime built-in
dispatch never receives the legacy surface name.

The translation record retains the source name, canonical name, translation
kind, and original source span. Repeated analysis of a function body can emit
the same logical record more than once internally, so final reports are sorted
by span/name/kind and deduplicated. Emulation records use the same stable
span/name ordering and deduplication rule.

### Focused ownership

Behavioral compatibility remains outside exact-name lowering:

- `legacy::inputs` owns old input signatures and type constants;
- `legacy::outputs` owns styles and transparency;
- `legacy::expressions` owns strict `iff` and `offset` lowering;
- `legacy::security` owns request routing and version lookahead behavior;
- `legacy::calls` owns version-specific overload and argument binding.

Until their execution phases, resolver-visible forms return
`E_UNSUPPORTED_FEATURE` with a focused reason rather than falling through to
`E_UNKNOWN_FUNCTION`.

### Cache invalidation

`CompileCacheKey` now contains `LEGACY_TRANSLATOR_REVISION`. Any semantic change
to the catalog or translator must increment this revision, preventing an
in-memory compile cache from treating results produced by different translator
semantics as equivalent.

## Acceptance Evidence

The Phase 2 semantic tests prove:

| Requirement | Evidence |
| --- | --- |
| Exact function alias reaches canonical HIR | synthetic v4 `sma` lowers to `ta.sma` |
| User function wins | local `sma` produces no translation and no `ta.sma` call |
| Lexical value prevents call fallback | local value named `sma` remains an ordinary invalid call and is not translated |
| Symbol fallback works | synthetic v3 `tickerid` lowers to `syminfo.tickerid` |
| Lexical symbol wins | local `tickerid` produces no translation |
| Version ranges are closed | function alias works only in v1-v4; symbol rule stops after v3 |
| Unsupported-known is focused | `iff` produces `E_UNSUPPORTED_FEATURE` |
| Truly unknown remains unknown | `mystery` produces `E_UNKNOWN_FUNCTION` |
| Modern controls stay strict | v5/v6 `sma` remains unknown |
| Original evidence is retained | translation span equals the source callee span |
| Runtime sees canonical names only | HIR contains `ta.sma`, never legacy `sma` |
| Catalog is validated | production/synthetic registries pass; bad target, overlap, and v5 leak controls fail |
| Reports are deterministic | translation/emulation ordering and deduplication test |
| Cache tracks semantics | compile-cache key revision test |

The unchanged production catalog was also run over the 29-item Phase 0 corpus
twice with a fixed build revision. The reports were byte-for-byte identical:
all 22 eligible indicators parsed, and all 22 still stopped at the intentional
`E_LEGACY_INDICATOR_DECLARATION` gate. This confirms that the Phase 2 framework
does not silently enable a production alias before `study()` admission.

The phase closes only after `scripts/verify.sh`, structure checks, formatting,
Clippy, Rust workspace tests, WASM Node smoke, and installed-wheel Python tests
all pass.

## Deferred Boundary

- No production exact alias is enabled by Phase 2.
- `study()` is not translated and no legacy indicator produces HIR yet.
- No legacy input, output, request, expression, session, or v2 declaration
  behavior is executed.
- No legacy strategy support is planned.
- The public analysis schema remains version 4; this phase fills the already
  reserved translation data model without changing its shape.
