# Legacy Indicator Phase 10 Audit

## Outcome

Phase 10 closes the public host-integration boundary for the released legacy
indicator profiles. Rust/CLI owns the compatibility decisions and golden
generation; Python and WASM now prove that representative v1, v2, v3, and v4
sources expose the same complete analysis reports and normalized runtime
results. The shared analysis set also contains a v2 declaration-cycle failure,
so parity covers a stable negative diagnostic rather than successful scripts
alone.

Legacy execution remains automatic from the validated source version. No host
must opt in, and no host can select different semantics for the same source.
Phase 10 deliberately does not add the optional `legacyPolicy` switch or a
source migration preview. Neither is required for direct execution, and adding
an incomplete converter would create a second, weaker compatibility path.
Legacy strategies remain outside every parity set.

## Background And Existing Baseline

The execution plan requires Rust, CLI, Python, and WASM to agree on version and
origin, executability, translations/emulations, diagnostics, input metadata and
overrides, chart/request contracts, normalized outputs, and schema versions.
Before Phase 10, all hosts already called the same semantic and runtime crates,
and individual tests covered the principal legacy behavior. Runtime parity was
also guarded by CLI-generated goldens.

The audit found two evidence gaps:

- implicit v1 had analysis tests and a Node execution smoke test but no
  dedicated CLI/Python/WASM runtime golden;
- analysis reports were asserted field by field in every host, but there was no
  shared full-report snapshot proving that fields, spans, input metadata,
  translations, emulations, and diagnostics remain identical together.

The v4 input fixture was added to required runtime parity at the same time. It
gives the host baseline a canonical default-output contract next to the
existing host-specific override tests.

## Phase Plan And Decisions

The phase used six gates:

1. inventory existing analysis, runtime, input, chart, request, error, and
   schema coverage in every host;
2. add missing v1 and v4-input runtime goldens through the CLI registry;
3. create a separate CLI-owned analysis snapshot registry for v1-v4;
4. make Python and WASM compare complete reports with those same snapshots;
5. expand the static parity guard so a missing registration, manifest entry, or
   host assertion fails the release gate;
6. document the API and migration decisions before the phase commit.

No semantic or runtime code changes are part of Phase 10. Host adapters remain
projections over one HIR/runtime implementation; the new assets make that
architecture enforceable in CI.

## Runtime Golden Parity

The CLI runtime registry now owns two additional snapshots:

- `runtime_legacy_v1_shared.json`, generated from the implicit-v1 shared
  `study`/`input`/`sma`/`plot` fixture;
- `runtime_legacy_v4_inputs.json`, generated from the historical v4 eleven-input
  fixture using default values.

Both are listed in `scripts/host_parity_required.txt` and asserted by Python
and WASM against the exact CLI-generated JSON. Together with the earlier
required legacy snapshots, the representative set covers:

| Profile | Required runtime evidence |
| --- | --- |
| implicit v1 | shared declaration, input, alias, and plot output |
| v2 | self/forward graph and conversion output |
| v3 | historical names, metadata, input/output, and untyped `na` |
| v4 | inputs, outputs, expressions, strict logical evaluation, session defaults, and same-context security |

All runtime outputs remain public `schemaVersion: 8`. The snapshot guard found
729 registered CLI runtime fixtures and 433 fixtures that deliberately require
both Python and WASM golden assertions at Phase 10 closeout.

## Complete Analysis Report Parity

`crates/pine-cli/src/analysis_snapshots.rs` is the single analysis-golden
registry. It generates these complete public `schemaVersion: 4` reports:

- `analysis_legacy_v1_shared.json`;
- `analysis_legacy_v2_core.json`;
- `analysis_legacy_v2_reference_cycle.json`;
- `analysis_legacy_v3_core.json`;
- `analysis_legacy_v4_inputs.json`.

The four positive profiles jointly cover explicit/implicit origin, dialect,
legacy indicator mode, executability, supported features, translations,
emulations, and eleven canonical input callsites. The v2 negative profile
contains the exact `E_LEGACY_REFERENCE_CYCLE`, source span, non-executable
state, and empty HIR-derived metadata expected from a rejected graph.

Python compares its returned dictionary with each parsed golden. WASM parses
both its JSON and the same golden and compares complete JSON values. This avoids
mistaking object-key serialization order for a schema difference while still
requiring every key and value to match. The CLI continues to assert its own
byte-stable writer output.

`scripts/legacy_analysis_parity_required.txt` is the explicit policy manifest.
The parity guard parses the CLI registry, both required manifests, real Rust
assertion calls, and real Python test assertions. It ignores comments and
string literals. A paired snapshot missing from the manifest, a required
snapshot missing from either host, a duplicate registry entry, or a runtime /
analysis filename collision fails the guard. All five registered analysis
snapshots are required by both hosts.

## Inputs, Chart Context, And Requests

The shared v4 analysis golden preserves all eleven input callsites and
canonical names. The shared runtime golden preserves default outputs and visual
metadata. Focused CLI, Python, and WASM tests additionally resolve callsite ids
from analysis, override `Length`, `Scale`, and `Price`, and produce the same
`[3, 5, 7, 9]` output over the common four-bar fixture. The host transport does
not reinterpret historical input signatures; all overrides target canonical
HIR callsites.

Chart and request contracts retain the Phase 7 evidence:

- CLI, Python, and WASM accept explicit chart symbol/timeframe context;
- all three supply the same `SYMBOL:TIMEFRAME` requested-bar key;
- provider-backed legacy security runs through isolated requested state;
- a missing `NYSE:IBM:5` stream reports the same legacy source span `52..84`
  inside each host's ordinary error wrapper;
- same-context security remains a required cross-host runtime golden.

The v3 runtime golden also exercises chart metadata derived from the supplied
context. No host-specific chart or request field was added.

## API Policy

Direct legacy support requires no option. `analyze`, `compile`, and `run`
validate the directive (or implicit-v1 absence) once, carry that dialect into
HIR, and select the same semantics in every host. Explicit v5/v6 code is never
forced into a legacy profile.

The execution plan describes `legacyPolicy = auto | reject` as a potential
safety option. Phase 10 does not add it because:

- no current user requirement asks hosts to disable otherwise valid legacy
  indicators;
- rejection is not needed to choose safe semantics;
- adding it would widen every compile/analyze/run signature and public error
  contract without improving compatibility;
- legacy strategy sources already have their own mandatory hard stop.

If a future embedding requires policy rejection, it must be one consistent
front-door diagnostic across all hosts. It must not change the selected legacy
semantics or accept a source that `auto` rejects.

## Migration Preview Decision

The optional `pine-compat migrate` preview is not implemented. Direct legacy
execution is independent of source rewriting and already meets the phase goal.
Current structured evidence is sufficient for exact aliases and selected
signature roles, but it does not reconstruct all original trivia, declaration
graphs, `iff` evaluation, v2 conversions, request alignment, or v3 type
inference as safe modern source. Emitting a partially modernized file would
invite users to trust a result whose semantics may differ.

A future migration preview remains possible only as a separate explicit-output
tool. It must consume structured translation/emulation data, preserve its input
by default, refuse every unsafe conversion, and never become an internal step
of analyze/compile/run. No migration command, output file, or formatter path is
claimed by the current conformance matrix.

## Fixture And Guard Evidence

The primary Phase 10 assets are:

- `crates/pine-cli/src/analysis_snapshots.rs`;
- `scripts/legacy_analysis_parity_required.txt`;
- the expanded `scripts/check_host_parity.py` and its unit tests;
- five `analysis_legacy_*.json` snapshots;
- `runtime_legacy_v1_shared.json` and `runtime_legacy_v4_inputs.json`;
- exact Python and WASM analysis/runtime assertions;
- the focused CLI v4 input-override integration test.

The guard reports runtime and analysis totals separately. Runtime goldens may
cover modern indicators and strategies elsewhere in the repository, but the
five-item analysis registry is intentionally legacy-indicator-only. No
strategy source can satisfy or enter the legacy analysis parity manifest.

## Deferred Boundary

- No `legacyPolicy` host option is exposed.
- No source migration command or preview output is exposed.
- Host parity proves the documented representative profiles, not arbitrary
  v1-v4 source compatibility.
- v1/v2 output families and graph shapes outside the Phase 9 subset remain
  unsupported or unclaimed.
- Provider expressions and timeframes outside the Phase 7 subset remain
  unsupported.
- Legacy strategies remain permanently out of scope.

## Verification

The phase gate includes CLI snapshot generation and replay, Python/WASM exact
analysis and runtime comparisons, parity-guard unit tests, v4 input overrides,
chart/request/error regression tests, matrix regeneration, and the full:

```text
scripts/verify.sh
```

The complete gate passed on 2026-07-19. It included all workspace Rust tests
(including 207 CLI and 531 WASM tests), structural and Clippy guardrails, the
real WASM Node smoke path, a freshly built and reinstalled Python wheel with
504 passing binding tests, and the expanded host parity guard over 729
registered CLI runtime snapshots, 433 required runtime golden assertions, and
5 required complete legacy-analysis golden assertions in both Python and WASM.
