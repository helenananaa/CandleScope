# Legacy Pine v3 Indicator Profile Closeout

## Release Decision

The Pine v3 indicator profile closes as **preview**. `//@version=3` sources run
directly only when every used behavior belongs to the documented fixture-backed
subset. Legacy strategy mode remains a hard stop.

The frozen original corpus contains seven eligible v3 indicators. All seven
pass, but the count is below the provisional 50-script stable gate and no
external reference-output oracle is supplied. The preview label is therefore
an evidence boundary, not a known test failure.

## Closed Surface

The profile includes the conformance-listed historical `study`, `input`,
`plot`, and `hline` signatures; selected pre-v4 colors, color helper, style and
weekday constants; chart/timeframe metadata aliases; selected TA aliases; and
focused untyped-`na` inference to one stable later scalar type. User functions
and lexical declarations retain precedence over every fallback name.

`security` uses the v3/v4 historical binder and defaults to lookahead off. The
release registry closes the same-context profile; separate provider tests
cover the focused external same-or-higher-timeframe alignment used by the
shared legacy request implementation. Unsupported requested expressions and
lower timeframes fail closed.

## Execution Evidence

Two v3 release rows cover the paired v3 core and the corpus same-context MTF
source. Both pass semantic v3 admission, batch/incremental equality, realtime
historical handoff, forming replacement/rollback/final confirmation equality,
and their declared chart/request contract. They retain at most 23 values under
the 4096-value ceiling.

On the audit machine their end-to-end CLI analysis medians were approximately
2.305 ms and 3.108 ms. These process-level timings are indicative only. Runtime
storage and execution equality, rather than latency, are deterministic gates.

The complete v3 core runtime/analysis goldens remain identical across CLI,
Python, and WASM. The profile introduces no new public diagnostic or schema
field.

## Corpus Evidence And Boundaries

The fixed v3 result is 7 of 7 for parse, analyze/lower, and historical run,
with zero unknown diagnostics or scope mismatch. All sources are marked
`original`.

The preview does not include all pre-v4 built-ins, all historical overloads,
general untyped-`na` inference, legacy strategies, arbitrary MTF expressions,
lower-timeframe security, or unlisted output/declaration arguments. It cannot
become stable until representative authorized samples reach the stable evidence
gate, difficult inputs stay in the denominator, available reference oracles
pass, and all execution/provider gates continue to hold.
