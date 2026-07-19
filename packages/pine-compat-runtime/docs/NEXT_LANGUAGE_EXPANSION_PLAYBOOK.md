# Next Language Expansion Playbook

This playbook defines the next implementation stage after the v0.1 baseline.
The goal is to widen language coverage without weakening the current rule that
compatibility claims must be backed by fixtures.

## Guiding Rules

- Add fixtures before or alongside every behavior change.
- Move one feature through syntax, semantic analysis, HIR, runtime, fixtures,
  conformance metadata, and docs before starting the next feature.
- Claim only fixture-covered behavior in `tests/fixtures/conformance.tsv`.
- Reject or avoid unsupported variants explicitly. Do not silently approximate
  Pine behavior.
- Keep runtime safety guards for loops or mutable state that can hang or grow
  without bound.

## Stage Order

1. `switch` expressions.
2. `while` statements.
3. Array storage and mutation.
4. Broader input and output options.
5. Strategy, request, drawing objects, imports, and alerts remain out of scope
   until the indicator runtime and conformance harness are broader.

## Stage 1: `switch` Expressions

### Target Syntax

Condition-list form:

```pine
value = switch
    close > open => high
    close < open => low
    => close
```

Selector form:

```pine
value = switch direction
    1 => high
    -1 => low
    => close
```

### Initial Scope

Support `switch` as an expression value. Each arm returns an expression. The
default arm is optional; if no arm matches and no default exists, the result is
`na`.

Do not support statement-block arms in the first pass. A later pass can add
block arms after expression arms are stable.

### Implementation Tasks

Status: implemented for expression arms; statement-block arms remain out of
scope for this stage.

- Syntax:
  - Add `switch` token support.
  - Add AST nodes for selector-less and selector-based switch expressions.
  - Parse newline/indent arm lists with `=>` arm separators.
  - Add parser recovery tests for malformed switch arms.
- Semantics:
  - Analyze condition-list arms as bool conditions.
  - Analyze selector-form arms by comparing selector and case expression kinds.
  - Merge arm result types using the existing branch merge rules.
  - Return `na` when a switch has no default and no arm matches.
- HIR:
  - Add a switch expression node with optional selector, arms, and optional
    default result.
  - Preserve callsite ids independently for expressions in each arm.
- Runtime:
  - Evaluate the selector once for selector-form switches.
  - Evaluate arms in source order.
  - Evaluate only the selected arm result.
  - Commit skipped series values as `na`, consistent with conditional behavior.
- Fixtures and matrix:
  - Add syntax, semantic, and runtime fixtures for both forms.
  - Add conditional stateful-call fixture inside switch arms.
  - Add `switch` to `tests/fixtures/conformance.tsv` as `partial`.
- Docs:
  - Update language scope, execution semantics, semantic model, and release notes
    for partial switch support.

### Suggested Commits

1. `Parse switch expressions`
2. `Analyze switch expression types`
3. `Execute switch expressions`
4. `Add switch conformance fixtures`

### Acceptance Criteria

- `cargo test -p pine-syntax switch`
- `cargo test -p pine-sema switch`
- `cargo test -p pine-runtime switch`
- `cargo test --workspace`
- `pine-compat matrix` lists `switch` with fixture paths.

## Stage 2: `while` Statements

### Target Syntax

```pine
i = 0
sum = 0
while i < 10
    sum := sum + i
    i := i + 1
plot(sum)
```

### Initial Scope

Support `while` as a statement. Support `break` and `continue` targeting the
nearest loop. Defer `while` expression results until statement execution is
stable.

### Runtime Guard

Add a deterministic max-iteration guard. The first implementation should use a
runtime constant such as `MAX_LOOP_ITERATIONS = 100_000`. If a loop exceeds the
guard, return a runtime error with a stable message. Do not allow scripts to
hang the host.

### Implementation Tasks

Status: implemented for statement loops and the first scalar while-expression
subset; tuple, UDT, and broader collection-expression variants remain out of
scope.

- Syntax:
  - Add `while` token support.
  - Parse while statements with indented bodies.
  - Add parser tests for nested `while`, `break`, and `continue`.
- Semantics:
  - Require bool conditions.
  - Reuse loop-depth validation for `break` and `continue`.
  - Keep body-local declarations scoped to the loop body.
- HIR:
  - Add a while statement node with condition and body.
- Runtime:
  - Evaluate the condition before each iteration.
  - Support nearest-loop `break` and `continue`.
  - Enforce the max-iteration guard.
  - Preserve local `var` declaration-site storage in while bodies.
- Fixtures and matrix:
  - Add runtime fixtures for ordinary loops, `break`, `continue`, local `var`,
    and guard failure.
  - Add `while` to conformance metadata as `partial`.
- Docs:
  - Document while statement support, the scalar expression subset, and the
    iteration guard.

### Suggested Commits

1. `Parse while statements`
2. `Analyze while loop control`
3. `Execute while statements with guard`
4. `Add while conformance fixtures`

### Acceptance Criteria

- `cargo test -p pine-syntax while`
- `cargo test -p pine-sema while`
- `cargo test -p pine-runtime while`
- Guard failure is covered by a runtime test.
- `cargo test --workspace`
- `pine-compat matrix` lists `while` with fixture paths.

## Stage 3: Arrays

Arrays are a larger stage because they introduce mutable reference-like values
and storage lifetime rules.

Status: closed for the current scalar typed-array subset. See
`docs/ARRAY_STAGE_AUDIT.md` for the supported surface, known compatibility
gaps, and future backlog.

### Initial Scope

The implemented initial subset started with float arrays and now also includes
int, bool, string, and color arrays:

```pine
var values = array.new_float()
array.push(values, close)
first = array.get(values, 0)
count = array.size(values)
plot(count)

var counts = array.new_int()
counts.push(bar_index)

var flags = array.new_bool()
flags.push(close > open)

var names = array.new_string()
names.push("seed")

var shades = array.new_color()
shades.push(color.red)
```

Initial supported functions:

- `array.new_float`
- `array.new_int`
- `array.new_bool`
- `array.new_string`
- `array.new_color`
- `array.from`
- `array.push`
- `array.get`
- `array.set`
- `array.insert`
- `array.size`
- `array.pop`
- `array.remove`
- `array.shift`
- `array.unshift`
- `array.fill`
- `array.first`
- `array.last`
- `array.copy`
- `array.slice`
- `array.concat`
- `array.includes`
- `array.every`
- `array.some`
- `array.indexof`
- `array.lastindexof`
- `array.binary_search`
- `array.binary_search_leftmost`
- `array.binary_search_rightmost`
- `array.abs`
- `array.min`
- `array.max`
- `array.sum`
- `array.avg`
- `array.range`
- `array.median`
- `array.mode`
- `array.percentile_nearest_rank`
- `array.percentile_linear_interpolation`
- `array.percentrank`
- `array.covariance`
- `array.standardize`
- `array.variance`
- `array.stdev`
- `array.sort`
- `array.sort_indices`
- `array.reverse`
- `array.join`
- `array.clear`

### Required Design Decisions

Resolved implementation choices:

- `PineValue::Array` stores an id into runtime-owned array storage.
- Non-`var` arrays are allocated when their declaration executes on each bar.
- `var` arrays preserve their id and backing storage across bars.
- Array values remain runtime-internal in JSON/Python/WASM outputs.
- The current pass supports float, int, bool, string, color, label-id, and line-id arrays with
  array.from inference and size/get/set/insert/push/pop/remove/shift/unshift/fill/first/last/copy/slice/concat/includes/indexof/lastindexof/clear,
  negative indexes for get/set/insert/remove, plus numeric binary search/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev,
  numeric/string sort and sort_indices, all-supported-array reverse, and
  scalar-array join only; unsupported `array.*` variants still produce
  diagnostics.
- Array assignment and UDF argument binding pass the runtime array id by
  reference. `array.copy` is the explicit boundary for creating an independent
  array id with copied element values.

### Implementation Tasks

- [x] Add array types to HIR and semantic type checks.
- [x] Add runtime array store with explicit ids.
- [x] Implement selected `array.*` built-ins.
- [x] Add diagnostics for unsupported array element kinds and unsupported array
  functions.
- [x] Add fixtures for `var` array persistence, non-`var` per-bar allocation,
  mutation order, out-of-range reads, and UDF boundaries.
- [x] Move `array.*` from unsupported to partial in conformance metadata only after
  fixture coverage exists.

Remaining array work is deferred rather than part of this stage:

- Remaining generic `array.new<type>()` syntax and type checking for future
  UDT/polyline/map/matrix element families.
- Additional object, drawing, UDT, matrix, and map arrays outside the current
  fixture-backed scalar, drawing-id, and chart.point subset.
- Array history snapshots and dynamic history offsets.
- `for...in` array iteration.
- UDT `sort_field` support for `array.sort` and `array.sort_indices`.

### Suggested Commits

1. `Design array runtime storage`
2. `Support float array creation and size`
3. `Support float array get set push pop`
4. `Add array conformance fixtures`

### Acceptance Criteria

- [x] Array fixtures pass historical and incremental execution.
- [x] Unsupported array variants still produce diagnostics.
- [x] Matrix marks `array.*` as `partial`, not broadly supported.

## Later Stages

### Broader Input and Output Options

Candidate areas:

- More `input.*` variants.
- Input override API.
- More `plot` style/color/visibility parameters.
- `plotshape`, `plotchar`, and similar output calls.

### Still Out of Scope

Keep these rejected until separate design docs exist:

- `request.*`
- `strategy.*`
- drawing objects
- imports/libraries
- alerts
- `varip`
- maps, matrices, user-defined types, and methods

## Definition of Done for Each Feature

Before marking a feature complete:

- Syntax tests cover valid and malformed source.
- Semantic tests cover accepted and rejected cases.
- Runtime tests cover historical execution.
- Incremental fixture execution matches full recomputation when applicable.
- Realtime behavior is covered or explicitly documented as out of scope.
- `tests/fixtures/conformance.tsv` has fixture paths for the claim.
- Docs describe supported and unsupported variants.
- Full verification passes:

```text
cargo fmt --check
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
cargo check -p pine-wasm --target wasm32-unknown-unknown
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python -m pip install --force-reinstall dist/*.whl
python -m pytest python/tests
```
