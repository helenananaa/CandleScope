# Legacy Indicator Compatibility Phase 1 Audit

Date: 2026-07-19

Phase 1 establishes version policy, script-mode admission, and the public
analysis-report shape required by later legacy translation work. It does not
translate `study()`, resolve legacy aliases, execute a v1-v4 indicator, or add
legacy strategy support.

## Background Reviewed

Before implementation, the syntax, semantic, HIR, runtime, CLI, Python, WASM,
fixture, and public-schema paths were traced end to end.

- The lexer already recognized `//@version=<u16>`, but the parser only consumed
  a version token when it happened to be the first parsed token. A later or
  duplicate directive could therefore fall into generic parser recovery.
- Semantic analysis stored an optional raw integer version. A missing directive
  stayed `None`, while existing runtime branches interpreted that state as the
  pre-v6 behavior path.
- Script declarations were discovered during ordinary call analysis. That
  allowed legacy `study()` or `strategy()` sources to accumulate unrelated
  unknown-call and broker diagnostics before their mode was known.
- `CompatibilityReport` exposed only the raw language version plus canonical
  supported and unsupported features.
- CLI analysis was text-only. Python and WASM manually projected their own
  analysis objects, and the analysis schema constant was owned by the runtime
  output model even though it did not describe runtime output.
- The repository contained modern fixtures and inline unit-test sources that
  omitted a directive because the old analyzer treated omission like the
  existing pre-v6 path. Those tests had to be made explicit without changing
  the new production rule that omission means v1.

## Implemented Policy

### Closed dialect and version origin

`pine-sema::PineDialect` is a closed enum for v1 through v6. The validated
selection records both the raw version and one of these public origins:

- `explicit` for an accepted exact directive;
- `implicit` for a missing directive, which always selects v1.

Version `0`, any value above `6`, and lexically invalid numeric directives stop
before ordinary semantic analysis. Invalid selections retain the raw version
where one was parsed, report no validated dialect, and never produce HIR.

Root and every host-provided library source must select the same validated
dialect. A mismatch produces `E_LANGUAGE_VERSION_CONFLICT` before root
semantic analysis or lowering. Tests that deliberately reuse one logical
modern library fixture from both v5 and v6 roots construct a version-matched
test copy; the production `AnalysisInput` path has no such normalization and is
covered by an explicit mismatch test.

### Directive grammar and placement

Phase 1 preserves the existing lexical surface instead of widening it:

- exact prefix: `//@version=N`;
- leading comments, blank lines, and source indentation before the directive
  are accepted;
- existing whitespace after `=` and trailing whitespace remain accepted;
- `// @version=N` and `//@version =N` remain ordinary comments;
- a second exact directive reports `E_LANGUAGE_VERSION_DUPLICATE`;
- an exact directive after a source statement reports
  `E_LANGUAGE_VERSION_PLACEMENT`.

The parser consumes the invalid later directive after emitting the focused
diagnostic so it does not also generate a generic expression cascade.

### Pre-semantic script-mode gate

The root AST is classified as `legacyIndicator`, `indicator`, `strategy`,
`library`, `missing`, or `mixed` before ordinary call analysis.

For v1-v4:

- one top-level `study()` is recognized as the legacy-indicator declaration,
  but returns `E_LEGACY_INDICATOR_DECLARATION` until Phase 3 implements its
  declaration translation;
- `indicator()`, a missing declaration, or multiple declarations fail with the
  same focused declaration family and a specific reason;
- `strategy()` or any recursively discovered `strategy.*` reference wins over
  declaration errors and returns exactly one
  `E_LEGACY_STRATEGY_OUT_OF_SCOPE` diagnostic plus one unsupported-feature
  record;
- no HIR is produced, so a legacy strategy cannot reach runtime broker logic.

For v5/v6, `indicator()` and `strategy()` continue through the existing modern
analyzer. `study()` remains unknown in modern sources; Phase 1 does not activate
legacy aliases outside their future version ranges.

## Public Analysis Contract

`pine-sema::PUBLIC_ANALYSIS_SCHEMA_VERSION` now owns analysis schema version 4.
CLI JSON, Python dictionaries, and WASM JSON expose equivalent fields:

```json
{
  "schemaVersion": 4,
  "languageVersion": 5,
  "languageVersionOrigin": "explicit",
  "dialect": "v5",
  "scriptMode": "indicator",
  "executable": true,
  "diagnostics": [],
  "inputs": [],
  "compatibility": {
    "supported": [],
    "unsupported": [],
    "legacyTranslations": [],
    "legacyEmulations": []
  }
}
```

The shown arrays are a modern no-legacy-record example. During Phase 1, a
recognized legacy `study()` has its focused declaration diagnostic and
unsupported record, while
translation and emulation arrays remain empty. Later phases can populate those
arrays without another structural redesign.

CLI `analyze` keeps the first two lines of its existing text report and adds
language, mode, and legacy-record counts. `--format text|json` selects the
projection explicitly.

## Fixture and Test Migration

Production behavior has no compatibility switch for unversioned modern code.
Modern `.pine` fixtures that previously omitted a directive were assigned
explicit v5, preserving the old pre-v6 semantics. The only intentionally
unversioned Pine fixture is
`tests/fixtures/legacy/legacy_v1_sma.pine`, which is the implicit-v1 control.

Large in-crate semantic and runtime unit suites use test-only modern-source
helpers to avoid shifting thousands of source-span assertions. These helpers
are unavailable to dependent crates and release builds. Public CLI, Python,
and WASM tests pass explicit modern directives and separately exercise the raw
implicit-v1 contract.

## Stable Diagnostics Added

- `E_LANGUAGE_VERSION_DUPLICATE`
- `E_LANGUAGE_VERSION_PLACEMENT`
- `E_LANGUAGE_VERSION_UNSUPPORTED`
- `E_LANGUAGE_VERSION_CONFLICT`
- `E_LEGACY_INDICATOR_DECLARATION`
- `E_LEGACY_STRATEGY_OUT_OF_SCOPE`

All are documented in `docs/DIAGNOSTIC_CODES.md` and included in the repository
diagnostic-reference guard.

## Acceptance Evidence

| Requirement | Evidence |
| --- | --- |
| Missing directive is implicit v1 | semantic, CLI JSON, Python, and WASM contract tests |
| Explicit v1-v6 select closed dialects | table-driven semantic test |
| Invalid versions stop before ordinary semantic errors | semantic test combines invalid version with an unknown symbol and receives only the version error |
| Duplicate and misplaced directives are focused | parser tests with exact diagnostic sequences |
| Legacy strategy produces one hard stop | semantic and all three public-host report tests |
| Modern v5/v6 paths remain active | indicator/strategy positive controls and modern `study()` negative controls |
| Root/library mismatch is rejected | production `AnalysisInput` mismatch and matching-version controls |
| Public host fields are equivalent | strict JSON/dictionary assertions and schema snapshots |
| Legacy translation/emulation arrays are reserved but empty | CLI, Python, and WASM assertions |
| Corpus remains deterministic and privacy-safe | two byte-identical 29-item reports; all 22 eligible indicators parse and stop in the actionable `legacy_declaration` cluster |

Validation performed for the phase includes:

```text
cargo test -p pine-syntax
cargo test -p pine-sema
cargo test -p pine-runtime
cargo test -p pine-cli --bin pine-compat
cargo test -p pine-wasm --lib
cargo test --workspace --all-targets
```

The final phase gate is `scripts/verify.sh`, which also covers formatting,
Clippy, structure guards, generated WASM/Node behavior, the installed Python
wheel, public snapshots, and corpus determinism.

## Deferred to Phase 2 and Later

- No legacy source name is rewritten yet.
- No `LegacyTranslation` or `LegacyEmulation` record is emitted yet.
- No `study()` source is executable until Phase 3.
- No legacy strategy conversion or execution will be added; it remains an
  explicit project exclusion.
- Version-specific legacy expression, request, session, output, and realtime
  semantics remain assigned to their documented later phases.
