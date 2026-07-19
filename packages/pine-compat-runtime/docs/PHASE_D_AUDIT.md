# Phase D Built-In Coverage Audit

Phase D is closed for the current executable indicator subset. Future built-in
work should be treated as maintenance or as part of a later phase unless it is a
small compatibility fix for an already supported family.

## Closure Evidence

The supported matrix and runtime fixtures now cover the Phase D target areas:

- Core TA windows and oscillators: moving averages, bands/channels, rolling
  statistics, pivots, trend checks, momentum/rate helpers, crosses, occurrence
  helpers, volume-flow variables, and selected tuple-returning TA functions.
- Pure helper families: selected `math.*`, `str.*`, scalar casts, `na`, `nz`,
  and `fixnan`.
- Time and chart metadata: UTC calendar variables/functions, `timestamp`,
  `time_close`, `timeframe.*` helpers, chart timeframe metadata, and
  `barstate.*` runtime state.
- Market and symbol metadata: fixed-default `session.*` and `syminfo.*`
  subsets.
- Global price sources: OHLCV, `time`, `time_close`, `bar_index`, and derived
  sources `hl2`, `hlc3`, `hlcc4`, and `ohlc4`.
- Output/input compatibility: common metadata parameters for existing supported
  inputs and outputs, plus fixture-backed color helpers and display constants.

Use `tests/fixtures/conformance.tsv` as the authoritative feature list. The
compatibility matrix must remain fixture-backed; do not add supported claims
without syntax, semantic, runtime, fixture, docs, and public-surface agreement.

## Known Maintenance Tails

These are not blockers for closing Phase D:

- `ta.vwap` still documents session-derived anchoring as future work.
- `color.*` named constants remain a common registry, not an exhaustive Pine
  color compatibility claim.
- `input.*` and output calls accept a broad metadata subset, but host-side input
  overrides and renderer-facing style semantics remain later work.
- Unsupported platform families such as drawings, `request.*`, strategies,
  alerts, `varip`, libraries, maps, matrices, and user-defined types remain
  intentionally out of Phase D scope.

## Maintenance Rules

- Add new built-ins only when they are small, fixture-backed compatibility
  fixes or when a later phase explicitly needs them.
- Keep unsupported variants diagnostic-only until their semantics are designed.
- Do not widen public output schemas under Phase D maintenance; move that work
  into Phase K or the relevant platform phase.
- Continue to run the full verification gate before publishing compatibility
  claims.

## Recommended Next Stage

Prefer Phase K next if the goal is reliability: strengthen conformance,
golden-result snapshots, CI coverage, and release checks before large runtime
surface changes.

Prefer Phase E next if the goal is visible Pine feature expansion: start with a
minimal `label.new` object output, then design mutation, deletion, rollback,
and limits before moving to `line.*`.
