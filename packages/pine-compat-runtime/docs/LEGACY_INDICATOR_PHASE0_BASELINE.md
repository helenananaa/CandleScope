# Legacy Indicator Phase 0 Baseline

This record freezes the first reproducible, indicator-only legacy corpus
baseline. It is evidence for prioritization, not a compatibility claim.

## Baseline Identity

The baseline was generated on 2026-07-19 with:

```text
cargo build -p pine-cli
python3 scripts/analyze_legacy_corpus.py \
  --build-revision 364488ae0ceb74c2edce380028ccc2fabba093da \
  --output /tmp/legacy-indicator-phase0.json
```

The deterministic report identity is:

| Field | Value |
| --- | --- |
| Report schema | `1` |
| Analyzer tool version | `1` |
| Compiler build revision | `364488ae0ceb74c2edce380028ccc2fabba093da` |
| Manifest SHA-256 | `775dd5361a4cbfff954cacb78dc3b66bcd02d5bd6c6689657b8374b7cab0d879` |
| Analyzer SHA-256 | `c903f246d75a659413de72978a9c928e6bae163eb68a9d47ba7c65c8c0dfd6b0` |

Two consecutive runs with these inputs produced byte-for-byte identical JSON.
The report contains no timestamp, source path, source text, manifest notes, or
unrecognized user identifiers. The raw JSON remains a local build artifact;
this document is the repository-safe summary.

## Scope And Corpus Composition

All committed corpus sources are original, minimal fixtures written for this
project. No public or protected indicator source was scraped.

| Corpus class | Count | Included in legacy rate |
| --- | ---: | --- |
| Eligible legacy indicators | 22 | Yes |
| Deliberately invalid controls | 5 | No |
| Modern v6 executable control | 1 | No |
| Excluded legacy strategy | 1 | No |
| Total manifest rows | 29 | — |

The eligible denominator contains 12 v4, 7 v3, 2 v2, and 1 implicit-v1
indicator. The fixtures cover declarations, ordinary plots, typed inputs,
colors and styles, stateful TA calls, tuples, legacy state/type behavior,
session defaults, and multi-timeframe requests.

The initial target of 30 v4 and 15 v3 whole indicators was not available from
authorized sources. This baseline therefore proceeds under the plan's
small-corpus exception and must not be presented as representative of the
user's full indicator library. User-owned samples can be supplied through a
private manifest without changing or exposing the analyzer.

`strategy()` is a hard exclusion. The analyzer derives this classification
from source mode before invoking the CLI, so even a manifest scope mistake
cannot place a legacy strategy in the indicator denominator or compiler path.
The committed exclusion control has no scope mismatch.

## Stage Baseline

Rates below always use the 22 eligible legacy indicators as the denominator.

| Stage | Passed | Failed | Not run | Rate over attempted |
| --- | ---: | ---: | ---: | ---: |
| Source read | 22 | 0 | 0 | 100% |
| Parse | 22 | 0 | 0 | 100% |
| Analyze | 0 | 22 | 0 | 0% |
| Lower | 0 | 0 | 22 | N/A |
| Historical run | 0 | 0 | 22 | N/A |
| Incremental run | 0 | 0 | 22 | N/A |
| Realtime run | 0 | 0 | 22 | N/A |
| Reference-output comparison | 0 | 0 | 22 | N/A |

All five invalid controls fail at their intended syntax or semantic stage. The
modern v6 control analyzes and runs successfully. This isolates the 22 legacy
analysis failures from a general CLI or bar-data failure.

No runtime or timing claim is possible yet because no eligible script reaches
lowering. Wall-clock timings are intentionally absent from the deterministic
report. Runtime profiling becomes meaningful only after a legacy slice can
execute.

## External Input Availability

Input availability is recorded before compilation, independently of compiler
diagnostics.

| Input class | Available | Not supplied | Missing |
| --- | ---: | ---: | ---: |
| Source | 22 | 0 | 0 |
| Chart bars | 22 | 0 | 0 |
| Request/provider data | 2 | 20 | 0 |
| Reference output | 0 | 22 | 0 |

The 20 indicators without request data do not require it. No reference output
bundle is currently authorized, so output parity remains unmeasured rather
than failed. Missing source, chart bars, request manifests, request bar files,
and reference outputs have separate machine-readable states and unit tests.

## Top Failure Clusters

Clusters use structured diagnostic fields, omit line numbers from grouping,
and expose only allow-listed legacy subjects. Counts are diagnostic
occurrences, not unique scripts, unless the row says otherwise.

| Rank | Stage | Feature category | Diagnostic / subject | Count | Versions | Canonical candidate |
| ---: | --- | --- | --- | ---: | --- | --- |
| 1 | Analyze | Declaration | `E_UNKNOWN_FUNCTION: study` | 22 | v1-v4 | `indicator` mode |
| 2 | Analyze | Call shape | `E_CALL_ARG_TYPE: plot.series` | 8 | v2-v4 | Resolve upstream legacy value typing |
| 3 | Analyze | TA alias | `E_UNKNOWN_FUNCTION: sma` | 5 | v1, v3, v4 | `ta.sma` |
| 4 | Analyze | TA alias | `E_UNKNOWN_FUNCTION: ema` | 4 | v3, v4 | `ta.ema` |
| 5 | Analyze | Name resolution | `E_UNKNOWN_SYMBOL` | 4 | v2, v4 | Resolve tuple/self-reference cases |
| 6 | Analyze | Request alias | `E_UNKNOWN_FUNCTION: security` | 3 | v2-v4 | `request.security` |
| 7 | Analyze | Input overload | `E_CALL_ARG_NAME: input.type` | 2 | v3, v4 | Typed input call |
| 8 | Analyze | TA alias | `E_UNKNOWN_FUNCTION: change` | 2 | v4 | `ta.change` |
| 9 | Analyze | Color compatibility | `E_UNKNOWN_SYMBOL: red` | 2 | v3 | `color.red` |
| 10 | Analyze | Legacy metadata | `E_UNKNOWN_SYMBOL: tickerid` | 2 | v2, v3 | `syminfo.tickerid` |

The declaration failure affects every eligible script and is the first true
blocker. Several `plot.series` and generic symbol errors are downstream
cascades from unresolved aliases, tuples, or legacy self-reference rules;
their raw rank must not move them ahead of mode/version gating. Each top-ten
cluster is represented by at least one committed original minimized fixture.

## Phase 0 Decision

Phase 0 changes no compiler behavior. The evidence fixes the next ordering:

1. establish closed version and mode classification with stable diagnostics;
2. carry immutable legacy provenance through analysis;
3. unlock v4 `study()` and corpus-ranked exact aliases;
4. address inputs, output options, semantic rewrites, and `security()` only in
   their dedicated phases;
5. preserve v2/v1 semantic work until the v4 and v3 paths are measurable.

The baseline must be regenerated after each compatibility phase with a fixed
build revision. Any denominator, manifest hash, or stage-definition change
requires a new baseline identity rather than silently replacing these figures.
