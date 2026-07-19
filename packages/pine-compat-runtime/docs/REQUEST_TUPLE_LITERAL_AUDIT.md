# Request Tuple Literal Coverage Audit

Status: closed for the current fixture-backed provider `request.security` tuple
literal subset.

This audit closes the recent request tuple-literal maintenance track. It
documents coverage for tuple literals whose elements are already-supported
scalar requested expressions in same-timeframe and higher-timeframe provider
contexts. It does not add request semantics, widen optional parameters, change
alignment rules, change host APIs, or bump the public runtime schema.

## Supported Boundary

The supported boundary is:

- destructuring directly from `request.security(...)` into local variables;
- tuple literals made from supported scalar requested expressions;
- same-timeframe provider requests using `timeframe.period`;
- higher-timeframe provider requests using the default `gaps_off` and
  `lookahead_off` alignment;
- isolated requested-context state for rolling and stateful scalar elements;
- host-provided request bars through the existing Rust, CLI, Python, and WASM
  request-bars contracts.

Covered tuple literal element families include:

- direct sources, arithmetic, ternaries, history references, `na`, and `nz`;
- supported stateless `math.*` calls;
- fixed-mintick `math.round_to_mintick` and rolling `math.sum`;
- supported scalar `ta.*` calls, including rolling, stateful, extrema,
  momentum, dispersion, weighted average, smoothing, regression, percentile,
  pivot, event, cross, and volume-flow helpers;
- length-only extrema overloads such as `ta.highest(2)`, `ta.lowest(2)`,
  `ta.highestbars(2)`, and `ta.lowestbars(2)`.

Provider-backed tuple-returning calls are a separate supported subset when
destructured directly from the request, currently `ta.macd`, `ta.bb`, `ta.kc`,
`ta.supertrend`, `ta.dmi`, and
`ta.vwap(source, anchor, stdev_mult)`.

## Fixture Evidence

`tests/fixtures/request/request_security_host.pine` is the cross-host fixture.
It now contains same-timeframe and higher-timeframe provider tuple literal
groups for the covered scalar families. Recent closeout examples include:

- `[tuple_ta_bbw]` and `[higher_tuple_ta_bbw]`;
- `[tuple_ta_highest_default, tuple_ta_lowest_default]` and the higher
  timeframe pair;
- `[tuple_ta_highestbars_default, tuple_ta_lowestbars_default]` and the higher
  timeframe pair;
- `[tuple_math_sum, tuple_math_mintick]` and
  `[higher_tuple_math_sum, higher_tuple_math_mintick]`.

The fixture has 309 plotted outputs and is intentionally shared by CLI, Python,
and WASM host tests so host surfaces validate the same requested-bar inputs and
runtime output shape.

## Runtime And Sema Evidence

Runtime coverage lives in `crates/pine-runtime/src/tests/request.rs`.
Representative same-timeframe provider tests include:

- `request_security_evaluates_provider_tuple_literal_in_requested_context`
- `request_security_evaluates_provider_tuple_literal_history_and_nz_in_requested_context`
- `request_security_evaluates_provider_tuple_literal_math_in_requested_context`
- `request_security_evaluates_provider_tuple_literal_stateful_math_in_requested_context`
- the `request_security_evaluates_provider_tuple_literal_ta_*` family

Representative higher-timeframe provider tests include:

- `request_security_aligns_provider_higher_timeframe_tuple_literal`
- `request_security_aligns_provider_higher_timeframe_tuple_literal_history_and_nz`
- `request_security_aligns_provider_higher_timeframe_tuple_literal_math`
- `request_security_aligns_provider_higher_timeframe_tuple_literal_stateful_math`
- the `request_security_aligns_provider_higher_timeframe_tuple_literal_ta_*`
  family

Semantic coverage lives in `crates/pine-sema/src/tests/compatibility.rs`.
Representative accepted-form tests include:

- `accepts_provider_backed_request_security_tuple_literal_expression`
- `accepts_provider_backed_request_security_tuple_literal_history_and_nz_expression`
- `accepts_provider_backed_request_security_tuple_literal_math_expression`
- `accepts_provider_backed_request_security_tuple_literal_stateful_math_expression`
- the same-timeframe and higher-timeframe
  `accepts_provider_backed_*request_security_tuple_literal_ta_*` families

Unsupported-form semantic tests still reject tuple literals with local aliases
inside the requested expression and other side-effecting or non-scalar
requested-expression tails.

## Host Evidence

The host tests run the shared request fixture through the public host APIs:

- CLI: `runs_request_bars_integration_fixture`
- Python: `test_run_script_request_fixture_matches_cli_contract`
- WASM: `request_host_data_runs_through_direct_wasm_api`

These tests keep host behavior aligned with the shared runtime path. Hosts do
not reimplement tuple literal evaluation, requested-context state, or
higher-timeframe alignment.

## Unchanged Contracts

- Runtime output remains `schemaVersion: 3`.
- `tests/fixtures/conformance.tsv` keeps `request.security` as `partial`.
- `request.security_lower_tf` remains unsupported.
- Broad `request.*` families beyond the narrow `request.security` subsets
  remain unsupported.
- Optional `request.security` parameters, explicit `gaps`, explicit
  `lookahead`, provider expression local aliases, UDF calls, array mutation,
  drawing/output side effects, `math.random`, and `ta.tr` variable form remain
  outside this subset.
- No CLI, Python, or WASM request-bars host shape changed for this closeout.

## Verification

The closeout gate is:

```text
scripts/verify.sh
```

It covers formatting, clippy with `-D warnings`, workspace Rust tests,
structural guardrails, `pine-wasm` wasm32 checking, Python wheel build and
install, and the Python binding test suite.
