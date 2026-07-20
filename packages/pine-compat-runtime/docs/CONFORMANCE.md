# Conformance

This document defines how compatibility is measured.

The project should make compatibility claims by tested feature, not by broad
language name.

## Fixture Categories

Fixtures should be grouped by behavior:

```text
tests/fixtures/
  syntax/
  sema/
  runtime/
  builtins/
  unsupported/
  regressions/
```

Each fixture should include:

- source script
- expected diagnostics or expected output
- selected Pine version
- fixture ownership or license metadata when not original

## Snapshot Outputs

Runtime snapshots should be normalized JSON:

```json
{
  "schemaVersion": 8,
  "plots": [],
  "plotChars": [],
  "plotShapes": [],
  "plotArrows": [],
  "plotBars": [],
  "plotCandles": [],
  "bgColors": [],
  "barColors": [],
  "hlines": [],
  "fills": [],
  "labels": [],
  "lines": [],
  "lineFills": [],
  "polylines": [],
  "boxes": [],
  "tables": [],
  "alerts": [],
  "diagnostics": []
}
```

The snapshot format should avoid host-specific charting details.

Every machine-readable public output must include top-level `schemaVersion`.
Runtime outputs use `PUBLIC_RUNTIME_SCHEMA_VERSION`; analysis outputs use
`PUBLIC_ANALYSIS_SCHEMA_VERSION`; matrix JSON uses
`PUBLIC_MATRIX_SCHEMA_VERSION`. Runtime output is currently `schemaVersion: 8`
because the top-level `alerts` array is reserved, strategy order-fill alert
payloads are exposed under `strategy.alerts`, table cell snapshots include
host-neutral `textWrap`, linefill snapshots are exposed under `lineFills`, and
polyline creation and lifecycle snapshots are exposed under `polylines`; plot,
marker, bar, candle, color, hline, and fill outputs also expose normalized
visual series and fixture-backed metadata;
runtime results also carry `renderMetadataVersion: 1` so hosts can distinguish
native visual metadata from host defaults. Analysis JSON is currently
`schemaVersion: 5`; in addition to top-level `inputs` callsite metadata, it
exposes compile-time defaults, constraints, and options plus validated
language-version origin, dialect, script mode, and reserved legacy
translation/emulation evidence. Matrix JSON
remains `schemaVersion: 2`.
The contracts are separate so runtime-only fields do not force analysis or
matrix schema changes. CLI `analyze --format json`, Python analysis
dictionaries, and WASM analysis JSON project this same analysis contract; the
default CLI text report remains diagnostic console output.

Legacy host parity has two explicit baselines. CLI runtime fixtures generate
the ordinary `runtime_*.json` goldens listed in
`scripts/host_parity_required.txt`. CLI legacy analysis fixtures generate the
complete `analysis_legacy_*.json` reports listed in
`scripts/legacy_analysis_parity_required.txt`. Python and WASM must assert every
required golden, and `scripts/check_host_parity.py` fails missing registrations,
missing host assertions, duplicate entries, unrecorded pairs, or runtime /
analysis name collisions. Analysis comparisons use complete parsed JSON values,
so every schema field and value must agree without treating object-key order as
semantic.

## Legacy Indicator Release Profiles

`tests/fixtures/legacy/release_profiles.tsv` is the release execution registry.
It contains 12 complete legacy runtime fixtures and three additional MTF rows.
Every row pins source version, maturity, bars/request environment, realtime
policy, original-source provenance, and a retained-value ceiling. The runtime
release test fails if a legacy runtime fixture is missing from the registry,
if a row changes maturity or provenance unexpectedly, or if execution diverges
across its required modes.

| Profile | Maturity | Eligible corpus | Release rows | Historical/incremental | Realtime policy |
| --- | --- | ---: | ---: | --- | --- |
| v4 | preview | 12 | 9 | exact parity | forming/rollback/confirmed parity |
| v3 | preview | 7 | 2 | exact parity | forming/rollback/confirmed parity |
| v2 | experimental | 2 | 3 | exact parity | ordinary rows parity; lookahead row forbids future leakage |
| implicit v1 | experimental | 1 | 1 | exact parity | forming/rollback/confirmed parity |

The fixed seed corpus has 22 eligible legacy indicators and six controls plus
one excluded legacy strategy. It reaches 100% parse, analyze/lower, and
historical-run success with zero unknown diagnostics, but it is small and has
no external reference-output oracle. The provisional stable gate requires at
least 50 authorized eligible scripts per profile when samples are available;
therefore no v1-v4 profile is labeled stable. A passing feature row means that
the named fixture-backed behavior is supported, not that its enclosing
language profile is stable.

`scripts/profile_legacy_release.py` performs an indicative end-to-end CLI
analysis timing pass and consumes public runtime profiles to count retained
series/window/output values. Timing is observational and machine-dependent;
the per-row resource ceiling is deterministic and release-gated. Corpus and
release manifests require explicit license classes and source paths, and
privacy-preserving corpus reports omit source text and source paths.

Legacy exact-alias conformance requires a paired source/canonical HIR or runtime
comparison, an original-span translation record, a user-symbol collision
control, and a v5/v6 negative control. Catalog validation must also prove that
canonical targets exist and version ranges neither overlap nor enter modern
dialects. Phase 2 exercises these requirements with a synthetic catalog only;
production alias rows become support claims only when their owning phase adds
fixtures and conformance metadata.

The current pure-internal call-result subset normalizes an unqualified plain
local UDF receiver through the parser-only `$call_result` prefix, exact static
built-in array producers through `$builtin_array_result`, and the five exact
`matrix.new<float|int|bool|string|color>` templates plus namespace
`matrix.copy(...)`/`matrix.transpose(...)`/`matrix.submatrix(...)`/
`matrix.kron(...)`/`matrix.diff(...)`/`matrix.pow(...)`/`matrix.inv(...)`/
`matrix.pinv(...)`/`matrix.eigenvectors(...)`/`matrix.mult(...)` candidates through
`$builtin_matrix_result`. Exact supported scalar `map.new<K,V>` templates and
exact namespace `map.copy(existing)` results use the separate
`$builtin_map_result` prefix. Local UDF,
qualified user-defined UDF/method, and admitted built-in producer results can
use only `.size()`, `.get(index)`, `.first()`, `.last()`, and `.copy()` for
currently supported array kinds. Namespace `matrix.mult(...)` results that
resolve to a matrix and namespace `matrix.copy(...)` results can instead use
the same set as namespace `matrix.transpose(...)`, `matrix.submatrix(...)`,
`matrix.kron(...)`, `matrix.diff(...)`, `matrix.pow(...)`, `matrix.inv(...)`,
`matrix.pinv(...)`, and `matrix.eigenvectors(...)` results: `.rows()`, `.columns()`,
`.elements_count()`, `.get(row, column)`, `.copy()`, `.submatrix(...)`, and
`.transpose()`, plus terminal `.set(row, column, value)`, `.fill(value)`, `.reverse()`, `.reshape(rows, columns)`, `.add_row(row, array_id)`, `.add_col(column, array_id)`, numeric-only `.sort(column?, order?)`, `.swap_rows(row1, row2)`, `.swap_columns(column1, column2)`, `.remove_row(row)`, and `.remove_col(column)`. Numeric results
additionally admit `.diff(other)`, `.eigenvectors()`, `.inv()`, `.kron(other)`,
`.mult(other)`, `.pinv()`, and `.pow(power)`.
Unqualified local-UDF results that infer a concrete supported matrix kind use
that same forty-four-helper closed set through `$call_result`, subject to
the numeric-only checks; parameter passthrough,
block aliases, nested calls, same-kind control flow, matrix operations, and
constructors retain call-specific float/int/bool/string/color kinds.
`.copy()`, numeric `.diff(other)`/`.eigenvectors()`/`.inv()`/`.kron(other)`/`.mult(other)`/`.pinv()`/`.pow(power)`,
`.submatrix(...)`, and `.transpose()` may continue. Local and
imported user-method results with a concrete supported matrix kind share the
same closed helpers through recorded method-call
provenance, including receiver-style, local-type-qualified or alias-qualified,
direct-constructor-receiver, block/nested/control-flow, dual-alias, and nested
copy paths. Registered imported pure-function results with a concrete supported
matrix kind also share them across alias-qualified, block/nested/
control-flow, five-kind, dual-alias, and nested-copy paths. Unregistered or
unresolved user-function matrix results do not enter these paths.
`matrix.copy` preserves shape, while `matrix.transpose` swaps shape; both
preserve the source's supported matrix element kind. `matrix.submatrix`
preserves that element kind while returning the selected half-open range.
`matrix.kron` always produces an independent expanded-shape `matrix<float>`
from two numeric matrices.
`matrix.diff` produces an independent `matrix<float>` with the selected matrix
operand's shape and preserves left-to-right subtraction order.
`matrix.pow` produces an independent square `matrix<float>` for identity,
copy, and positive integer powers.
`matrix.inv` produces an independent square `matrix<float>`, empty `0 x 0`, or
`na` for singular/invalid-cell inputs; non-square inputs retain the runtime
shape error.
`matrix.pinv` produces an independent fixed `matrix<float>`, swaps rectangular
row/column counts, preserves singular matrix-valued results and swapped zero-
cell shapes, and yields `na` for invalid-cell inputs.
`matrix.eigenvectors` produces an independent square `matrix<float>` whose
columns are real complete eigenvectors, or `na` for invalid-cell, non-real, or
incomplete results.
Each admitted `matrix.new<T>` template produces a fresh matrix with its
float/int/bool/string/color element kind, requested rectangular shape,
type-compatible initial value or default `na`, and the same seven direct
all-kind read/copy/submatrix/transpose helpers. Numeric templates additionally
admit `.diff(other)`, `.eigenvectors()`, `.inv()`, `.kron(other)`, `.mult(other)`, `.pinv()`, and `.pow(power)` with copy/diff/eigenvectors/inv/kron/mult/pinv/pow/submatrix/transpose
continuation.
Admitted scalar map results expose `.size()`, terminal `.put(key, value)`,
`.clear()`, `.remove(key)`, and `.put_all(source)`, `.get(key)`, `.contains(key)`, `.copy()`,
`.keys()`, and `.values()`, retain
known scalar key/value kinds, and allow only `.copy()` to continue another map
read/copy. `.put(...)` validates both concrete scalar kinds, replaces an
existing value without moving its key or appends a new insertion-order entry,
returns `void`, and cannot continue. Fresh constructor, copy, imported-
function, and imported-method results isolate the write; local UDF and local
user-method alias results update shared storage. `.clear()` empties the same
backing entry list, returns `void`, and cannot continue, with the same alias-
versus-fresh storage split.
`.remove(...)` validates the concrete key kind, deletes the matching entry
without disturbing the order of retained keys, no-ops for a missing key,
returns `void`, and uses the same alias-versus-fresh storage split.
`.put_all(...)` requires the exact same key/value template, clones source
entries before merging so self-merge is safe, replaces existing values without
moving keys, appends new keys in source order, returns `void`, and uses the same
alias-versus-fresh split.
Unqualified local-UDF results that retain one concrete supported scalar map
template share those ten helpers through `$call_result`; parameter
passthrough, block aliases, nested calls, same-template control flow,
constructed/copied results, and named/reordered arguments preserve per-call
key/value metadata and copy independence. Imported pure-function results with
one concrete supported scalar map template share the same helpers across
alias-qualified, block-return, nested-function, same-template control-flow,
constructed-result, scalar-template-interleaving, same-library dual-alias, and
independent-copy paths. Local and imported user-method results retain their
receiver-style and qualified/direct-constructor coverage. Unknown/`na`,
scalar, array, matrix, wrong-template/key/value/source, broader-helper, map
mutation outside terminal `.put(...)`/`.clear()`/`.remove(...)`/`.put_all(...)`, array mutation outside the admitted derived-
array set, and terminal-read continuation cases remain gated. Direct map
mutation inside UDFs remains rejected.
Local-UDF scalar UDT results may also use existing pure user methods when they
carry a concrete local or imported scalar-tree identity. Array result paths
allow `.copy()` and `.slice(index_from, index_to)`, plus numeric `.abs()` and `.standardize()`, and numeric-or-
string `.sort_indices(order?)`, to yield another
array receiver; map result paths allow only `.copy()` to yield another same-
family collection receiver;
matrix results allow `.copy()`, `.submatrix(...)`, or `.transpose()` to
continue the matrix chain.
Scalar and concrete same-identity scalar-tree UDT array results additionally
expose terminal `.join(separator?)`. The other readers are terminal or transition to the closed array-result path
and cannot continue into user methods or unrelated call-result methods.
Built-in-qualified/template receivers outside the exact
`array.*` producer allowlist, the exact seven fixed cross-namespace producers,
the result-type-checked namespace `matrix.mult` paths, the unqualified local-UDF
matrix path, and the exact namespace
`matrix.copy`/`matrix.transpose`/`matrix.submatrix`/`matrix.kron`/
`matrix.diff`/`matrix.pow`/`matrix.inv`/`matrix.pinv`/
`matrix.eigenvectors` paths remain rejected. So do
non-array/non-matrix/non-UDT results, unknown/`na` results without a concrete
supported type or identity, mixed or non-scalar UDT-array identities, other
array or matrix helpers, and call-result
mutation.

## Built-In Runtime Contract

Built-in compatibility is claimed one fixture-backed subset at a time. The
current timeframe metadata subset exposes `timeframe.period` and
`timeframe.main_period` as the runtime's single chart timeframe string. Main
timeframe declaration overrides and requested-context differences are not
claimed until a separate fixture-backed slice designs that context model.
`runtime.error(message)` is a fixture-backed internal execution outcome: it
accepts string-compatible messages, may be called through a user-defined
function or named argument, and stops at the first reached call with the exact
message. Typed `na` is normalized to `NaN`; non-string messages and uses of the
`void` result are rejected. It does not require a host log or output contract.
Input rows in `tests/fixtures/conformance.tsv` include two separate claims:
the executable Pine `defval`/metadata subset covered by runtime fixtures, and
the host override subset covered by Rust runtime, CLI, Python, and WASM entry
point tests. Host overrides are keyed by analysis `inputs[].callSiteId` and are
limited to scalar/string-like `input.*` calls; host-side `input.source`
overrides remain outside the supported contract.
Typed variable declarations are partial: `int`, `float`, `bool`, `string`,
`color`, `chart.point`, and drawing-id `label`, `line`, `linefill`, `box`,
`table`, and `polyline` declarations, plus scalar `array<int>`,
`array<float>`, `array<bool>`, `array<string>`, `array<color>`, and
object-id `array<label>`, `array<line>`, `array<linefill>`,
`array<polyline>`, `array<box>`, `array<table>`, `array<chart.point>`, and
same-local scalar-tree UDT `array<T>` declarations and same-imported
scalar-tree UDT `array<lib.Type>` declarations, are fixture-backed with
compatible or `na` initializers and later compatible reassignment. The
equivalent `type[]` aliases are fixture-backed for the same supported array
element types, including `var` declarations, the scalar and `chart.point`
typed-array `varip` subset, explicitly typed same-local scalar-tree UDT
`varip` declarations initialized from `na`, same-UDT constructors,
same-identity aliases, or fixture-backed same-UDT ternary/switch/if/for/for...in/while expressions,
direct-alias-inferred same-local or same-imported scalar-tree UDT `varip`, scalar map `varip`,
same-local and same-imported scalar-tree UDT array `varip`, and `matrix<float>`,
`matrix<int>`, `matrix<bool>`, `matrix<string>`, or `matrix<color>`
declarations initialized from compatible matrix values or `na`. Bare `array`,
non-scalar UDT arrays, nested-field UDT `varip`, template-less bare map
declarations, matrix
declarations beyond float/int/bool/string/color, and other typed declarations remain unsupported
unless a narrower feature row explicitly backs them with fixtures;
direct sema fixtures keep bare array declarations, including `var`, `na`, and
initializer-inferred forms, non-scalar UDT array template and alias
declarations, mismatched UDT array declarations, non-constructor-inferred UDT
`varip`, nested-field UDT `varip`, non-scalar UDT array `varip`,
non-scalar imported UDT array `varip`,
unsupported map/matrix array element templates, nested array element templates,
tuple array element templates, strategy-like record array element templates,
plus template-less bare map, bare matrix, and cross-element matrix typed declaration boundaries
rejected, and the imported-source compatibility
fixtures keep non-scalar `array<lib.Wrapper>` and `lib.Wrapper[]` declarations
rejected. Parser-level syntax fixtures keep deeply dotted `array.new<...>()`
templates rejected, while same-local scalar-tree UDT `array.new<T>()` and
same-imported scalar-tree UDT `array.new<lib.Type>()` expressions are
fixture-backed outside typed declaration syntax.

Direct method reads on an `array.*` built-in producer are a closed,
fixture-backed exception to the general built-in call-result parser boundary.
The exact admitted producer set is `array.new_float`, `array.new_int`,
`array.new_bool`, `array.new_string`, `array.new_color`, `array.new_line`,
`array.new_linefill`, `array.new_polyline`, `array.new_label`, `array.new_box`,
`array.new_table`, `array.new<chart.point>`, supported `array.new<UDT>`,
`array.from`, `array.copy`, `array.slice`, `array.concat`, `array.abs`,
`array.standardize`, and `array.sort_indices`. Existing supported
`array.new<T>` source templates for
scalar, drawing-id, `chart.point`, and concrete same-local or same-imported
scalar-tree UDT element types enter through the corresponding canonical
constructor or checked UDT-template path. Only `.size()`, `.get(index)`,
`.first()`, `.last()`, `.copy()`, `.slice(index_from, index_to)`, `.concat(id2)`, `.includes(value)`, `.indexof(value)`, and
`.lastindexof(value)`, plus bool/int/float-only `.every()`/`.some()` and numeric-only `.binary_search(value)` and
`.binary_search_leftmost(value)`/`.binary_search_rightmost(value)`/`.abs()`/
`.min(nth?)`/`.max(nth?)`/`.sum()`/`.avg()`/`.range()`/`.median()`/`.mode()`/`.percentile_nearest_rank(percentage)`/`.percentile_linear_interpolation(percentage)`/`.percentrank(index)`/`.covariance(id2, biased?)`/`.standardize()`/`.variance(biased?)`/`.stdev(biased?)`, plus int/float/string `.sort_indices(order?)` or exact-identity scalar-tree UDT `.sort_indices(order?, sort_field?)`, scalar/same-identity scalar-tree UDT `.join(separator?)`, and terminal top-level `.clear()`/`.reverse()`/`.pop()`/`.shift()`/`.remove(index)`/`.push(value)`/`.unshift(value)`/`.insert(index, value)`/`.set(index, value)`/`.fill(value, index_from?, index_to?)`/`.sort(order?, sort_field?)`, may follow one of those producer calls;
the parser uses the impossible synthetic prefix `$builtin_array_result` and
semantic analysis rechecks the receiver type, producer arguments, and concrete
UDT identity before lowering. Only `.copy()`, `.slice(index_from, index_to)`, `.concat(id2)`, numeric `.abs()` and
`.standardize()`, and sortable-scalar or exact-identity scalar-tree UDT `.sort_indices(order?, sort_field?)` may continue
with another allowed array chain; the twenty-nine terminal value results and
the eight `void` mutations cannot continue
into a user method or any other call-result method, including a scalar UDT
element method.
`.concat(id2)` is the sole admitted mutating array-returning continuation. It
requires a same-kind or exact-identity source, appends into and returns the
receiver id, and may continue through the closed helper path. Alias/live-slice
writes reach shared parent backing, fresh snapshots remain independent, and
ordinary upstream-`na`, capacity, arity, and UDF-side-effect behavior applies.
`.includes(value)` reuses the ordinary element-kind and same-identity UDT
argument checks and equality rules, returns `series bool`, is false for an
empty concrete array, propagates an upstream `na` array, performs no mutation,
and creates no continuation prefix.
`.every()` accepts concrete bool, int, or float array results and returns fixed
`series bool` without mutating the source. It is true only when every element
is truthy: nonzero numerics and `true` pass, while zero, `false`, and element
`na` fail. Empty arrays return true and an upstream `na` array propagates.
String/color/object/chart-point/UDT results and extra arguments remain rejected;
the scalar result is terminal and creates no continuation prefix.
`.some()` uses the same concrete bool/int/float gate and fixed `series bool`
result, but returns true when at least one nonzero numeric or `true` element
exists. Zero, `false`, and element `na` do not satisfy it; empty arrays return
false and an upstream `na` array propagates. It leaves the source unchanged,
rejects the same string/color/object/chart-point/UDT and extra-arity cases, and
is terminal without a continuation prefix.
`.indexof(value)` reuses the same validation and equality rules, returns the
first zero-based match as `simple int`, returns `-1` for missing or empty
concrete arrays and for an upstream `na` array, performs no mutation, and
creates no continuation prefix.
`.lastindexof(value)` reuses the same validation and equality rules, returns
the last zero-based match as `simple int`, returns `-1` for missing or empty
concrete arrays and for an upstream `na` array, performs no mutation, and
creates no continuation prefix.
`.binary_search(value)` retains the ordinary numeric-array receiver and numeric-
value checks. It expects ascending contents and performs an exact lower-bound
search, returning the leftmost duplicate match as `simple int` or `-1` for
missing, empty, and upstream-`na` arrays. It performs no mutation and creates no
continuation prefix. Nonnumeric, drawing/object, chart-point, and UDT result
arrays remain rejected.
`.binary_search_leftmost(value)` shares the numeric checks and ascending-input
contract. Exact duplicates return their first index; misses return the nearest-
left element index, clamped to `0` below the minimum and the last index above
the maximum. Empty and upstream-`na` arrays return `-1`. The result is `simple
int`, non-mutating, terminal, and creates no continuation prefix.
`.binary_search_rightmost(value)` is the symmetric ceiling search. Exact
duplicates return their last index; misses return the nearest-right element
index, with the same below-min/above-max clamps, empty/upstream-`na` `-1`,
numeric gate, `simple int`, non-mutation, and terminal boundaries.
`.abs()` accepts only concrete numeric array results, returns a fresh same-kind
int or float array, preserves `na` elements, leaves the source unchanged, and
preserves empty-array and upstream-`na` behavior. Its result may continue
through another admitted reader, `.copy()`, `.abs()`, `.standardize()`, or `.sort_indices()`.
`.min(nth?)`/`.max(nth?)` return the same series numeric kind as the receiver
element type. They rank non-`na` elements in ascending order for `min` and
descending order for `max`, with a zero-based optional `nth` that defaults to
`0`; dynamic integer ranks are accepted. Empty, all-`na`, and
upstream-`na` arrays, plus `na`, negative, or out-of-range ranks, return `na`.
The scalar result is non-mutating and terminal.
`.sum()` returns the same series numeric kind as the receiver element type,
adds all non-`na` elements, and returns `na` for empty, all-`na`, or upstream-
`na` arrays. It is also non-mutating and terminal.
`.avg()` always returns `series float`, averages the same filtered elements,
and shares the empty, all-`na`, upstream-`na`, non-mutation, and terminal
boundaries; a non-finite result becomes `na`.
`.range()` returns the receiver element type's series numeric kind and computes
maximum minus minimum over non-`na` elements. Empty, all-`na`, and upstream-
`na` arrays return `na`, as does a non-finite float difference; it is
non-mutating and terminal.
`.median()` sorts the filtered non-`na` elements, selects the middle item for an
odd count, and averages the middle pair for an even count. It preserves the
receiver series numeric kind; integer pair means truncate toward zero. Empty,
all-`na`, upstream-`na`, and non-finite float medians return `na`; the result is
non-mutating and terminal.
`.mode()` sorts the filtered non-`na` elements, returns the most frequent value
in the receiver's series numeric kind, and chooses the smaller value when
frequencies tie. At least one value must repeat; empty, all-`na`, upstream-`na`,
and all-unique arrays return `na`. The result is non-mutating and terminal.
`.percentile_nearest_rank(percentage)` sorts filtered non-`na` elements and
returns the element at `ceil(percentage / 100 * count) - 1`, with `0` selecting
the minimum and `100` the maximum. Positional or named series/simple numeric
percentages are accepted. Empty, all-`na`, upstream-`na`, runtime typed-`na`,
negative, and above-100 percentages return `na`; the receiver-derived series
numeric result is non-mutating and terminal.
`.percentile_linear_interpolation(percentage)` sorts the same filtered values
and interpolates at `percentage / 100 * (count - 1)`. It always returns
`series float`, including for integer arrays and single-element inputs.
Positional or named series/simple numeric percentages are accepted. Empty,
all-`na`, upstream-`na`, runtime typed-`na`, out-of-range, and non-finite
interpolation results return `na`; the read is non-mutating and terminal.
`.percentrank(index)` reads the target at the original zero-based array index,
filters `na` values only from the comparison population, and returns
`count(value <= target) / non_na_count * 100` as `series float`. Duplicate
values participate independently. The index may be positional or named but
must remain simple int-compatible. Empty, all-`na`, upstream-`na`, target-
`na`, runtime typed-`na`, negative, and out-of-range indexes return `na`; the
read is non-mutating and terminal.
`.covariance(id2, biased?)` requires a same-length runtime numeric second
array, pairs cells by original index, and discards a pair when either side is
`na`. It returns fixed `series float`, using the biased population denominator
by default and the sample denominator when `biased` is `false` or `na`.
The second array and bias may be positional or named. Empty/all-`na`/upstream-
`na` pairs, mismatched lengths, sample populations below two pairs, and non-
finite results return `na`; the read is non-mutating and terminal.
`.standardize()` accepts only concrete numeric array results and returns a
fresh fixed `simple array<float>`, leaving its source unchanged. It computes
the mean and population standard deviation from non-`na` values and preserves
`na` positions when at least one numeric value exists. Zero or non-finite
standard deviation produces `na` at every numeric position, so a constant
source becomes a same-length all-`na` result. Empty and all-`na` sources return
an empty array, while an upstream-`na` source returns `na`. The new array may
continue through the same closed reader, `.copy()`, `.abs()`, and
`.standardize()`/`.sort_indices()` set.
`.variance(biased?)` accepts concrete numeric array results and returns fixed
`series float`. It filters `na` elements, uses the population denominator when
`biased` is omitted or `true`, and uses the sample denominator when `biased`
is `false` or `na`; the argument may be positional or named. A single numeric
value therefore has population variance `0`, while an unbiased population
below two values returns `na`. Empty, all-`na`, upstream-`na`, insufficient-
sample, and non-finite results return `na`. The read leaves its source
unchanged and is terminal.
`.stdev(biased?)` shares the same concrete numeric receiver, filtered-`na`,
bias, positional/named argument, empty/all-`na`/upstream-`na`, sample-size,
non-finite, non-mutation, and terminal boundaries as `.variance()`. It returns
fixed `series float` equal to the square root of the selected population or
sample variance; one numeric value therefore returns population standard
deviation `0` and unbiased `na`.
`.sort_indices(order?, sort_field?)` accepts concrete int, float, or string
array results and concrete same-local or same-imported scalar-tree UDT array
results. UDT results require a compile-time root int/float/string field
resolved against the exact call-result identity. It returns a fresh fixed
`simple array<int>` containing stable original indexes. Omitted order is
ascending and explicit `order.descending` reverses the value ordering while
preserving equal-value source order. Existing float-`na` and string-empty
placement is unchanged. Empty input returns an empty index array, upstream
`na` propagates, and the source is never mutated. The result may continue
through the closed int-array helper path, including nested `.sort_indices()`.
Bool/color/object/chart-point receivers, missing/unknown/dynamic or unsupported
UDT fields, unresolved/mixed/non-scalar UDT identities, invalid order or arity,
and direct mutation other than `.concat(id2)`/`.clear()`/`.reverse()`/`.pop()`/`.shift()`/`.remove(index)`/`.push(value)`/`.unshift(value)`/`.insert(index, value)`/`.set(index, value)`/`.fill(value, index_from?, index_to?)`/`.sort(order?, sort_field?)` remain rejected.
Unsupported element templates, all other `array.*` members, built-in
namespaces and templates outside the exact cross-namespace producer set below,
and postfix mutation other than `.concat(id2)`/`.clear()`/`.reverse()`/`.pop()`/`.shift()`/`.remove(index)`/`.push(value)`/`.unshift(value)`/`.insert(index, value)`/`.set(index, value)`/`.fill(value, index_from?, index_to?)`/`.sort(order?, sort_field?)` remain fail-closed. The
lexical prefix `array` is reserved for this
built-in recognition, so an import or user qualifier named `array` is not a
supported qualified call-result receiver path.

`array.concat(left, right)` remains a mutating producer: it appends into
`left` in place and returns the first array id. A following allowed postfix
helper only reads that returned id (or independently copies it); it does not
make the producer pure, and `array.concat(...).size()` or an equivalent chain
inside a UDF remains rejected by the collection-side-effect rule.
`array.slice(...)` returns its existing live shallow parent window, so a
following read observes that view. `array.slice(...).copy()` instead allocates
an independent array containing the window's current values.
The same rule now applies when `.slice(index_from, index_to)` follows any
concrete array call result: it preserves scalar/object/`chart.point` element
kind or same-local/same-imported UDT identity, remains a bidirectionally live
window, accepts only the ordinary simple-int-compatible bounds, and may
continue through the closed array-result helper set. Invalid bounds and an
upstream `na` receiver retain the ordinary `na` result.
Terminal top-level `.clear()` reuses ordinary array mutation and returns
`void`. Alias-returning concat and local/imported UDF or method results clear
their shared backing array, while nested slices delete their live window from
the parent. Matrix row/column/eigenvalue, map key/value, and array-returning
`matrix.mult` results are fresh snapshots, so clearing them leaves the source
collection unchanged. Empty and upstream-`na` results are no-ops; extra
arguments, continuation, and use inside a UDF remain rejected.
Terminal `.reverse()` has the same alias/live-window/fresh-snapshot, empty/
upstream-`na`, zero-explicit-argument, `void`, continuation, and UDF-side-
effect boundaries, while reversing rather than removing the result values.
Terminal `.pop()` removes and returns the final resolved scalar/object/
`chart.point`/UDT element, returns `na` for empty or upstream-`na` results, and
shares the alias/live-window/fresh-snapshot, arity, continuation, and UDF gate.
Terminal `.shift()` shares those boundaries while removing and returning the
first resolved element and preserving the order of all remaining elements.
Terminal `.remove(index)` deletes and returns the selected positive or in-range
negative element. It accepts one simple-int-compatible index, returns `na`
without mutation for an explicit `na` index or upstream-`na` result, preserves
ordinary out-of-range runtime errors, and shares the identity, alias/live-
window/fresh-snapshot, continuation, and UDF boundaries.
Terminal `.push(value)` appends one element-compatible value, returns `void`,
and shares the identity, alias/live-window/fresh-snapshot, continuation, and
UDF boundaries. Mismatched scalar or UDT values are rejected, upstream-`na`
results remain no-ops after value evaluation, and the 100000-element runtime
limit is unchanged.
Terminal `.unshift(value)` is symmetric: it prepends the compatible value at
the resolved result's start, returns `void`, and shares the same identity,
alias/live-window/fresh-snapshot, continuation, upstream-`na`, UDF, and
100000-element boundaries.
Terminal `.insert(index, value)` accepts a simple-int-compatible index and one
compatible value, inserts at a positive, in-range negative, or end position,
returns `void`, and cannot continue. Explicit `na` indexes and upstream-`na`
results are no-ops after value evaluation; ordinary bounds, identity, alias/
live-window/fresh-snapshot, UDF, and parent-capacity behavior is preserved.
Terminal `.set(index, value)` accepts the same index/value type contract but
replaces one positive or in-range negative slot without changing length. It
returns `void` and cannot continue; explicit `na` indexes and upstream-`na`
results no-op after value evaluation, while empty/out-of-range, identity,
alias/live-window/fresh-snapshot, and UDF behavior remains unchanged.
Terminal `.fill(value, index_from?, index_to?)` validates the same value kind or
concrete UDT identity and optional simple-int-compatible half-open range. It
returns `void` and cannot continue; omitted bounds fill the full result, live
slices write through to parent backing, and fresh map/matrix-derived arrays
remain source-independent. Explicit `na`, negative, reversed, or oversized
bounds, empty arrays, and upstream-`na` receivers no-op after evaluating every
supplied argument, while UDF mutation stays rejected.
Terminal `.sort(order?, sort_field?)` sorts concrete int/float/string results
in place, ascending by default or descending by a supported const order. A
same-local or same-imported scalar-tree UDT result instead requires a compile-
time root int/float/string `sort_field`, which is lowered against that exact
identity. Alias and nested live-slice results reorder parent backing, while
fresh map/matrix-derived arrays reorder only their snapshots. Empty and
upstream-`na` results remain no-ops after order evaluation; unsupported kinds,
field/order/arity errors, continuation, and UDF mutation remain closed.

One later closed slice admits exactly seven fixed non-`array` namespace
producers on that same `$builtin_array_result` path: `str.split`,
`ta.pivot_point_levels`, `matrix.row`, `matrix.col`,
`matrix.eigenvalues`, `map.keys`, and `map.values`. They share the same forty-four
parser helpers: `.size()`, `.get(index)`, `.first()`, `.last()`, `.copy()`, `.slice(index_from, index_to)`, `.concat(id2)`,
`.includes(value)`, `.indexof(value)`, `.lastindexof(value)`, bool/int/float-only
`.every()`/`.some()`, and numeric-only
`.binary_search(value)`/`.binary_search_leftmost(value)`/
`.binary_search_rightmost(value)`/`.abs()`/`.min(nth?)`/`.max(nth?)`/`.sum()`/
`.avg()`/`.range()`/`.median()`/`.mode()`/`.percentile_nearest_rank(percentage)`/`.percentile_linear_interpolation(percentage)`/`.percentrank(index)`/`.covariance(id2, biased?)`/`.standardize()`/`.variance(biased?)`/`.stdev(biased?)`, plus int/float/string `.sort_indices(order?)`, all-scalar `.join(separator?)`, and terminal top-level `.clear()`/`.reverse()`/`.pop()`/`.shift()`/`.remove(index)`/`.push(value)`/`.unshift(value)`/`.insert(index, value)`/`.set(index, value)`/`.fill(value, index_from?, index_to?)`/`.sort(order?)`. Only `.copy()`, `.slice(index_from, index_to)`, `.concat(id2)`, numeric `.abs()` and
`.standardize()`, and numeric-or-string `.sort_indices(order?)` may continue
into another allowed array chain; the other
other twenty-nine value results and the eight `void` mutations are terminal.
`str.split` produces
`array<string>` and
`ta.pivot_point_levels` produces `array<float>`. `matrix.row` and `matrix.col`
produce independent element-array snapshots for the existing
`matrix<float>`, `matrix<int>`, `matrix<bool>`, `matrix<string>`, and
`matrix<color>` subsets; `matrix.eigenvalues` produces an independent
`array<float>` for its existing supported numeric-matrix subset. `map.keys`
and `map.values` produce independent insertion-order snapshots whose element
kind matches the key or value side of the existing
`map<int|float|bool|string|color, int|float|bool|string|color>` subset.
Direct helpers preserve the producers' existing empty/`na`, negative-index,
bounds-error, and element-kind behavior, and postfix copies remain independent
of the producer snapshot. A following dynamic exception marks
namespace-qualified `matrix.mult(...)` with `$builtin_matrix_result` and then
dispatches by its resolved `MatrixMult` return type. Matrix-by-array,
array-by-matrix, and array-by-array results resolve to `array<float>` and may
use `.size()`, `.get(index)`, `.first()`, `.last()`, `.copy()`, `.slice(index_from, index_to)`, `.concat(id2)`,
`.includes(value)`, `.indexof(value)`, `.lastindexof(value)`, `.every()`, `.some()`, and
`.binary_search(value)`/`.binary_search_leftmost(value)`/
`.binary_search_rightmost(value)`/`.abs()`/`.min(nth?)`/`.max(nth?)`/`.sum()`/
`.avg()`/`.range()`/`.median()`/`.mode()`/`.percentile_nearest_rank(percentage)`/`.percentile_linear_interpolation(percentage)`/`.percentrank(index)`/`.covariance(id2, biased?)`/`.standardize()`/`.variance(biased?)`/`.stdev(biased?)`/`.sort_indices(order?)` plus terminal `.clear()`/`.reverse()`/`.pop()`/`.shift()`/`.remove(index)`/`.push(value)`/`.unshift(value)`/`.insert(index, value)`/`.set(index, value)`/`.fill(value, index_from?, index_to?)`/`.sort(order?)`.
Matrix-by-matrix, matrix-by-scalar, and scalar-by-matrix results resolve to
`matrix<float>` and may use `.rows()`, `.columns()`, `.elements_count()`,
`.get(row, column)`, `.copy()`, `.row(index)`, `.col(index)`, and numeric-only
`.eigenvalues()`, `.is_zero()`, `.is_binary()`, `.is_diagonal()`,
`.is_identity()`, `.is_symmetric()`, `.is_antisymmetric()`, and
`.is_stochastic()`, plus numeric-only terminal
`.sum()`/`.avg()`/`.min()`/`.max()`/`.mode()`/`.trace()`/`.det()`/`.rank()` and
all-kind terminal `.is_square()`. Int inputs still produce float collection results. Matrix
`.copy()` continues on the matrix-result path;
`.row(index)` and `.col(index)` return fresh element-kind-preserving scalar arrays and switch
to the array-result path; `.eigenvalues()` retains the existing numeric check,
square-matrix runtime boundary, and fresh `array<float>` result before switching
to `.size()`/`.get()`/`.first()`/`.last()`/`.copy()`/`.slice(index_from, index_to)`/`.concat(id2)`/`.includes(value)`/
`.indexof(value)`/`.lastindexof(value)`/`.every()`/`.some()`/`.binary_search(value)`/
`.binary_search_leftmost(value)`/`.binary_search_rightmost(value)`/`.abs()`/
`.min(nth?)`/`.max(nth?)`/`.sum()`/`.avg()`/`.range()`/`.median()`/`.mode()`/`.percentile_nearest_rank(percentage)`/`.percentile_linear_interpolation(percentage)`/`.percentrank(index)`/`.covariance(id2, biased?)`/`.variance(biased?)`/`.stdev(biased?)`/`.join(separator?)` terminal reads plus transforming `.standardize()` and `.sort_indices(order?)` and terminal `.clear()`/`.reverse()`/`.pop()`/`.shift()`/`.remove(index)`/`.push(value)`/`.unshift(value)`/`.insert(index, value)`/`.set(index, value)`/`.fill(value, index_from?, index_to?)`/`.sort(order?)`, with copy/slice/concat/abs/standardize/sort_indices array continuation and terminal read/search/aggregate/mutation checks. `.is_square()`
returns the ordinary simple bool for every
supported concrete matrix kind and is terminal without a result-prefix
transition. Numeric-only `.is_zero()` retains the ordinary exact-zero,
zero-element, `na`-cell, and upstream-`na` result rules and is likewise
terminal without a prefix transition. Numeric-only `.is_binary()` preserves
the corresponding strict 0-or-1, empty, `na`-cell, and upstream-`na` rules and
is terminal as well. Numeric-only `.is_diagonal()` retains rectangular
support, arbitrary main-diagonal cells, exact-zero off-diagonal cells, empty
true, and upstream-`na` propagation, and is terminal as well. Numeric-only
`.is_identity()` adds square shape, exact-one main diagonal,
exact-zero off-diagonal cells, false for every `na` cell, empty true, and
upstream-`na` propagation, and is terminal. Numeric-only `.is_symmetric()`
requires square shape and exact transposed-pair
equality, returns false for every `na`, true for empty 0×0, propagates upstream
`na`, and is terminal. Numeric-only `.is_antisymmetric()` requires square
shape, an exact-zero main diagonal, and exact negation across transposed pairs,
returns false for every `na`, true for empty 0×0, propagates upstream `na`, and
is terminal. Numeric-only `.is_stochastic()` requires a non-empty matrix of
finite non-negative values and accepts either exact unit row sums or exact unit
column sums; empty matrices and invalid or negative cells are false, upstream
`na` propagates, and the reader is terminal. Numeric-only `.sum()` returns a
fixed `series float`, ignores `na` cells, returns `na` for empty, all-`na`, or
non-finite results, propagates upstream `na`, and is terminal. Numeric-only
`.avg()` shares the fixed `series float` terminal contract,
averages only non-`na` numeric cells, and returns `na` for empty, all-`na`,
non-finite, or upstream-`na` results.
Numeric-only `.min()` shares the fixed `series float` terminal contract, scans
only non-`na` numeric cells, and returns `na` for empty, all-`na`, non-finite,
or upstream-`na` results.
Numeric-only `.max()` mirrors `.min()` with the selected maximum and otherwise
retains the same fixed `series float`, `na`, non-finite, upstream-`na`, and
terminal rules.
Numeric-only `.mode()` returns a fixed `series float`, ignores `na` cells,
selects the smallest value among equally frequent repeats, and returns `na`
for empty, all-`na`, no-repeat, selected non-finite, or upstream-`na` results;
it is terminal.
Numeric-only `.trace()` returns a fixed `series float`, sums non-`na` main-
diagonal cells over `min(rows, columns)`, and returns `na` for an empty/all-
`na` diagonal, non-finite sum, or upstream-`na` result; it is terminal.
Numeric-only `.det()` returns a fixed `series float`, retains the runtime
square-matrix error, returns `1.0` for `0 x 0`, zero for singular matrices, and
`na` for invalid cells, non-finite results, or upstream `na`; it is terminal
and adds no static shape inference.
Numeric-only `.rank()` returns a fixed `series int`, supports rectangular and
singular matrices, returns `0` for zero-element matrices, and returns `na` for
invalid/non-finite cells or upstream `na`; it is terminal.
Every concrete matrix call result also admits terminal
`.set(row, column, value)`. It retains the ordinary simple-int row/column and
element-kind-compatible value checks, mutates alias-returning local UDF or user
method results in place, mutates only the independent result for fresh
namespace, bound-transform, imported-function, or imported-method producers,
returns `void`, and cannot continue. An upstream-`na` result evaluates the
value and no-ops; bounds errors and UDF side-effect rejection are unchanged.
Every concrete matrix call result also admits terminal `.fill(value)`. It
validates the receiver's float/int/bool/string/color element kind, replaces
every cell, mutates local UDF/user-method aliases in place, and confines fresh
namespace, bound-transform, imported-function, or imported-method writes to
the transient result. It returns `void` and cannot continue; empty and
upstream-`na` no-op behavior, value evaluation, invalid type/arity, and UDF
side-effect rejection are unchanged.
Every concrete matrix call result also admits terminal `.reverse()`. It
reverses the row-major cell sequence without changing shape, mutates local
UDF/user-method aliases in place, and confines fresh namespace, bound-
transform, imported-function, or imported-method writes to the transient
result. It returns `void` and cannot continue; empty/upstream-`na`, invalid
arity, and UDF side-effect behavior are unchanged.
Every concrete matrix call result also admits terminal
`.reshape(rows, columns)`. It preserves row-major cells, validates simple-int
non-negative dimensions with an unchanged element count, mutates local UDF/
user-method alias shape in place, and confines fresh producer shape changes to
the transient result. It returns `void` and cannot continue; upstream-`na`
dimension evaluation, negative/`na` dimensions, count mismatch, invalid arity/
type, and UDF side-effect behavior are unchanged.
Every concrete matrix call result also admits terminal
`.swap_rows(row1, row2)`. It preserves shape and concrete element kind,
validates two simple-int row indexes, swaps the selected rows in place, mutates
local UDF/user-method aliases, and isolates fresh producer writes. It returns
`void` and cannot continue; same-index no-op, bounds/`na` index errors,
upstream-`na` argument evaluation, invalid type/arity, and UDF side-effect
behavior are unchanged.
Every concrete matrix call result also admits terminal
`.swap_columns(column1, column2)`. It preserves shape and concrete element
kind, validates two simple-int column indexes, swaps the selected columns in
place, mutates local UDF/user-method aliases, and isolates fresh producer
writes. It returns `void` and cannot continue; same-index no-op, bounds/`na`
index errors, upstream-`na` argument evaluation, invalid type/arity, and UDF
side-effect behavior are unchanged.
Every concrete matrix call result also admits terminal `.remove_row(row)`. It
validates one simple-int row index and removes the selected complete row,
including from a zero-column matrix, while preserving column count and
concrete element kind. It mutates local UDF/user-method aliases and isolates
fresh producer shape changes. It returns `void` and cannot continue; bounds/
`na` index errors, upstream-`na` argument evaluation, invalid type/arity, and
UDF side-effect behavior are unchanged.
Every concrete matrix call result also admits terminal `.remove_col(column)`.
It validates one simple-int column index and removes the selected complete
column, including from a zero-row matrix, while preserving row count and
concrete element kind. It mutates local UDF/user-method aliases and isolates
fresh producer shape changes. It returns `void` and cannot continue; bounds/
`na` index errors, upstream-`na` argument evaluation, invalid type/arity, and
UDF side-effect behavior are unchanged.
Every concrete matrix call result also admits terminal
`.add_row(row, array_id)`. It validates a simple-int insertion index and an
element-kind-matched array, copies the array into a complete new row—including
for a zero-column matrix—while preserving column count and concrete element
kind. It mutates local UDF/user-method aliases and isolates fresh producer
shape changes. It returns `void` and cannot continue; `0..=rows` bounds/`na`
index errors, array-size and cell-budget errors, upstream-`na` evaluation,
invalid type/arity, and UDF side-effect behavior are unchanged.
Every concrete matrix call result also admits terminal
`.add_col(column, array_id)`. It validates a simple-int insertion index and an
element-kind-matched array, copies the array into a complete new column—
including for a zero-row matrix—while preserving row count and concrete
element kind. It mutates local UDF/user-method aliases and isolates fresh
producer shape changes. It returns `void` and cannot continue; `0..=columns`
bounds/`na` index errors, array-size and cell-budget errors, upstream-`na`
evaluation, invalid type/arity, and UDF side-effect behavior are unchanged.
Every concrete numeric matrix call result also admits terminal
`.sort(column?, order?)`. It defaults to column 0 and ascending order, reorders
complete rows while preserving shape and element kind, keeps equal-key rows
stable, and places `na` last ascending and first descending. Local UDF/user-
method aliases mutate while fresh producers remain isolated. It returns `void`
and cannot continue; column bounds/`na`, unsupported-order, upstream-`na`,
invalid type/arity, non-numeric receiver, and UDF side-effect behavior retain
ordinary `matrix.sort` boundaries.
Matrix-valued `.transpose()` accepts all supported matrix element kinds,
returns an independent matrix with swapped row/column counts, propagates
upstream `na`, and retains the matrix-result prefix for `.copy()`, repeated
`.transpose()`, or any supported matrix reader.
Matrix-valued `.submatrix(...)` accepts those element kinds, returns an
independent optional/default half-open range, preserves empty row/column
shapes, propagates upstream `na`, and retains the same result prefix.
Numeric matrix-valued `.inv()` always returns an independent fixed
`matrix<float>`, preserves square shape for invertible inputs, returns empty
`0 x 0`, yields `na` for singular, invalid-cell, non-finite, or upstream-`na`
inputs, and retains the same prefix. Non-square inputs retain the ordinary
runtime shape error.
Numeric matrix-valued `.pinv()` always returns an independent fixed
`matrix<float>`, swaps rectangular row/column counts, preserves singular
matrix-valued results and swapped zero-cell shapes, yields `na` for invalid-
cell, non-finite, or upstream-`na` inputs, and retains the same prefix.
Numeric matrix-valued `.eigenvectors()` always returns an independent fixed
`matrix<float>`, preserves square shape for a complete real eigenvector basis,
returns empty `0 x 0`, retains the runtime non-square error, yields `na` for
invalid-cell, non-finite, non-real, incomplete, or upstream-`na` results, and
retains the same prefix.
Numeric matrix-valued `.pow(power)` always returns an independent fixed
`matrix<float>`, retains the simple-int argument gate and runtime square-matrix
boundary, supports identity/copy/positive powers and empty `0 x 0`, preserves
`na` cells for positive powers, retains negative and `na` power errors, and
keeps the same prefix.
Numeric matrix-valued `.kron(other)` always returns an independent fixed
`matrix<float>` after the numeric-matrix operand check, multiplies both source
row and column dimensions, preserves `na` cells and zero dimensions, propagates
upstream `na`, retains the matrix cell-budget error, and keeps the same prefix.
Numeric matrix-valued `.diff(other)` always returns an independent fixed
`matrix<float>` after the numeric-matrix-or-scalar operand check, preserves the
receiver shape and left-to-right subtraction, propagates `na` cells, `na`
scalars, and upstream `na`, preserves zero dimensions, retains the matching-
shape runtime error for matrix operands, and keeps the same prefix.
Numeric matrix-valued `.mult(other)` retains the numeric matrix/scalar/array
operand gate and resolves each overload before continuing. Matrix operands
return an independent `matrix<float>` with receiver rows and operand columns,
scalar operands return an independent receiver-shaped `matrix<float>`, and
numeric-array operands return an independent `array<float>` with one value per
receiver row. The resolved result selects the closed matrix or array helper
set. Multiplication order, `na` propagation, zero inner dimensions, matrix
cell limits, matrix dimension checks, and vector-length checks are unchanged.
Other terminal readers, invalid arity or argument types, wrong-result helpers,
broader postfix helpers, and mutation other than `.set(...)`/`.fill(...)`/`.reverse()`/`.reshape(...)`/`.add_row(...)`/`.add_col(...)`/`.sort(...)`/`.swap_rows(...)`/`.swap_columns(...)`/`.remove_row(...)`/`.remove_col(...)` fail closed.
Exact namespace `matrix.copy(values)` results also
use `$builtin_matrix_result`, preserve the source's float/int/bool/string/color
matrix kind through `SameAsArg`, and admit the same forty-four matrix helpers subject
to the numeric eigenvalue, value-predicate, and aggregate checks, with the same
matrix-copy/array-result and terminal-scalar-reader continuation rules. Exact namespace
`matrix.transpose(values)`
shares that contract, preserves the source's float/int/bool/string/color matrix
kind through `SameAsArg`, swaps row and column counts, and returns independent
storage. Exact namespace `matrix.submatrix(values, ...)` likewise preserves the
source kind through `SameAsArg`, returns an independent half-open range with
default full bounds and empty row/column slices, and shares the seven all-kind
helpers plus `.diff(other)`, `.eigenvectors()`, `.inv()`, `.kron(other)`, `.mult(other)`, `.pinv()`, and `.pow(power)` for numeric results. Exact namespace `matrix.kron(left, right)` returns a fixed
`matrix<float>` result for float/int numeric inputs, expands both dimensions,
preserves `na` and zero-dimension behavior, and admits only that same helper
set. Exact namespace `matrix.diff(left, right)` returns fixed `matrix<float>`
results for matrix-matrix, matrix-scalar, and scalar-matrix numeric operands,
preserving the selected matrix shape and operand direction, and admits the
same fourteen helpers. Exact namespace `matrix.pow(values, power)` returns a
fixed square `matrix<float>` for numeric matrices and simple-int powers,
preserves identity/copy/positive-power semantics, and admits those fourteen
helpers. Exact namespace `matrix.inv(values)` returns an independent square
`matrix<float>` for invertible numeric matrices, an empty `0 x 0` matrix for
empty input, and `na` for singular or invalid-cell inputs, while admitting the
same fourteen helpers. Exact namespace `matrix.pinv(values)` returns an
independent fixed `matrix<float>` pseudo-inverse for numeric matrices, swaps
rectangular row/column counts, preserves singular matrix-valued results,
returns swapped zero-cell shapes, and yields `na` for invalid-cell inputs,
while admitting the same fourteen helpers. Exact namespace
`matrix.eigenvectors(values)` returns an independent square `matrix<float>`
whose columns are real eigenvectors for numeric square matrices, returns an
empty `0 x 0` matrix for empty input, and yields `na` for invalid-cell,
non-real, or incomplete results, while admitting the same fourteen helpers.
The five exact `matrix.new<float|int|bool|string|color>` templates enter the
same path, preserve their element kind, requested shape, initial/default-`na`
cells, fresh allocation, and copy independence. All five kinds admit the same
seven helpers, while numeric templates additionally admit `.inv()` and
`.pinv()`. Invalid
constructor arguments retain their existing diagnostics.
Exact scalar `map.new<K,V>` templates enter `$builtin_map_result`, preserve the
known key/value kinds and fresh-empty allocation, and admit only direct
`.size()`, `.get(key)`, `.contains(key)`, and `.copy()` with copy-only
continuation. Direct mutation, `keys()`/`values()`, and unsupported templates
remain gated. Exact namespace `map.copy(existing)` results enter the same path,
retain the source template and entries in an independent backing store, and
admit the same helpers and copy-only continuation. Non-map inputs and direct
mutation or `keys()`/`values()` remain gated.
The existing bound-receiver
`matrix_id.mult(array).size()` path is unchanged, while direct helpers on bound
matrix-returning `matrix_id.copy()` results now admit
`.rows()`/`.columns()`/`.elements_count()`/`.get(row, column)`/`.copy()`/
`.submatrix(...)`/`.transpose()`, plus numeric `.diff(other)`/`.eigenvectors()`/
`.inv()`/`.kron(other)`/`.mult(other)`/`.pinv()`/`.pow(power)`, with
copy/diff/eigenvectors/inv/kron/mult/pinv/pow/submatrix/transpose continuation
when `matrix_id` has a
concrete supported matrix kind.
Bound `matrix_id.transpose()` results admit the same helpers, preserve element
kind, swap row/column shape, and return independent storage. Direct helpers on
bound `matrix_id.submatrix(...)` results admit the same helpers, preserve
element kind, select independent half-open ranges with default/empty ranges,
and keep copy/diff/eigenvectors/inv/kron/mult/pinv/pow/submatrix/transpose continuation. Direct helpers on bound
numeric `matrix_id.kron(other)` results admit the same helpers, expand both
dimensions, resolve to independent `matrix<float>` storage, and keep
copy/diff/eigenvectors/inv/kron/mult/pinv/pow/submatrix/transpose
continuation. Direct helpers on bound matrix-valued
`matrix_id.mult(other)` results admit the same helpers for matrix or scalar
operands, preserve multiplied or scalar-selected shape, and resolve to
independent `matrix<float>` storage; its array-result overloads retain array-
helper dispatch. Numeric `matrix_id.diff(other)`, `matrix_id.pow(...)`,
`matrix_id.inv()`, `matrix_id.pinv()`, and `matrix_id.eigenvectors()` results
likewise admit the closed matrix helper set at their established result
boundaries. Unqualified local-UDF results with a concrete supported matrix kind
also admit that set with copy/diff/eigenvectors/inv/kron/mult/pinv/pow/submatrix/transpose continuation and call-specific result kinds.
Local and imported user-method results with a concrete supported matrix kind
also admit that set across receiver-style, qualified, constructor-receiver,
block/nested/control-flow, and copy/diff/eigenvectors/inv/kron/mult/pinv/pow/submatrix/transpose-continuation paths. Remaining
unregistered or unresolved user-function and unresolved/non-matrix method
results,
unsupported `map.new` and `matrix.new` templates, any other namespace
or non-producer member,
and postfix mutation other than `.concat(id2)`/`.clear()`/`.reverse()`/`.pop()`/`.shift()`/`.remove(index)`/`.push(value)`/`.unshift(value)`/`.insert(index, value)`/`.set(index, value)`/`.fill(value, index_from?, index_to?)`/`.sort(order?)` also stay outside this set. The built-in lexical prefixes
`str`, `ta`, `matrix`, and `map` stay reserved for this recognition and cannot
be hijacked by same-named user/import qualifiers. This slice adds no UDT or
imported-type identity flow and does not change the public runtime, analysis,
or matrix JSON schemas.

`max_bars_back` is partial. Declaration-level
`indicator(..., max_bars_back=N)` and `strategy(..., max_bars_back=N)` apply a
global constant non-negative retention bound for dynamic history reads,
including supported constant integer expressions, pure UDF-returned constant
length values, prior named const int alias-chain values, and nested known
results from the exact `int`, `float`, `math.min`, `math.max`, `math.abs`,
`math.floor`, `math.ceil`, and `math.trunc` scalar-call whitelist.
Statement-form
`max_bars_back(source, N)` helper calls are fixture-backed at top level and in
the supported block, `for`/`for...in`/`while` statement-body, switch,
block-expression, call-argument block, collection mutation argument block,
block-result nested expression, and loop-expression result contexts for
built-in, derived, or alias-chain declared simple series numeric identifiers plus direct series
numeric expressions, with stable pure unary/binary/ternary expression identity
reused for matching history reads, including builtin qualified constants/simple
metadata, bar/session flags, direct-constructor local or imported scalar-tree UDT scalar field expressions including nested field paths, positional, fixed-arity named, and signature-bound
fully named or mixed variadic stateless pure math calls, fixed-arity pure `nz`
source-helper calls including named/reordered `replacement`, pure numeric cast
calls, unreassigned pure scalar series declaration aliases, and expression-body
or pure expression-statement-prefixed normal typed or untyped local-alias block-body parameterized pure UDF calls, including nested pure UDF calls and direct-constructor local or imported scalar-tree UDT-argument scalar-field pure UDF calls including named/reordered UDF arguments, direct-constructor UDT argument expressions, nested scalar field paths, and nested pure UDF passthrough over those paths including named/reordered arguments and direct-constructor UDT argument expressions, plus receiver-unused parameterized pure user method calls, direct-constructor local or imported scalar-tree receiver scalar-field pure user method calls through direct reads or block-local receiver aliases or nested field aliases including nested scalar field paths, alias-qualified imported method calls with bound or direct-constructor receiver expressions and scalar-tree UDT argument field paths including named/reordered method arguments and nested method passthrough over those paths including named/reordered arguments and direct-constructor UDT argument expressions, and direct-constructor local or imported scalar-tree UDT-argument scalar-field pure user method calls including local named/reordered method arguments, direct-constructor UDT argument expressions, nested scalar field paths, and nested pure user method passthrough over those paths including named/reordered arguments and direct-constructor UDT argument expressions. Helper calls accept positional or named arguments,
including reordered `source`/`num` arguments, support the same constant length
subset, apply per-series retention bounds, merge repeated calls by the largest
declared bound, and report effective-window runtime/profile misses for dynamic
offsets beyond the retained bound. Non-series or non-numeric sources,
non-constant lengths, negative lengths, oversized lengths, and
declaration-value calls are rejected.

Series history offsets are partial. Dynamic integer offsets are evaluated at
runtime with full-history retention up to the runtime cap, and returned `na`
offsets evaluate the source expression on the current bar before returning `na`,
including stateful built-in source callsites. Constant non-negative offsets may
also use nested or cast-wrapped known results from the exact scalar-call
whitelist above. Negative values produced by those calls are rejected with the
same `negative_history_offset` boundary as literal and named-const negatives;
runtime-pure calls outside the whitelist remain dynamic/unknown rather than
being folded implicitly.
Fixture-backed sources include direct expressions, branches, `for`/`for...in`/
`while` loops, switch arms, UDF parameters, UDF-returned offsets and series
values, method-returned offsets and series values, and supported built-in
returned offsets.

## Strategy Runtime Contract

Phase G marks `strategy` as partial. The executable subset accepts
`strategy(title, shorttitle, overlay, max_bars_back, initial_capital, currency,
default_qty_type, default_qty_value, commission_type, commission_value,
slippage, backtest_fill_limits_assumption, margin_long, margin_short,
pyramiding, close_entries_rule, named max_labels_count, named max_boxes_count, named max_lines_count, named max_polylines_count)` where
`initial_capital` must be a positive const numeric value when provided. Phase L
accepts `default_qty_type=strategy.fixed` with positive const numeric
`default_qty_value`; Strategy Internal Stage 12 accepts
`default_qty_type=strategy.cash` with positive const numeric
`default_qty_value`, resolving omitted entry `qty` at placement time as cash
divided by current close under the current no-currency-conversion boundary;
`currency=currency.NONE` is accepted as the explicit form of that default
no-conversion account-currency path;
Stage 7 Slice 31 accepts `default_qty_type=strategy.percent_of_equity` with
positive const numeric `default_qty_value`, resolving omitted entry `qty` at
placement time from the current supported equity and current close.
`strategy.default_entry_qty(fill_price)` exposes these fixed, cash, and
percent-of-equity calculations as a read-only strategy-mode series float
without placing an order or adding position-reversal quantity. It supports
direct, named, UDF, and history reads. Cash and percent modes return `na` for a
non-positive or non-finite price, and percent sizing does the same for
non-positive or non-finite supported equity. Indicator use, requested-context
use, currency conversion, symbol point value, precision, and lot-step handling
remain unsupported, and no public schema field is added. Margin
parameters currently support
declaration/IR storage, long-only `strategy.opentrades.capital_held`, and
long-entry affordability checks for the supported entry subset when explicit
active `margin_long` is configured. They also enable the first long-only forced
liquidation subset using `bar.low`, the documented available-funds algorithm,
and whole-unit truncation. `strategy.margin_liquidation_price` exposes the
current long-only margin boundary price for active `margin_long` positions.
They do not enable short margin behavior, margin-specific public schema
expansion, or symbol tick rounding for the liquidation price. Stage 13 Slice 10
accepts positive integer
const `pyramiding` values for same-direction long `strategy.entry()` market
entries, with the default staying at `1`; `strategy(...,
close_entries_rule="FIFO")` and `strategy(..., close_entries_rule="ANY")` are
accepted close-entry allocation settings, stored in strategy settings, and
fixture-backed for current long-only FIFO close/exit allocation plus id-specific
`"ANY"` `strategy.close(id)` and `strategy.exit(..., from_entry=id)` allocation,
including same-entry-id partial exit allocation in stable ledger order.
Omitted-`from_entry` exits and `strategy.close_all()` stay on the FIFO path.
Fixture-backed market-long
`strategy.order(id, strategy.long, qty=...)`, or omitted-qty long orders using
the configured default quantity, add to existing long exposure without consuming
the `strategy.entry()` pyramiding limit. Fixture-backed limit-long
`strategy.order(id, strategy.long, qty=..., limit=price)` uses the supported
long limit timing model while also bypassing that limit, and omitted long `qty`
uses the configured default quantity at placement time. Fixture-backed stop-long
`strategy.order(id, strategy.long, qty=..., stop=price)` uses the supported long
stop timing model while also bypassing that limit, and omitted long `qty` uses
the configured default quantity at placement time. Fixture-backed
stop-limit-long
`strategy.order(id, strategy.long, qty=..., stop=stop_price, limit=limit_price)`
uses the supported long stop-limit activation/fill timing model while also
bypassing that limit, and omitted long `qty` uses the configured default
quantity at placement time. Reduce-only market
`strategy.order(id, strategy.short, qty=...)` can reduce existing long exposure
without opening shorts; while flat, it is a no-op. Omitted `qty` remains
unsupported for `strategy.short`.
The supported `strategy.order()` subset accepts `comment`, `alert_message`, and
`disable_alert` metadata; supported long order fills retain entry comments,
reduce-only short fills retain exit comments, and supported fill payloads are
exposed under `strategy.alerts`. Short entries, short exposure, reversals,
short price-based `strategy.order()` forms, same-tick price-based entry exceptions beyond the
fixture-backed long subset, and broader multi-entry exit/reporting semantics
remain outside the supported subset unless fixture-backed. Stage 13 Slice 80
adds WASM public JSON host-parity coverage for
the base `pyramiding`, `strategy.close(id)`, and `strategy.close_all()` fixtures.
Stage 13 Slice 81 adds matching Python binding public JSON host-parity coverage
for those fixtures. Stage 13 Slice 82 adds WASM public JSON host-parity coverage
for the absolute `strategy.exit(from_entry)`, relative profit
`strategy.exit(from_entry)`, and same-id fan-out fixtures from Slices 14-16.
Stage 13 Slice 83 adds matching Python binding public JSON host-parity coverage
for those fixtures. Stage 13 Slice 84 adds WASM public JSON host-parity coverage
for the bracket and trailing `strategy.exit(from_entry)` fixtures from Slices
17-18. Stage 13 Slice 85 adds matching Python binding public JSON host-parity
coverage for those fixtures. Stage 13 Slice 86 adds WASM public JSON
host-parity coverage for the current same-id omitted `profit`/`loss`
`strategy.exit` fixtures from Slices 59-60. Stage 13 Slice 87 adds matching
Python binding public JSON host-parity coverage for those fixtures. Stage 13
Slice 88 adds WASM public JSON host-parity coverage for the current same-id
omitted `loss+profit` and `stop+profit` bracket fixtures from Slices 61-62.
Stage 13 Slice 89 adds matching Python binding public JSON host-parity coverage
for those fixtures. Stage 13 Slice 90 adds WASM public JSON host-parity
coverage for the current same-id omitted `loss+limit` and `stop+limit` bracket
fixtures from Slices 63-64. Stage 13 Slice 91 adds matching Python binding
public JSON host-parity coverage for those fixtures. Stage 13 Slice 92 adds
WASM public JSON host-parity coverage for the current same-id omitted
`trail_points+trail_offset` and `trail_price+trail_offset` trailing fixtures
from Slices 65-66. Stage 13 Slice 93 adds matching Python binding public JSON
host-parity coverage for those fixtures. Stage 13 Slice 94 adds WASM public
JSON host-parity coverage for the same-id omitted `profit`/`loss`
future-entry persistence fixtures from Slices 67-68. Stage 13 Slice 95 adds
matching Python binding public JSON host-parity coverage for those fixtures.
Stage 13 Slice 96 adds WASM public JSON host-parity coverage for the same-id
omitted `loss+profit` and `stop+profit` bracket future-entry persistence
fixtures from Slices 69-70. Stage 13 Slice 97 adds matching Python binding
public JSON host-parity coverage for those fixtures. Stage 13 Slice 98 adds
WASM public JSON host-parity coverage for the same-id omitted `loss+limit` and
`stop+limit` bracket future-entry persistence fixtures from Slices 71-72. Stage
13 Slice 99 adds matching Python binding public JSON host-parity coverage for
those fixtures. Stage 13 Slice 100 adds WASM public JSON host-parity coverage
for the same-id omitted `trail_price+trail_offset` and
`trail_points+trail_offset` trailing future-entry persistence fixtures from
Slices 73-74. Stage 13 Slice 101 adds matching Python binding public JSON
host-parity coverage for those fixtures.
Stage 13 Slice 75 adds fixture-backed same-tick limit-entry
pyramiding-limit exceptions. Stage 13 Slice 76 adds matching stop-entry
exceptions. Stage 13 Slice 77 adds matching stop-limit-entry exceptions while
preserving the existing activation-bar delay. Stage 13 Slice 78 adds WASM
public JSON host-parity coverage for those same-tick long limit, stop, and
stop-limit entry fixtures. Stage 13 Slice 79 adds matching Python binding
public JSON host-parity coverage for those fixtures. Stage 13 Slice 11 adds
fixture-backed `strategy.close(id)`
matching for a requested pyramided long entry id. Stage 13 Slice 12 adds
fixture-backed `strategy.close_all()` flattening across all open long ledger
entries. Stage 13 Slice 14 adds fixture-backed absolute stop/limit
`strategy.exit` matching by requested open pyramided long entry id. Stage 13
Slice 15 adds fixture-backed single-trigger `profit`/`loss` tick conversion from
the matched open pyramided entry price. Stage 13 Slice 16 adds fixture-backed
same-entry-id `strategy.exit` allocation fan-out into one public exit order and
closed trade per matched open trade. Stage 13 Slice 17 adds fixture-backed
bracket `profit`/`loss` relative leg conversion from the matched open pyramided
entry price. Stage 13 Slice 18 adds fixture-backed trailing `trail_points`
activation conversion from the matched open pyramided entry price. Stage 13
Slice 19 adds fixture-backed omitted-`from_entry` current open-entry absolute
stop/limit all-entry exits. Stage 13 Slice 20 extends that absolute stop/limit
subset so the omitted-`from_entry` exit persists for later open long entries
until the position closes. Stage 13 Slice 21 adds fixture-backed omitted-
`from_entry` current unique-entry-id profit-tick all-entry exits. Stage 13 Slice
22 adds the symmetric fixture-backed loss-tick subset for current unique entry
ids. Stage 13 Slice 23 adds the fixture-backed omitted-`from_entry`
current unique-entry-id `loss+profit` bracket subset; broader multi-entry
`strategy.exit` semantics remain outside this claim. Stage 13 Slice 24 adds the
fixture-backed omitted-`from_entry` current unique-entry-id `stop+profit`
bracket subset. Stage 13 Slice 25 adds the fixture-backed omitted-`from_entry`
current unique-entry-id `loss+limit` bracket subset. Stage 13 Slice 26 adds the
fixture-backed omitted-`from_entry` current all-entry `stop+limit` bracket
subset. Stage 13 Slice 27 adds the fixture-backed omitted-`from_entry` current
all-entry `trail_price+trail_offset` trailing subset. Stage 13 Slice 28 adds the
fixture-backed omitted-`from_entry` current unique-entry-id
`trail_points+trail_offset` trailing subset. Stage 13 Slices 29-34 add
fixture-backed omitted-`from_entry` future-entry persistence for profit-tick,
loss-tick, `loss+profit`, `stop+profit`, `loss+limit`, and `stop+limit` exits.
Stage 13 Slice 35 adds fixture-backed omitted-`from_entry`
`trail_price+trail_offset` future-entry persistence.
Stage 13 Slice 36 adds fixture-backed omitted-`from_entry`
`trail_points+trail_offset` future-entry persistence for unique entry ids.
Stage 13 Slice 37 adds WASM public JSON host-parity coverage for the Slice 36
omitted trail-points persistence fixture without widening the runtime subset.
Stage 13 Slice 38 adds the matching Python binding public JSON host-parity
coverage for the same fixture without widening the runtime subset.
Stage 13 Slice 39 adds WASM public JSON host-parity coverage for the Slice 35
omitted trail-price persistence fixture without widening the runtime subset.
Stage 13 Slice 40 adds the matching Python binding public JSON host-parity
coverage for the same fixture without widening the runtime subset.
Stage 13 Slice 41 adds WASM public JSON host-parity coverage for the Slice 29
omitted profit persistence fixture without widening the runtime subset.
Stage 13 Slice 42 adds the matching Python binding public JSON host-parity
coverage for the same fixture without widening the runtime subset.
Stage 13 Slice 43 adds WASM public JSON host-parity coverage for the Slice 30
omitted loss persistence fixture without widening the runtime subset.
Stage 13 Slice 44 adds the matching Python binding public JSON host-parity
coverage for the same fixture without widening the runtime subset.
Stage 13 Slice 45 adds WASM public JSON host-parity coverage for the Slice 31
omitted loss+profit bracket persistence fixture without widening the runtime
subset.
Stage 13 Slice 46 adds the matching Python binding public JSON host-parity
coverage for the same fixture without widening the runtime subset.
Stage 13 Slice 47 adds WASM public JSON host-parity coverage for the Slice 32
omitted stop+profit bracket persistence fixture without widening the runtime
subset.
Stage 13 Slice 48 adds the matching Python binding public JSON host-parity
coverage for the same fixture without widening the runtime subset.
Stage 13 Slice 49 adds WASM public JSON host-parity coverage for the Slice 33
omitted loss+limit bracket persistence fixture without widening the runtime
subset.
Stage 13 Slice 50 adds the matching Python binding public JSON host-parity
coverage for the same fixture without widening the runtime subset.
Stage 13 Slice 51 adds WASM public JSON host-parity coverage for the Slice 34
omitted stop+limit bracket persistence fixture without widening the runtime
subset.
Stage 13 Slice 52 adds the matching Python binding public JSON host-parity
coverage for the same fixture without widening the runtime subset.
Stage 13 Slice 53 adds WASM public JSON host-parity coverage for the Slice 19
omitted current all-entry absolute exit fixture without widening the runtime
subset.
Stage 13 Slice 54 adds the matching Python binding public JSON host-parity
coverage for the same fixture without widening the runtime subset.
Stage 13 Slice 55 adds internal broker open-trade keys for future per-open-trade
exit identity work without widening the runtime subset.
Stage 13 Slice 56 adds internal key-scoped ledger exit allocation for future
per-open-trade exit identity work without widening the runtime subset.
Stage 13 Slice 57 adds internal pending-exit trade-key scoping for future
per-open-trade exit identity work without widening the runtime subset.
Stage 13 Slice 58 adds internal key binding for existing unique-entry-id
omitted relative exit expansion without widening the runtime subset.
Stage 13 Slice 59 adds fixture-backed current same-entry-id omitted
`from_entry` profit-tick exits, using each open trade's entry price.
Stage 13 Slice 60 adds matching fixture-backed current same-entry-id omitted
`from_entry` loss-tick exits. Stage 13 Slice 61 adds matching fixture-backed
current same-entry-id omitted `from_entry` `loss+profit` bracket exits.
Stage 13 Slice 62 adds matching fixture-backed current same-entry-id omitted
`from_entry` `stop+profit` bracket exits. Stage 13 Slice 63 adds matching
fixture-backed current same-entry-id omitted `from_entry` `loss+limit` bracket
exits. Stage 13 Slice 64 adds explicit fixture-backed current same-entry-id
omitted `from_entry` `stop+limit` bracket coverage. Stage 13 Slice 65 adds
matching fixture-backed current same-entry-id omitted `from_entry`
`trail_points+trail_offset` trailing exits. Stage 13 Slice 66 adds explicit
fixture-backed current same-entry-id omitted `from_entry`
`trail_price+trail_offset` trailing coverage. Stage 13 Slice 67 adds
fixture-backed same-entry-id omitted `from_entry` profit-tick future-entry
persistence. Stage 13 Slice 68 adds matching loss-tick future-entry
persistence. Stage 13 Slice 69 adds matching `loss+profit` bracket
future-entry persistence. Stage 13 Slice 70 adds matching `stop+profit`
bracket future-entry persistence. Stage 13 Slice 71 adds matching `loss+limit`
bracket future-entry persistence. Stage 13 Slice 72 adds explicit
`stop+limit` bracket future-entry persistence. Stage 13 Slice 73 adds explicit
`trail_price+trail_offset` future-entry persistence. Stage 13 Slice 74 adds
matching `trail_points+trail_offset` future-entry persistence.
Stage 7 Slice 17 accepts
`commission_type=strategy.commission.cash_per_contract`, and Stage 7 Slice 18
accepts `commission_type=strategy.commission.cash_per_order`, both with finite
non-negative const numeric `commission_value`. Stage 7 Slice 21 accepts
`commission_type=strategy.commission.percent` and debits
`qty * fill_price * commission_value / 100` on each supported entry and exit
fill. Stage 7 Slice 19 accepts finite non-negative integer const `slippage`
ticks using the fixed `syminfo.mintick` subset. Stage 7 Slice 20 accepts finite
non-negative integer const
`backtest_fill_limits_assumption` ticks for supported limit-order
verification. Contracts, commission modes outside the three listed above, richer
fill models, currency conversion, symbol precision rounding, and lot-step
constraints remain unsupported. Strategy
mode output includes `orders`, `trades`, `position`, `equity`, and
`diagnostics`. Equity snapshots are emitted once per historical bar with
`barIndex`, `cash`, `marketValue`, `equity`, and `netProfit`, using current
bar-close mark-to-market accounting for the long-only order subset and applying
supported commission debits and slippage-adjusted fill prices when configured.
Supported fixed-tick limit verification can delay supported long limit entry and
limit/profit exit fills while preserving the original limit fill price.
The fixed symbol metadata subset uses a default `NASDAQ:AAPL` chart identity and
now includes `syminfo.main_tickerid` plus `syminfo.mincontract` alongside the
existing ticker, exchange, currency, session, mintick, pointvalue, minmove, and
pricescale fields. Host-configurable symbol metadata remains outside the current
runtime contract.
Currency conversion, symbol precision rounding, lot-step constraints, pyramiding
behavior beyond the fixture-backed long-only subset, short exposure,
`strategy.exit` same-side/3+ trigger/invalid trailing variants, reservation
behavior outside the explicit fixed-`qty` or `qty_percent`
single-trigger/bracket/trailing subset, omitted-quantity multiple
pending exits, `strategy.order` behavior beyond the fixture-backed
long-market/price-based and reduce-only market-short subset, realtime strategy
handoff, and most strategy reporting variables remain outside the supported
matrix.

Phase L adds the first read-only strategy state variables for historical
strategy-mode scripts. `strategy.position_size` is a series float that is `0`
when flat and positive for the current long-only position. `strategy.position_avg_price`
is a series float that is `na` when flat and the current average entry price
when long. `strategy.position_entry_name` is a read-only series string that is
`na` while flat and otherwise retains the entry order ID that initially opened
the current continuous net long position. Pyramiding additions and partial
allocation closes preserve it; a flat transition clears it before a later
position establishes a new name. Direct, UDF, and history reads are supported,
while indicator use, requested-context use, and mutation remain rejected, with
no public schema expansion. The `strategy.initial_capital` slice adds a
read-only series float
that returns the configured or default broker starting capital unchanged on
every bar, including ordinary UDF and history reads, without public schema
expansion. The default account-currency slice adds
`strategy.account_currency` as a read-only simple string. Under the current
default `currency.NONE` path it inherits the fixed `syminfo.currency` value
(`"USD"`), supports simple-string consumers plus direct, UDF, and history
reads, and rejects const-string consumers, indicator use, requested-context
use, and mutation. Explicit `strategy(..., currency=currency.NONE)` selects
the same no-conversion path; other currency values, settings overrides, and
cross-currency conversion remain unsupported. The same-currency subset adds
`strategy.convert_to_account(value)` and `strategy.convert_to_symbol(value)` as
strategy-mode series-float identities. They coerce integers to floats, preserve
typed `na`, and support direct, named, UDF, and history calls while rejecting
indicator and requested-context use, with no public schema expansion.
`strategy.openprofit` is unrealized profit for the current long
position marked to the current close and is `0` when flat. `strategy.netprofit`
is cumulative realized closed-trade profit only, excluding any current open
profit. The `strategy.openprofit_percent` slice divides current unrealized
profit by realized equity (`initial_capital + strategy.netprofit`) and
multiplies by 100, returning `na` when that denominator is non-positive or
non-finite. Stage 7 Slice 22 adds `strategy.grossprofit` as cumulative positive
realized closed-trade profit only, excluding losing, flat, and current open
trades. Stage 7 Slice 23 adds `strategy.grossloss` as cumulative realized
closed-trade loss as a positive value, excluding winning, flat, and current
open trades. Stage 7 Slice 32 adds `strategy.netprofit_percent`,
`strategy.grossprofit_percent`, and `strategy.grossloss_percent` by dividing the
corresponding realized amount by `initial_capital` and multiplying by 100.
Stage 7 Slice 34 adds `strategy.buy_and_hold_return_percent` as the current
close's percentage change from the first loaded bar close, returning `na` when
that baseline is zero or non-finite.
Stage 7 Slice 24 adds `strategy.avg_trade` as average realized
profit/loss per closed trade, returning `na` until at least one trade is
closed. Stage 7 Slice 25 adds `strategy.avg_winning_trade` as average realized
profit among winning closed trades only, returning `na` until at least one
winning trade exists. Stage 7 Slice 33 adds `strategy.avg_trade_percent`,
`strategy.avg_winning_trade_percent`, and
`strategy.avg_losing_trade_percent` as averages of per-closed-trade percentage
profit/loss values, using each trade's entry price times quantity as the
denominator and returning `na` until the matching trade set exists.
winning trade is closed. Stage 7 Slice 26 adds `strategy.avg_losing_trade` as
average realized loss among losing closed trades only as a positive value,
returning `na` until at least one losing trade is closed. Stage 7 Slice 27 adds
`strategy.max_drawdown` as the maximum intrabar equity drawdown amount
over the current supported trading interval, using the supported entry equity,
the maximum equity before that entry, and the lowest low reached while the
supported position is open. Stage 7 Slice 28 adds `strategy.max_runup` as the maximum intrabar
equity run-up amount over the current supported long-only trading interval,
using the supported entry equity, the minimum equity before that entry, and the
highest high reached while the supported position is open. Stage 7 Slice 30
adds `strategy.max_runup_percent` and `strategy.max_drawdown_percent` by
dividing the supported run-up or drawdown amount by entry price times current
supported position quantity and multiplying by 100. `strategy.equity` is
cash plus current market value; without configured
commission this is equivalent to `initial_capital + strategy.netprofit +
strategy.openprofit` in the current subset, and with supported commission it
also reflects entry commission debits on open positions.
Supported market `strategy.entry`
calls create an internal pending entry and fill on the next historical bar open.
Supported long limit entries fill at the limit price before script statements
on a later historical bar when `low <= limit`. Supported long stop entries fill
at the stop price before script statements on a later historical bar when
`high >= stop`. Supported long stop-limit entries activate before script
statements on a later historical bar when `high >= stop`, do not fill on that
activation bar, and fill at the limit price before script statements on a later
historical bar when `low <= limit`. These variables reflect filled entries
before script statements on the fill bar, not on the creation or activation bar.
When explicit active `margin_long` is configured, these supported long entry
fills are rejected at the actual fill price if simulated equity cannot cover
the required margin. Rejected fills emit a strategy diagnostic, produce no
public order/position/trade event, remove the triggered pending entry, and clear
attached pending exits for that entry id.
Supported same-calculation absolute `strategy.exit` attachment may target an
active pending entry id. The attachment remains internal while the entry is
pending and can fill through the existing `strategy.exit` public order/trade
shape after the matching entry fills. Supported explicit-`from_entry` exit calls
with no matching open entry or active pending entry are no-ops and do not create
exit orders. Entry-relative pending-entry exits using `profit`, `loss`, or
`trail_points` remain unsupported.
Supported `strategy.close` and
`strategy.close_all` calls still update immediately for later statements on the
same bar. They behave like read-only series floats in supported expression
contexts, including branches, switches, loops, pure UDF arguments, and constant
history references. They do not change the public runtime JSON shape because
scripts observe them through ordinary outputs such as `plot`.

Phase O adds the first narrow strategy reporting count variables for
historical strategy-mode scripts. `strategy.closedtrades` is a read-only
series int count of closed trades recorded by the current broker state.
`strategy.closedtrades.first_index` is a read-only series int for the oldest
retained closed-trade index. It stays `0`, including before the first close,
because the current broker does not trim closed trades; platform order-limit
trimming and a nonzero retained-index offset remain unsupported.
Stage 3 adds `strategy.wintrades`, `strategy.losstrades`, and
`strategy.eventrades` as read-only series int counts of closed trades with
positive, negative, and zero realized profit.
`strategy.opentrades` is a read-only series int count of open trades in the
current long-only broker. It is `0` when flat, `1` for the default
no-pyramiding behavior, and can rise to the accepted positive `pyramiding`
limit for fixture-backed same-direction long market entries. Supported market
`strategy.entry` calls fill on the next historical bar open and update both
counts before script statements on that fill bar. Supported `strategy.close`
and `strategy.close_all` calls update both counts immediately for later
statements on the same bar. Pending `strategy.exit` fills are still evaluated
after script statements on the bar, so script reads see the count changes on
the next bar. Stage 7 Slice 0 adds
`strategy.closedtrades.entry_price(trade_num)`,
`strategy.closedtrades.exit_price(trade_num)`,
`strategy.closedtrades.entry_bar_index(trade_num)`, and
`strategy.closedtrades.exit_bar_index(trade_num)` as script-visible
strategy-mode field functions over the current closed-trade list. Stage 7 Slice
1 adds `strategy.closedtrades.size(trade_num)` and
`strategy.closedtrades.profit(trade_num)` under the same contract. Stage 7
Slice 2 adds `strategy.closedtrades.entry_time(trade_num)` and
`strategy.closedtrades.exit_time(trade_num)`. Stage 7 Slice 3 adds
`strategy.closedtrades.commission(trade_num)`, returning `0.0` without
configured commission and supported entry-plus-exit commission when configured.
Stage 7 Slice 4 adds
`strategy.closedtrades.entry_id(trade_num)`, returning the retained entry id.
Stage 7 Slice 5 adds `strategy.closedtrades.exit_id(trade_num)`, returning the
retained close or exit id. Stage 7 Slice 6 adds
`strategy.closedtrades.entry_comment(trade_num)` and
`strategy.closedtrades.exit_comment(trade_num)`, returning stored entry and
exit comments for commented fixture-backed trades without expanding public
runtime JSON. Stage 7 Slice 7 adds
`strategy.opentrades.entry_price(trade_num)`, returning the current supported
long position's entry price for `trade_num == 0`. Stage 7 Slice 8 adds
`strategy.opentrades.entry_bar_index(trade_num)`, returning the current
supported long position's entry fill bar for `trade_num == 0`. Stage 7 Slice 9
adds `strategy.opentrades.entry_time(trade_num)`, returning the current
supported long position's entry fill timestamp for `trade_num == 0`. Stage 7
Slice 10 adds `strategy.opentrades.size(trade_num)`, returning the current
supported long position size for `trade_num == 0`. Stage 7 Slice 11 adds
`strategy.opentrades.profit(trade_num)`, returning the current close-based
floating profit for that same supported open position. Stage 7 Slice 12 adds
`strategy.opentrades.entry_id(trade_num)`, returning the retained entry id for
that same supported open position. Stage 7 Slice 13 adds
`strategy.opentrades.commission(trade_num)`, returning `0.0` without configured
commission and the selected open trade's supported entry commission when
configured.
Stage 7 Slice 14
adds `strategy.opentrades.max_runup(trade_num)`, returning the largest
high-based favorable excursion seen so far for the selected open
position. Stage 7 Slice 15 adds
`strategy.opentrades.max_drawdown(trade_num)`, returning the largest low-based
adverse excursion seen so far for the selected open trade. Stage
7 Slice 16 adds `strategy.opentrades.entry_comment(trade_num)`, returning the
stored entry comment for the current commented fixture-backed open trade without
expanding public runtime JSON. Stage 7 Slice 35 adds
`strategy.opentrades.capital_held` as a read-only variable.
The indexed trade-percentage slice adds `profit_percent`,
`max_runup_percent`, and `max_drawdown_percent` to both the
`strategy.closedtrades.*` and `strategy.opentrades.*` families. Each uses the
selected trade's entry price times absolute quantity as denominator, preserves
the existing invalid-index and flat-state `na` behavior, covers fixture-backed
pyramided long trades independently, and adds no public runtime schema fields.
In the no-margin subset it returns `na`; Stage 7 Margin Slice M2 returns
current open long market value times `margin_long / 100` when explicit active
`margin_long` is configured. Strategy Internal Margin Slice M5 adds a
long-only forced-liquidation subset: historical checks use `bar.low` before
script statements, apply the documented available-funds and four-times-cover
algorithm with temporary whole-unit truncation, and emit only existing
order/trade/position/equity output fields. Stage 7 Slice 15 adds
`strategy.closedtrades.max_runup(trade_num)`, returning the
largest high-based favorable excursion retained for the selected closed trade
quantity.
Stage 7 Slice 16 adds `strategy.closedtrades.max_drawdown(trade_num)`,
returning the largest low-based adverse excursion retained for the selected
closed trade quantity. The current long-only closed-trade field subset reads
fixture-backed pyramided closed trades by zero-based index. Stage 7 Slice 17 adds cash-per-contract commission accounting for
supported entries and exits without adding public schema fields. Stage 7 Slice
18 adds cash-per-order commission accounting under the same public contract.
Stage 7 Slice 19 adds fixed-tick slippage for supported long entry, close, and
exit fill prices without changing trigger conditions or public schema.
Stage 7 Slice 20 adds fixed-tick limit-order verification for supported long
limit entry and supported long limit/profit exit fills while preserving the
original limit fill price. Stage 7 Slice 21 adds percent commission accounting
for supported entry/exit fills under the same public contract. Stage 7 Slice 22
adds `strategy.grossprofit` as a script-visible read-only series float summing
only positive realized closed-trade profit. Stage 7 Slice 23 adds
`strategy.grossloss` as a script-visible read-only series float summing
realized closed-trade losses as positive values. Stage 7 Slice 24 adds
`strategy.avg_trade` as a script-visible read-only series float for average
realized profit/loss per closed trade. Stage 7 Slice 25 adds
`strategy.avg_winning_trade` as a script-visible read-only series float for
average realized profit among winning closed trades only. Stage 7 Slice 26
adds `strategy.avg_losing_trade` as a script-visible read-only series float for
average realized loss among losing closed trades only as a positive value.
Stage 7 Slice 27 adds `strategy.max_drawdown` as a script-visible read-only
series float for maximum intrabar equity drawdown amount. Stage 7 Slice
28 adds `strategy.max_runup` as a script-visible read-only series float for
maximum intrabar equity run-up amount. Stage 7 Slice 30 adds
`strategy.max_runup_percent` and `strategy.max_drawdown_percent` as
script-visible read-only series floats for the corresponding intrabar
percentage values.
`trade_num` is zero-based and integer-only; no matching trade, a negative
index, an out-of-range index, or a non-integer argument returns `na`. Public
open-trade records, open-trade namespace functions outside `entry_price`,
`entry_comment`, `entry_id`, `entry_bar_index`, `entry_time`, `size`, `profit`,
`profit_percent`, `commission`, `max_runup`, `max_runup_percent`,
`max_drawdown`, and `max_drawdown_percent`, closed-trade namespace functions
outside this subset, rich reporting metrics, and public output schema changes
remain out of scope.

Phase M adds the first executable `strategy.exit` subset:
`strategy.exit(id, from_entry, stop=price)` and
`strategy.exit(id, from_entry, limit=price)` for full-position exits from the
current one-net-long broker. Accepted exits create or replace one internal
pending exit for the matching entry, do not trigger on the creation or
replacement bar, and fill on a later historical bar when `low <= stop` or
`high >= limit`. The fill uses the configured exit price and is represented by
the existing strategy output fields. No public pending-order, partial-fill, or
exit-reason fields are added.

Phase N adds the first `strategy.exit` tick-distance helpers:
`strategy.exit(id, from_entry, profit=ticks)` and
`strategy.exit(id, from_entry, loss=ticks)`. The current subset accepts one
trigger family per call. Profit exits convert to a pending limit at
`strategy.position_avg_price + ticks * syminfo.mintick`; loss exits convert to
a pending stop at `strategy.position_avg_price - ticks * syminfo.mintick`.
Ticks must evaluate to a finite positive number, and the implementation uses
the same fixed default `syminfo.mintick` subset as `math.round_to_mintick`.
Converted exits reuse the Phase M pending-exit lifecycle and public strategy
output contract.

Phase R adds the first `strategy.exit` bracket subset. Supported brackets have
exactly one downside leg plus one upside leg for the current long-only broker:
`stop + limit`, `stop + profit`, `loss + limit`, and `loss + profit`. A bracket
is one broker-owned pending full-position exit. Filling either leg cancels the
other leg, emits exactly one `strategy.exit` order event, and records the closed
trade under the source entry id. If both legs are touched on the same later
eligible historical bar, the downside stop/loss leg fills first. Public runtime
JSON, Python dictionaries, and WASM JSON keep the existing strategy result
shape and runtime `schemaVersion: 3`. Same-side pairs `stop + loss` and
`limit + profit`, 3+ trigger calls, partial exits, and arbitrary future binding
for unmatched `from_entry` ids remain unsupported.

Phase S adds the first `strategy.exit` trailing-stop subset. Supported trailing
forms are exactly `trail_price + trail_offset` and
`trail_points + trail_offset` for the current long-only broker, with no fixed
`stop`, `limit`, `profit`, or `loss` arguments in the same call. `trail_price`
is the activation price. `trail_points` converts once from the current average
entry price, or from the matched open pyramided entry price when that
fixture-backed `from_entry` subset applies, using the fixed default
`syminfo.mintick`; `trail_offset` converts once to a fixed price distance. A
trailing exit starts inactive, is not
eligible on its creation or replacement bar, activates on a later bar when
`high >= activation`, never fills on the activation bar, then fills on a later
bar when `low <= active_stop` before any same-bar ratchet. When not filled, the
active stop ratchets upward to
`max(active_stop, high - offset_distance)`. The public output stays on the
existing strategy result shape and runtime `schemaVersion: 3`; there are no
public trailing-state, pending-order, or exit-reason fields. Invalid trailing
combinations remain fixture-backed unsupported.

Phase U adds fixed partial quantities to the supported `strategy.exit` trigger
shapes. `qty` is accepted on the single-trigger stop, limit, profit, and loss
forms, on the supported one-downside/one-upside bracket forms, and on the
supported trailing forms. `qty` evaluates once at placement time, must be
finite and positive, and stores an absolute requested close quantity on the
single pending exit. If omitted, the exit keeps the previous full-position
behavior. On fill, the closed quantity is `min(qty, current position size)`:
partial fills emit one existing `strategy.exit` order event and one closed
trade for the filled quantity, leave the remaining long position open at the
same average price, and clear the filled pending exit. Quantities at or above
the current position size close the full position. The public output shape and
runtime `schemaVersion: 3` are unchanged. Phase U did not add `qty_percent`,
multiple pending exits, quantity reservation, or missing-entry pre-placement.

Phase V adds percent partial quantities to the same supported `strategy.exit`
trigger shapes. `qty_percent` evaluates once at placement time, must be finite
and positive, and resolves against the current open position size to an absolute
requested close quantity. Fills use `min(resolved_qty, current position size)`,
so `qty_percent > 100` is allowed but closes no more than the current position.
Partial fills emit the same existing order/trade fields with absolute `qty`,
leave any remaining long position open at the same average price, and do not add
public pending, remaining, percent, or schema fields. Phase W adds the first
multiple-pending reservation subset for explicit fixed `qty` or `qty_percent`
single-trigger exits on the current matching long entry. Phase X extends that
reservation subset to explicit fixed `qty` or `qty_percent` one-downside plus
one-upside bracket exits. Phase Y extends the same reservation model to the
supported trailing forms. Reservations are resolved at placement time, clamped
to currently unreserved position quantity, and same-identity calls replace the
previous reservation. Single-trigger, bracket, and trailing reservations can
share the same pool. Same-side touched exits fill in placement order. If
downside stop/loss/trailing and upside limit/profit candidates are both touched
on one eligible bar, downside candidates fill on that bar in placement order and
opposite-side candidates remain pending if a long position remains. When both
legs of one bracket are touched, that bracket contributes its downside
candidate. Inactive trailing reservations activate on a later eligible bar and
never fill on the activation bar; active trailing reservations fill as downside
candidates before same-bar ratchets and otherwise ratchet upward only. Phase Z
closes the omitted-quantity boundary: omitted `qty` and omitted
`qty_percent` keep full-position one-effective-pending behavior across
supported single-trigger, bracket, and trailing forms, and a later omitted
full-position exit clears earlier explicit reservations for the current
matching long entry. `qty` and `qty_percent` in the same call remain supported
on those same trigger shapes with fixed `qty` determining the reserved or
filled quantity. Stage 9 supports same-calculation active-entry single-trigger
attachment for absolute `stop`, `limit`, and `trail_price` plus entry-relative
`profit`, `loss`, and `trail_points + trail_offset` against a matching active
pending long entry. Same-calculation active-entry `stop + profit`,
`loss + limit`, and `loss + profit` bracket attachment is also fixture-backed;
other active-entry relative bracket forms remain outside the current subset,
while multiple pending exits outside the explicit fixed-`qty` or
`qty_percent` single-trigger/bracket/trailing reservation subset remain
unsupported, including omitted-quantity multiple reservations, reservation
behavior outside that subset, and arbitrary future binding for unmatched
`from_entry` ids. Supported unmatched explicit-`from_entry` exit placements are
no-ops without public exit orders or strategy diagnostics.

The closed Phase L boundary is summarized in `docs/PHASE_L_AUDIT.md`. The
closed Phase M boundary is summarized in `docs/PHASE_M_AUDIT.md`. The closed
Phase N boundary is summarized in `docs/PHASE_N_AUDIT.md`. The closed Phase O
count-variable boundary is summarized in `docs/PHASE_O_AUDIT.md`. Phase P's
structural broker split is summarized in `docs/PHASE_P_AUDIT.md`. Phase Q's
bracket design gate is recorded in `docs/PHASE_Q_AUDIT.md`. Phase R's
fixture-backed bracket implementation is summarized in `docs/PHASE_R_AUDIT.md`.
Phase U's fixed quantity subset is summarized in `docs/PHASE_U_AUDIT.md`. Phase
V's percent quantity subset is summarized in `docs/PHASE_V_AUDIT.md`. Phase X's
bracket reservation subset is summarized in `docs/PHASE_X_AUDIT.md`. Phase Y's
trailing reservation subset is summarized in `docs/PHASE_Y_AUDIT.md`. Phase Z's
omitted-quantity boundary is summarized in `docs/PHASE_Z_AUDIT.md`. Stage 9's
active-entry single-trigger relative exit closeout is summarized in
`docs/STRATEGY_INTERNAL_STAGE9_ENTRY_RELATIVE_EXIT_AUDIT.md`. Stage 10's
active-entry relative bracket design gate is recorded in
`docs/STRATEGY_INTERNAL_STAGE10_ACTIVE_ENTRY_BRACKET_PLAN.md`.

## Source Graph Host Contract

Phase J adds a host-neutral source graph scaffold and a narrow executable
import subset. `tests/fixtures/conformance.tsv` marks `import` as `partial`
only for host-provided exact-key imports with aliases, exported const
expressions, pure exported functions, scalar-tree imported UDT constructors
with direct and nested field reads, ordinary same-imported-UDT reassignment, and
scalar-tree imported UDT typed declarations initialized or reassigned from the
same imported identity, same-imported-identity ternary, `if`, `switch`,
`while`, `for`, and `for...in` expression results, plus imported UDT UDF parameter
passthrough returns through direct, block-local alias, ternary-expression alias, final-if alias,
final-`for`, final-`for in`, final-`while`, switch-expression alias, and
nested passthrough chains over those forms, exported functions with
same-imported UDT typed parameters, and scalar-tree root-field replacement in
top-level, branch, `for`-loop, `while`-loop, and UDF-local statement contexts.
Imported pure exported UDFs and imported user methods also return
same-imported scalar-tree UDT arrays through direct or block-alias paths,
copy/new/from allocation, private nested calls, final control flow, and typed
method named/reordered arguments. Imported type positions are rewritten for the
active alias, and source-aware metadata keeps calls through two aliases of the
same physical library isolated. Tuple literals and local/imported UDF or method
tuple returns retain same-local or same-imported scalar-tree UDT-array identity
independently per destructured UDT-array slot, including direct/block/nested/
final-flow, typed-`na`, A-to-B-to-A, dual-alias, tuple-valued ordinary
declaration direct/self alias, ternary/`switch`, assigned-`if`, shadowing, and
later-destructuring paths. A declaration's UDT-array slot identity is stable
across same-identity or `na` reassignment; cross-identity direct/control-flow
reassignment and unresolved nested consumers fail closed at the root span.
Qualified user-defined UDF/method results, unqualified plain local UDF results,
the exact built-in `array.*` producer allowlist, and the cross-namespace
array-capable set in the Built-In Runtime Contract may be consumed directly
through `.size()`, `.get(index)`, `.first()`,
`.last()`, `.copy()`, `.slice(index_from, index_to)`, or `.concat(id2)` when they return a currently supported array kind,
including nested copy/read chains. The parser represents the unqualified form
with the impossible synthetic prefix `$call_result` and the built-in producer
form with `$builtin_array_result`; the former requires a plain lexical callee,
while the latter requires either the reserved lexical `array` prefix and an
exact allowlisted member or supported `array.new<T>` template, one of the
seven exact non-`array` qualified producer names. The exact
`matrix.new<float|int|bool|string|color>` templates and namespace `matrix.mult`,
`matrix.copy`, `matrix.transpose`, `matrix.submatrix`, `matrix.kron`,
`matrix.diff`, `matrix.pow`, `matrix.inv`, `matrix.pinv`, and
`matrix.eigenvectors` use the separate
`$builtin_matrix_result` prefix; semantic analysis admits the five
array helpers when its actual overload returns an array and the exact
`.rows()`/`.columns()`/`.elements_count()`/`.get(row, column)`/`.copy()`/
`.submatrix(...)`/`.transpose()` set for matrix results. `matrix.copy` always takes the matrix
branch and preserves
shape; `matrix.transpose` always takes that branch and swaps shape. Both
preserve the source's supported element kind. `matrix.submatrix` takes the same
branch and returns the selected range with that kind. `matrix.kron` also takes
the matrix branch, produces a fixed float matrix, and expands row/column shape
from its numeric operands, while `matrix.diff` produces a fixed float matrix
with the selected matrix operand's shape and left-to-right subtraction order.
`matrix.pow` produces a fixed float matrix that preserves square shape across
identity, copy, and positive powers, while `matrix.inv` preserves square shape
for invertible inputs and yields `na` for singular or invalid-cell inputs.
`matrix.pinv` swaps rectangular shape, preserves singular matrix-valued
results, returns swapped zero-cell shapes, and yields `na` for invalid-cell
inputs. `matrix.eigenvectors` preserves square shape for real complete
eigenvector results, returns empty `0 x 0`, and yields `na` for invalid-cell,
non-real, or incomplete results. The admitted `matrix.new<T>` templates retain
their float/int/bool/string/color result kind, requested shape,
initial/default-`na` cells, and fresh allocation. Only `.copy()`, `.slice(...)`,
`.concat(id2)`, plus numeric `.abs()` and `.standardize()` continue an array-result chain; matrix results
may continue through `.copy()`,
`.submatrix(...)`, or `.transpose()`, and numeric matrix results may also
continue through `.diff(other)`, `.eigenvectors()`, `.inv()`, `.kron(other)`, `.mult(other)`, `.pinv()`, or `.pow(power)`.
Exact bound matrix-receiver `values.copy()`
results preserve element kind, shape, and independent storage and admit the
same seven all-kind helpers plus `.diff(other)`, `.eigenvectors()`, `.inv()`, `.kron(other)`, `.mult(other)`, `.pinv()`, and `.pow(power)` for numeric results. Exact bound
matrix-receiver `values.transpose()` results
share that helper set, preserve element kind, swap shape, and return independent
storage. Exact bound matrix-receiver `values.submatrix(...)` results retain the
source element kind and independent selected range and share the same helper
set. Exact bound numeric-matrix-receiver `values.kron(other)` results expand
shape, return independent `matrix<float>` storage, and share the same helper
set. Exact bound numeric-matrix-receiver `values.diff(other)` results preserve
operand direction and selected matrix shape, return independent
`matrix<float>` storage, and share the same helper set. Exact bound
numeric-square-matrix-receiver `values.pow(power)` results preserve square
shape across identity, copy, and positive powers, return independent
`matrix<float>` storage, and share the same helper set. Exact bound
numeric-square-matrix-receiver `values.inv()` results preserve invertible
square shape, empty `0 x 0` results, and `na` for singular or invalid-cell
inputs, return independent `matrix<float>` storage, and share the same helper
set. Exact bound numeric-matrix-receiver `values.pinv()` results swap
rectangular shape, preserve singular matrix results and swapped zero-cell
shapes, yield `na` for invalid-cell inputs, return independent `matrix<float>`
storage, and share the same helper set. Exact bound
numeric-square-matrix-receiver `values.eigenvectors()` results preserve real
square shape, return empty `0 x 0` or `na` at the established boundaries, use
independent `matrix<float>` storage, and share the same helper set. Exact bound
numeric-matrix-receiver matrix-valued `values.mult(other)` results preserve
multiplied or scalar-selected shape, `na` and zero-inner-dimension behavior,
return independent `matrix<float>` storage, and share the same helper set while
array-result overloads retain array-helper dispatch; UDF matrix-result
receivers instead enter the same forty-four-helper closed set only for
unqualified local UDFs whose inferred result has a concrete supported matrix
kind, with numeric-only checks retained. Parameter
passthrough, block aliases, nested calls, same-kind control flow, constructed
and matrix-operation returns, named/reordered arguments, zero dimensions, and
independent copies retain their existing behavior and call-specific element
kind. Local and imported user-method results with a concrete supported matrix
kind share those helpers across receiver-style, local-type-qualified or alias-
qualified, direct-constructor-receiver, block/nested/control-flow, five-kind,
zero-dimension, dual-alias, independent-copy, and
copy/diff/eigenvectors/inv/kron/mult/pinv/pow/submatrix/transpose-continuation paths.
Registered imported pure-function results with a concrete supported matrix kind
share those helpers across alias-qualified, block/nested/control-flow, five-
kind, zero-dimension, dual-alias, independent-copy, and
copy/diff/eigenvectors/inv/kron/mult/pinv/pow/submatrix/transpose-continuation
paths. Unknown/`na`, scalar, array, map, unregistered or unresolved user-
function matrix results, broader helpers, mutation other than terminal
`.set(row, column, value)`/`.fill(value)`/`.reverse()`/`.reshape(rows, columns)`/`.swap_rows(row1, row2)`/`.swap_columns(column1, column2)`/`.remove_row(row)`, and continuation after terminal reads remain gated.
Exact supported scalar `map.new<K,V>` templates use `$builtin_map_result` and
admit `.size()`, terminal `.put(key, value)`, `.clear()`, `.remove(key)`, and
`.put_all(source)`, `.get(key)`, `.contains(key)`,
`.copy()`, `.keys()`, and `.values()`. Only `.copy()` may continue another
admitted map helper; `.put(...)`, `.clear()`, `.remove(...)`, and `.put_all(...)` return `void`
and cannot continue.
Exact namespace `map.copy(existing)` results share that path while retaining
the source key/value kinds and entries in an independent backing store. Map
mutation outside terminal `.put(...)`/`.clear()`/`.remove(...)`/`.put_all(...)`, unsupported templates, non-map copy
inputs, and other map call-result receivers remain parser/semantic boundaries.
Unqualified local-UDF results with one concrete supported scalar map template
also share those ten helpers and copy-only continuation through `$call_result`;
registered local and imported user-function results plus local and imported
user-method results with the same concrete template use the same result path.
Function calls support unqualified or alias-qualified producers; methods retain
receiver-style and local-type-qualified or alias-qualified producers, with
same-library dual-alias isolation. Unresolved or mixed-template results and
wrong-result helpers remain outside that path. Concrete key/value checks,
insertion-order-preserving replacement/append, local alias writes, fresh-result
isolation, clear/remove behavior, same-template ordered put-all merging,
and UDF-side-effect rejection
retain ordinary map mutation behavior.
Built-in-qualified/template call results outside these paths remain parser
boundaries. For UDT
arrays, the result must carry a concrete same-local or same-imported scalar-tree
identity.
`get` preserves that element identity and the existing named-index, `na`,
negative-index, and bounds semantics; `size` and `last` preserve the existing
empty/typed-`na` behavior.
An unqualified local UDF result carrying a concrete local or imported scalar
UDT identity may also invoke the existing pure user-method subset. Explicit
same-named functions and methods remain distinct from the synthetic array
helper dispatch. Conflicting identities within one scalar return or tuple slot,
non-scalar UDT-array returns, non-array/non-UDT results, unknown/`na` results
without a concrete supported type or identity, helpers outside the read-only
set, built-in-qualified/template call-result receivers outside the exact
static and dynamic collection paths, and mutation through unsupported UDF/method
side-effect contexts remain outside the supported matrix. In particular, postfix reads do
not neutralize `array.concat`'s mutation of its first input, so that producer
remains rejected inside UDFs.
Unresolved-field imported UDT constructors remain rejected with targeted
diagnostics; private library UDTs remain non-exported symbols, local/imported
structural lookalikes remain distinct assignment identities, and duplicate
exported UDT names, UDT/const name collisions, or UDT/function name collisions
are rejected through the shared export table. Scalar-tree imported UDT value
history is fixture-backed, including typed-`na` history for exported imported
UDTs whose scalar-tree metadata depends on private library UDTs. Library
declarations, imported UDT flow outside the covered same-identity scalar-tree paths,
direct private imported UDT access and imported UDT value history outside the scalar-tree metadata subset, imported UDT parameter/global field mutation
inside UDFs, nested imported field mutation, re-exports, remote lookup, and
side-effecting exported functions remain outside the supported matrix. Receiver-style and
alias-qualified scalar-tree imported UDT method calls are fixture-backed for the
current pure method subset, including named/reordered non-receiver arguments, direct same-identity, block-local alias,
final-if alias, final-for alias, final-for-in alias, final-while alias, switch-expression alias,
nested-method passthrough plus constructor returns, and method-local scalar-tree
root-field replacement.

Local user-defined types are partial. The supported subset is limited to
top-level `type` declarations with scalar int/float/bool/string/color fields,
`Type.new(...)` construction, field reads on local values, ordinary variables,
local for-expression constructor results, `var` persistence for typed local UDT declarations initialized from `na`, same-UDT constructors, same-UDT ternary, switch, if, for, for...in, and while expressions, explicitly typed
same-local scalar-tree UDT `varip` values initialized from `na`, same-UDT
constructors, same-identity aliases, or fixture-backed same-UDT ternary, switch, if, for, for...in, and while expressions, plus
direct-constructor-inferred or direct-alias-inferred same-local scalar-tree UDT `varip` values with
realtime intrabar persistence, and UDF parameter passthrough/returns through
typed or inferred positional or named arguments with direct returns,
block-local, ternary-expression, final-if, final-for, final-for-in, final-while, or switch-expression aliases, or
nested passthrough calls through those same alias forms, plus UDF construction/returns,
directly, through nested pure
constructor-helper UDF calls, or through same-local-UDT ternary, switch, final
if/else constructor branches, same-local-UDT `if` expressions, or final for
bodies, from local UDT parameter scalar fields, scalar fields read through
block-local UDT aliases of those parameters, block-local scalar aliases of
those fields, typed or inferred scalar parameters, or block-local scalar aliases of
those scalar parameters using positional or named constructor field arguments.
Local scalar fields can be reassigned in top-level, branch, `for` loop,
`while` loop, UDF-local variables, and method-local variables. Global or
parameter field mutation inside UDFs, receiver/parameter/global field mutation
inside methods, non-constructor-inferred UDT `varip`, nested-field UDT `varip`,
non-scalar local UDT value history references, UDT fields, UDT array operations beyond
same-local scalar-field `array.new<T>()` construction, `array.from`
construction with size and `array.get` field reads plus `array.set`
replacement, `array.push` append, and `array.pop`
returns, `array.shift` returns, `array.first` reads, and `array.last` reads,
plus `array.clear` reset/reuse, `array.copy` independence, `array.concat`
same-UDT append, `array.slice` parent-window read/write mirroring, and
`array.reverse` reordering, `array.fill` same-UDT replacement, UDT array
`array.join` positional stringification, local field mutation of UDT array
values with explicit same-UDT `array.set`/`set()` writeback, local pure UDF
calls that consume UDT array values, local pure method calls on UDT array values
after binding them to local variables, UDT array
`array.sort`/`array.sort_indices` by `int`, `float`, or `string` `sort_field`,
UDT array id history snapshots, ordinary `var` realtime rollback,
same-local scalar-tree UDT array `varip` backing-store handoff,
scalar-tree imported UDT constructors with direct and nested field reads, and ordinary
same-imported-UDT reassignment, scalar-tree imported UDT typed declarations
initialized or reassigned from the same imported identity, and imported UDT
ternary, `if`, `switch`, `while`, or `for` expression results whose branches resolve
to the same imported identity. Direct, block-local alias, ternary-expression alias, final-if alias,
final-`for`, final-`for in`, final-`while`, switch-expression alias, and
nested imported UDT UDF parameter passthrough returns are also fixture-backed, as are direct, nested, ternary, if, for, for-in, while, or switch imported UDT
constructor-return UDFs. Ordinary imported UDT `var` declarations and
scalar-tree imported UDT `varip` declarations are fixture-backed, as is
scalar-tree imported UDT root-field replacement in top-level, branch, `for`-loop, and
`while`-loop statement contexts plus UDF-local variable mutation in pure
functions. Receiver-style and alias-qualified scalar-tree imported UDT method calls,
including named/reordered non-receiver arguments, direct same-identity, block-local alias, final-if alias,
final-for alias, final-for-in alias, final-while alias, switch-expression alias, nested-method
passthrough plus constructor returns, and method-local scalar-tree root-field
replacement, are fixture-backed. Same-imported scalar-tree UDT
`array.from` construction is fixture-backed for size, get, first, and last field
reads plus set/set() replacement field reads, push/push() append field reads,
unshift/unshift() prepend field reads, insert/insert() insertion field reads, fill/fill() replacement field reads, join/join() positional stringification, includes/indexof/lastindexof structural equality search, sort/sort_indices by int/float/string sort_field, pop, remove, and shift return field
reads, and clear/clear() size reset plus copy/copy() independent field reads,
reverse/reverse() reordered field reads, slice/slice() window field reads, and
concat/concat() appended field reads, plus same-imported scalar-field
`array<lib.Type>`/`lib.Type[]` declarations. Broader imported UDT flow remains
outside the supported matrix.
User-defined methods are partial for pure methods on local UDT receivers with
scalar or local UDT parameters and direct UDT passthrough returns with caller-side history reads, nested scalar-tree UDT method returns with caller-side history reads, block-local
or ternary-expression receiver or local UDT parameter alias passthrough
returns, final if/else, final for, final for-in, final while, or switch-expression local UDT
alias passthrough returns, nested-method UDT parameter passthrough returns, plus local and nested scalar-tree UDT constructor returns with caller-side history reads, directly, through
nested pure constructor-helper UDF calls, or through same-local-UDT ternary,
switch, final if/else constructor branches, same-local-UDT `if` expressions,
or final for bodies, final for-in bodies, or final while bodies, from receiver or local UDT parameter scalar fields, scalar
fields read through block-local receiver or local UDT parameter aliases,
block-local scalar aliases of those fields, inferred scalar parameters, or
block-local scalar aliases of those parameters using positional or named
constructor field arguments. The receiver
is passed as the first internal parameter. Returned receiver values,
block-local or ternary-expression receiver aliases, final if/else, final for,
final for-in, final while, or switch-expression local UDT aliases, local UDT parameter
values, block-local or ternary-expression local UDT parameter aliases, or
constructed local UDT values may be assigned and field-read at the callsite.
Same-local scalar-tree UDT values read from UDT arrays may also be passed to
local pure UDFs, including passthrough and constructor-return UDFs.
Same-local scalar-tree UDT values read from UDT arrays may also be bound to
local variables and used as receivers for these local pure methods.
Same-local scalar-tree UDT array elements may also be iterated by
statement-form `for...in` loops as value-copy loop locals.
Side effects, recursion, unknown receiver types, alias-qualified imported method
receiver type mismatches, mismatched UDT parameter identity, and unsupported
parameter families remain outside the supported matrix.
The imported UDT subset is intentionally narrow: scalar-tree constructors,
direct and nested field reads, ordinary same-imported-UDT reassignment, explicit
scalar-tree typed declarations, direct UDF parameter passthrough returns
including block-local alias, ternary-expression alias, final-if alias, final-`for`, final-`for in`,
final-`while`, switch-expression alias, and nested passthrough chains, direct, nested, ternary, if, for, for-in, while, or switch constructor-return UDFs,
same-imported-identity ternary/`if`/`switch`/`while`/`for`/`for...in` results, and
scalar-tree root-field replacement in top-level, branch, `for`-loop, `while`-loop, and
UDF-local statement contexts, plus method-local scalar-tree root-field
replacement, carry source-scoped identity through semantic analysis and HIR.
Receiver-style and alias-qualified scalar-tree imported UDT method calls, including
named/reordered non-receiver arguments, direct same-identity, block-local alias, ternary-expression alias, final-if
alias, final-for alias, final-for-in alias, final-while alias, switch-expression alias,
nested-method passthrough plus
direct, nested scalar-tree, ternary, if, for, for-in, while, or switch
constructor returns, caller-side history reads from method-returned values, and
method-local scalar-tree root-field replacement, are
supported, while collections, history, nested field mutation,
UDF parameter/global field side effects, method receiver/parameter/global field
side effects, and broader imported UDT value flow remain a maintenance tail.
The closed Phase J boundary and maintenance tails are summarized in
`docs/PHASE_J_AUDIT.md`.

Hosts may pass library source text into semantic analysis as future graph input:

- CLI accepts repeated `--library-source KEY=path.pine` options for `analyze`
  and `run`. The CLI owns filesystem reads and passes source text to core.
- Python accepts `library_sources={"KEY": "source text"}` on `compile_script`,
  `analyze_script`, and `run_script`.
- WASM accepts deterministic JSON library source maps on the
  `*WithLibraries` entry points and routes them through the same shared
  `AnalysisInput` path.

Core crates must not perform filesystem, network, clock, or host registry I/O
for library resolution. Library source keys are deterministic host-provided
identifiers: empty keys, keys containing whitespace/control characters, and
duplicate keys are rejected before analysis. Cache keys include root source
name/text and every host-provided library key/name/text so future import graph
use cannot reuse stale analysis.

CLI and WASM runtime JSON must be generated through the shared runtime contract
helper so field names and nesting cannot drift. Python returns native
dictionaries, so its binding tests assert the same top-level runtime keys and
representative nested output families such as `plotShapes` and `plotCandles`.
The Phase E drawing-object scaffold adds `labels`, `lines`, `boxes`, and
`tables` as top-level runtime keys in `schemaVersion: 2`. The executable label
subset covers `label.new` creation snapshots with bar-index or bar-time x
locations, price/abovebar/belowbar y locations, official label styles, official
empty-string defaults for omitted text, `color.blue` and `color.white` defaults
for omitted color/textcolor values, and host-neutral text metadata, plus the
`chart.point` point/text overload using
point indexes or times based on `xloc`, selected `label.set_*` mutators including
fixture-backed `label.set_x`, `label.set_y`, `label.set_xy`, `label.set_text`,
`label.set_point`, and `label.set_size` mutations from ordinary and independent
while-loop control-flow blocks, where `label.set_point` selects `point.index`
or `point.time` from the point based on the label's current `xloc` and uses
`point.price` for y, fixture-backed `label.set_color`, `label.set_textcolor`,
`label.set_style`, `label.set_tooltip`, `label.set_textalign`,
`label.set_text_font_family`, and `label.set_text_formatting` mutations from
ordinary and independent while-loop control-flow blocks,
fixture-backed x-location snapshot mutation for `label.set_xloc`, including
ordinary and independent while-loop control-flow mutation coverage, and
y-location snapshot mutation for `label.set_yloc`, including ordinary and
independent while-loop control-flow mutation coverage, text-alignment snapshot
mutation for `label.set_textalign`, text font-family snapshot mutation for
`label.set_text_font_family`, text-formatting snapshot mutation for
`label.set_text_formatting`, `label.delete` deletion snapshots, including
ordinary and independent while-loop control-flow deletion coverage,
fixture-backed cloning with `label.copy`, including ordinary and independent
while-loop control-flow cloning coverage, and the fixture-backed `label.get_x`,
`label.get_y`, and
`label.get_text` getters over the latest existing label snapshot, including
ordinary and independent while-loop control-flow read coverage for all three
getters, statement-form `array<label>` `for...in` shallow-id iteration with
getter/setter calls and setter visibility through the source array id, plus
`label.all` existing-label id reads, including ordinary and independent
while-loop control-flow read coverage, with default 50/named 1-500
`max_labels_count` oldest-active label eviction before new creation. The
executable line subset covers `line.new` x1/y1/x2/y2 creation with optional
xloc, extend, color, style, and width initialization for existing host-neutral
snapshot fields when `xloc` is omitted, `xloc.bar_index`, or `xloc.bar_time`,
with omitted color defaulting to `color.blue`, plus the `chart.point`
first_point/second_point overload using point indexes or times according to
`xloc`. It also covers selected
endpoint/color/width/style/extend mutators, `line.set_first_point` and
`line.set_second_point` using point indexes or times according to each line's
current `xloc`, and `line.set_xloc` for the `xloc.bar_index`/`xloc.bar_time`
subset that updates x1, x2, and xloc snapshots, all including ordinary
and independent while-loop control-flow mutation coverage, `line.delete`
deletion snapshots, including ordinary and independent while-loop control-flow
deletion coverage,
fixture-backed cloning with `line.copy`, including ordinary and independent
while-loop control-flow cloning coverage, statement-form `array<line>`
`for...in` shallow-id iteration with getter/setter calls and setter visibility
through the source array id, `line.all` reads from ordinary and
independent while-loop control-flow blocks, fixture-backed `line.get_x1`,
`line.get_y1`, `line.get_x2`, and `line.get_y2` reads from ordinary and
independent while-loop control-flow blocks, and fixture-backed
`line.get_price` getter over the latest existing line snapshot, including
ordinary and independent while-loop control-flow reads, with sparse snapshots
and default 50/named 1-500 `max_lines_count` eviction that appends deletion
snapshots to the oldest active line before creating new ones.
`line.get_price` uses bar-index x1/y1/x2/y2 interpolation and extrapolation and
returns `na` for `na`, deleted, vertical, nonnumeric, or time-coordinate lines;
timestamp interpolation remains unsupported. The executable box subset covers
`box.new` left/top/right/bottom creation plus `chart.point`
top_left/bottom_right creation with optional xloc, background, border, extend,
text, text-color, text-size, horizontal-alignment, vertical-alignment,
text-wrap, font-family, and text-formatting initialization for existing
host-neutral snapshot fields when `xloc` is omitted, `xloc.bar_index`, or
`xloc.bar_time`. Omitted `border_color` and `bgcolor` use the official
`color.blue` default, omitted `text_color` uses the official `color.black`
default, and omitted `text_size` uses the official `size.auto` default.
It also covers selected geometry mutators from ordinary and independent
while-loop control-flow blocks, selected background/border/extend mutators from
ordinary and independent while-loop control-flow blocks, selected
text/text-color/text-size/horizontal-alignment/vertical-alignment/text-wrap/
font-family/text-formatting mutators from ordinary and independent while-loop
control-flow blocks, and `box.set_top_left_point` plus
`box.set_bottom_right_point` using point indexes or times according to each
box's current `xloc`,
`box.set_xloc` for the `xloc.bar_index`/`xloc.bar_time` subset that updates
left, right, and xloc snapshots from ordinary and independent while-loop
control-flow blocks,
`box.delete` from ordinary and independent while-loop control-flow blocks, and
fixture-backed cloning with `box.copy` over the latest existing box
snapshot from ordinary and independent while-loop control-flow blocks, `box.all`
reads from ordinary and independent while-loop control-flow blocks after deletion, fixture-backed
`box.get_left`, `box.get_right`, `box.get_top`, and `box.get_bottom` reads from
ordinary and independent while-loop control-flow blocks after mutation, with
sparse snapshots plus default 50/named 1-500 `max_boxes_count` oldest-active
box eviction before new creation.
The executable table subset covers
`table.new` position/dimension creation with optional `bgcolor`,
`frame_color`, `frame_width`, `border_color`, and `border_width` initialization,
plus accepted `force_overlay` syntax (without public-output propagation or pane
routing),
plus `table.cell` text/background/text-color/tooltip/font-family/text-formatting
cell writes,
`table.set_position` final-position mutations, including ordinary and
independent while-loop control-flow mutation coverage,
`table.set_bgcolor` final background-color mutations, including ordinary and
independent while-loop control-flow mutation coverage,
`table.set_frame_color` final frame-color mutations, including ordinary and
independent while-loop control-flow mutation coverage,
`table.set_frame_width` final frame-width mutations, including ordinary and
independent while-loop control-flow mutation coverage,
`table.set_border_color` final border-color mutations, including ordinary and
independent while-loop control-flow mutation coverage,
`table.set_border_width` final border-width mutations, including ordinary and
independent while-loop control-flow mutation coverage, `table.delete` deletion
snapshots, including ordinary and independent while-loop control-flow deletion
coverage, `table.clear` inclusive rectangular
cell-content removal snapshots, including ordinary and independent while-loop
control-flow clearing coverage,
`table.merge_cells` inclusive merged-cell rectangle snapshots, including
ordinary and independent while-loop control-flow merge coverage, and
`table.cell_set_text` text mutations, including ordinary and independent
while-loop control-flow mutation coverage, plus `table.cell_set_bgcolor`
background color mutations, including ordinary and independent while-loop
control-flow mutation coverage, plus `table.cell_set_text_color` text-color
mutations, including ordinary and independent while-loop control-flow mutation
coverage, plus `table.cell_set_width` width mutations, including ordinary and
independent while-loop control-flow mutation coverage, plus
`table.cell_set_height` height mutations, including ordinary and independent
while-loop control-flow mutation coverage, plus `table.cell_set_text_size`
text-size mutations, including ordinary and independent while-loop
control-flow mutation coverage, plus `table.cell_set_text_halign` horizontal
text-alignment mutations, including ordinary and independent while-loop
control-flow mutation coverage, plus `table.cell_set_text_valign` vertical
text-alignment mutations, including ordinary and independent while-loop
control-flow mutation coverage, plus `table.cell_set_text_wrap` text-wrap
mutations, including ordinary and independent while-loop control-flow mutation
coverage, plus `table.cell_set_tooltip` tooltip mutations, including ordinary
and independent while-loop control-flow mutation coverage, plus
`table.cell_set_text_font_family` font-family mutations, including ordinary and
independent while-loop control-flow mutation coverage, plus
`table.cell_set_text_formatting` text-formatting mutations, including
ordinary and independent while-loop control-flow mutation coverage, for previously populated cells
with
deterministic table dimensions, a 50-table runtime limit, and a 1000-cell
per-table limit. `table.all` returns currently existing table ids in creation
order, including when read from ordinary and independent while-loop control-flow
blocks after table deletion. Supported label, line, box, and table id-first drawing
functions can also use Pine method syntax, where the object receiver becomes
the first function argument; for example, `id.set_text("x")` is analyzed and
lowered as `label.set_text(id, "x")` when `id` is a label. This method syntax
does not widen the supported method set: unsupported drawing methods and
unsupported box chart-point coordinate variants remain unsupported.
Deleting `na`,
mutating `na`, or mutating an already deleted
drawing object is a no-op where deletion exists; supported label getters return
`na` for `na` or deleted label ids; invalid non-`na` ids are runtime errors; ids
are stable and not reused. `label.new` can initialize host-neutral label
`xloc` values `xloc.bar_index`/`xloc.bar_time`, including from a `chart.point`
by selecting `point.index` or `point.time`, `yloc` values `yloc.price`,
`yloc.abovebar`, and `yloc.belowbar`, text fields with empty-string defaults
when omitted, color/text-color fields with official `color.blue`/`color.white`
defaults when omitted, official `label.style_*` values, size constants or
integer sizes, `textalign`,
`text_font_family`, and `text_formatting` snapshot fields; its `force_overlay`
argument is accepted but left to the host display layer.
`label.set_x`, `label.set_y`, `label.set_xy`, `label.set_point`,
`label.set_text`, and `label.set_size` update the latest existing label
snapshot, including when called from ordinary and independent while-loop
control-flow blocks. `label.set_point` uses the label's current `xloc` to
select `point.index` or `point.time` for x and uses `point.price` for y.
`label.set_color`, `label.set_textcolor`, `label.set_style`,
`label.set_tooltip`, `label.set_textalign`, `label.set_text_font_family`, and
`label.set_text_formatting` update their host-neutral snapshot fields, including
when called from ordinary and independent while-loop control-flow blocks.
`label.set_style` accepts the official label style constants and stores the
selected constant in the latest label snapshot.
`label.set_xloc` records `xloc.bar_index` or `xloc.bar_time` plus the new `x`
value in label snapshots, including when called from ordinary and independent
while-loop control-flow blocks; `label.set_yloc` records `yloc.price`,
`yloc.abovebar`, or `yloc.belowbar`, including when called from ordinary and
independent while-loop control-flow blocks; `label.set_textalign` records horizontal text alignment
in label snapshots. `label.set_text_font_family` records font
family in label snapshots. `label.set_text_formatting` records a
`text.format_none`/`text.format_bold`/`text.format_italic` bitmask, including
bold+italic combinations, while actual glyph styling remains host-specific.
Text layout remains host-specific. `label.delete` appends an `exists: false`
label snapshot, including when called from ordinary and independent while-loop
control-flow blocks.
`label.copy` clones the latest existing label
snapshot into a new deterministic id, including when called from ordinary and
independent while-loop control-flow blocks, returns `na` for `na` or deleted
labels, and shares the effective label limit. `label.get_x` reads the latest
existing label x-coordinate,
including when called from ordinary and independent while-loop control-flow
blocks, and returns `na` for `na` or deleted labels. `label.get_y` reads the
latest existing label y-coordinate, including when called from ordinary and
independent while-loop control-flow blocks, and returns `na` for `na` or deleted
labels.
`label.get_text` reads the latest existing label text, including when called
from ordinary and independent while-loop control-flow blocks, and returns `na`
for `na` or deleted labels. `label.all` returns currently existing label ids in
creation order, including when read from ordinary and independent while-loop
control-flow blocks after label deletion or max-count eviction. Selected
`line.set_*` mutators update
endpoint/color/width/style/extend snapshots, and `line.set_xloc` with
`xloc.bar_index` or `xloc.bar_time` updates x1, x2, and xloc snapshot values,
including when called from ordinary and independent while-loop control-flow
blocks. `line.delete` appends an
`exists: false` line snapshot, including when called from ordinary and
independent while-loop control-flow blocks. `line.copy` clones the latest
existing line snapshot into a new deterministic id, including when called from
ordinary and independent while-loop control-flow blocks,
returns `na` for `na` or deleted lines, and shares the effective line runtime
limit.
`line.all` returns currently existing line ids in creation order, including
when read from ordinary and independent while-loop control-flow blocks after
line deletion or max-count eviction.
`box.copy` clones the latest existing box
snapshot into a new deterministic id, including when called from ordinary and
independent while-loop control-flow blocks, returns `na` for `na` or deleted
boxes, and shares the effective box limit. `box.set_bgcolor`,
`box.set_border_color`, `box.set_border_width`, `box.set_border_style`, and
`box.set_extend` update box style snapshots, including when called from
ordinary and independent while-loop control-flow blocks. `box.set_xloc` with
`xloc.bar_index` or `xloc.bar_time` updates left, right, and xloc values in box
snapshots, including when called from ordinary and independent while-loop
control-flow blocks. `box.set_left`, `box.set_top`,
`box.set_right`, `box.set_bottom`, `box.set_lefttop`, and
`box.set_rightbottom` update box geometry snapshots, including when called from
ordinary and independent while-loop control-flow blocks. `box.set_text`,
`box.set_text_color`, `box.set_text_size`, `box.set_text_halign`,
`box.set_text_valign`, `box.set_text_wrap`, `box.set_text_font_family`, and
`box.set_text_formatting` update box text snapshots, including when called from
ordinary and independent while-loop control-flow blocks. `box.set_text_formatting`
records a `text.format_none`/`text.format_bold`/`text.format_italic` bitmask,
including bold+italic combinations, while actual glyph styling remains
host-specific.
Richer box text layout remains unsupported. `box.get_left`,
`box.get_right`, `box.get_top`, and `box.get_bottom` read the latest existing
box snapshot, including when called from ordinary and independent while-loop
control-flow blocks, and return `na` for `na` or deleted boxes; other box
methods remain unsupported. `table.set_position` updates only the table's final
position value, including when called from ordinary and independent while-loop
control-flow blocks, with table layout left to hosts. `table.new` optional `bgcolor`,
`frame_color`, `frame_width`, `border_color`, and `border_width` initialize only
the table's final background-color, frame-color, frame-width, border-color, and
border-width values. `force_overlay` is accepted, but its value is not exposed
in public output and pane routing remains unsupported.
`table.delete` appends an `exists: false` table snapshot, including when called
from ordinary and independent while-loop control-flow blocks. `table.clear` removes
already populated cells in the inclusive rectangular range from `start_column`,
`start_row` to `end_column`, `end_row`, including when called from ordinary and
independent while-loop control-flow blocks; it also removes merged-cell records
that intersect the cleared range, while preserving the table object and
table-level style fields.
`table.merge_cells` appends inclusive
`start_column`/`start_row` to `end_column`/`end_row` merge rectangles to the
host-neutral table snapshot, including when called from ordinary and independent
while-loop control-flow blocks; deleted or `na` table ids are no-ops, invalid
non-`na` ids are runtime
errors, and out-of-bounds, reversed, or overlapping merge ranges are runtime
errors. Later table-level and cell mutations of
deleted tables are no-ops.
`table.set_bgcolor`, `table.set_frame_color`, `table.set_frame_width`,
`table.set_border_color`, and `table.set_border_width` update only the table's
final style values, including when called from ordinary and independent
while-loop control-flow blocks; border rendering and table layout remain host
responsibilities. `table.cell_set_text`, `table.cell_set_bgcolor`,
`table.cell_set_text_color`, `table.cell_set_width`, `table.cell_set_height`,
`table.cell_set_text_size`, `table.cell_set_text_halign`,
`table.cell_set_text_valign`, `table.cell_set_text_wrap`,
`table.cell_set_tooltip`, `table.cell_set_text_font_family`, and
`table.cell_set_text_formatting` update only previously populated cell
snapshots, including when called from ordinary and independent while-loop
control-flow blocks, while preserving other supported fields. Visual layout,
text wrapping, tooltip display, font rendering, and bold/italic rendering
remain host-specific;
other table cell text rendering remains host-specific.
Supported drawing creation, mutation, cloning, getter, and cell writes are covered under realtime rollback where state
changes, and drawing side effects inside user-defined functions are rejected
under the existing side-effect policy. Keep unsupported coordinate modes and advanced object
methods out of the supported matrix until they have fixtures and public-output
coverage. `linefill.new` and `linefill.set_color` are partial: they create
runtime-owned linefill ids over supported line ids, emit sparse color snapshots,
mutate colors, return referenced line ids through `linefill.get_line1` and
`linefill.get_line2`, and replace the previous linefill for the same line pair.
`linefill.delete` appends deletion snapshots, including while-loop
control-flow deletes, statement-form `array<linefill>` `for...in` shallow-id
iteration supports getter/setter calls with setter visibility through linefill
snapshots and source array ids, and `linefill.all` returns currently existing
linefill ids in creation order while omitting replaced or deleted linefills.
`array.new_linefill` and `array.from` support linefill id arrays for generic
object-array storage, mutation, reads, and search; numeric, truth, sorting, and
join helpers still reject linefill arrays with type diagnostics. `chart.point`
is partial: `chart.point.new`, `chart.point.now`,
`chart.point.from_index`, `chart.point.from_time`, and `chart.point.copy`
construct/copy point values, and top-level `time`, `index`, and `price` field
reads and mutation are fixture-backed. Single `chart.point` value history is
fixture-backed for constant offsets, dynamic `na` offsets, retained previous
values after current-point field mutation, UDF-returned and method-returned
point values, and
`if`/`switch`/`for`/`for...in`/`while` expression results. Ordinary
`var chart.point` values roll back field mutation between repeated forming
realtime updates,
while single `chart.point` value `varip` declarations persist point values
intrabar by value, including field-mutation writeback and committed/realtime
confirmed-bar history reads with constant and dynamic offsets. Scalar and
`chart.point` typed UDF parameters are fixture-backed for constructor-returned points,
read-only passthrough, caller-side field reads, and history reads. Scalar,
object-id, `chart.point`, same-local scalar-tree UDT array, and same-imported
scalar-tree UDT array typed UDF parameters are fixture-backed for `array<T>` and
`T[]` syntax, including named same-imported UDT array arguments, caller-side
history reads from returned imported UDT array elements, typed argument
rejection, and history reads from UDF results. Scalar, `chart.point`, scalar-array, object-id-array,
chart.point-array, same-local scalar-tree UDT array, and same-imported
scalar-tree UDT array typed method parameters are fixture-backed, including
`array<T>`/`T[]` syntax, receiver-style and alias-qualified imported method
calls, named same-imported UDT array arguments, caller-side history reads from
returned imported UDT array elements, and typed argument rejection.
`array.new<chart.point>()` can construct chart-point arrays,
`array.from(chart.point, ...)` can infer chart-point arrays, and the generic
storage/read/mutation/search subset can carry point values.
Label, line, linefill, box, and table arrays may also be iterated by statement-form
`for...in` as shallow-id loop locals with getter/setter, cell-write, or
lifecycle calls and visibility through the source array id, linefill snapshots,
or `box.all`/`table.all` deletion state. Polyline arrays may also be iterated by
statement-form `for...in` as shallow-id loop locals with deletion visible
through `polyline.all`. Chart-point arrays may also be iterated by
statement-form value-only or index/value `for...in` as value-copy loop locals
with field reads and local field mutation that does not write back to the source
slot.
`array.new<T>()` and `array.from` can construct same-local scalar-tree UDT
arrays for value-only and index/value `for...in` value-copy iteration,
`array.size`, method `size()`, namespace `array.get`, method `get()` field
reads, and
same-UDT `array.set`/`set()` replacement, `array.push`/`push()` append, and
`array.pop`/`pop()` returns plus `array.shift`/`shift()` returns,
`array.first`/`first()` and `array.last`/`last()` reads,
including direct `array.new<T>()` empty-array `na` returns for first, last,
pop, and shift,
`array.clear`/`clear()` reset/reuse, `array.copy`/`copy()` independence,
`array.concat`/`concat()` same-UDT append,
`array.slice`/`slice()` parent-window read/write mirroring, and
`array.reverse`/`reverse()` reordering, plus `array.insert`/`insert()`
same-UDT insertion, `array.remove`/`remove()` returns, and
`array.unshift`/`unshift()` same-UDT prepend; typed `array<T>`/`T[]`
declarations are supported for the same local scalar-tree UDT array subset.
Same-imported scalar-tree UDT `array.from` construction is also fixture-backed
for `array.size`, namespace/method `array.get`, namespace/method
`array.first`/`array.last` field reads, namespace/method
`array.set`/`set()` replacement field reads, namespace/method
`array.push`/`push()` append field reads, namespace/method
`array.unshift`/`unshift()` prepend field reads, namespace/method
`array.insert`/`insert()` insertion field reads, namespace/method
`array.pop`/`array.remove`/`array.shift` return field reads, and
`array.clear`/`clear()` size reset plus `array.copy`/`copy()` independent field
reads, `array.reverse`/`reverse()` reordered field reads,
`array.slice`/`slice()` window field reads, and `array.concat`/`concat()`
appended field reads.
Same-local and same-imported scalar-tree UDT array identities are preserved
through ternary, `if`, `switch`, `for`, `for...in`, and `while` expression
results, including array/`na` branches and block-local aliases. Those results
can initialize typed or inferred declarations and be consumed by the existing
array helper, history, and iteration subsets. Mixed UDT identities remain
diagnostic-only unsupported.
Same-local scalar-tree UDT array id history snapshots are fixture-backed and
clone the committed array before historical reads. Same-local scalar-tree UDT
array `varip` declarations retain array ids, backing contents, and UDT element
identity across realtime forming updates. Mixed UDT values, non-scalar imported
UDT arrays, nested-field UDT values, and nested-field UDT `varip` remain unsupported. Ordinary `var` UDT arrays roll
back their backing store during realtime forming updates.
`polyline.new` can consume those arrays and copy their values into host-neutral
runtime snapshots, while `polyline.delete` and `polyline.all` cover the
historical and forming-bar rollback lifecycle subset. Omitted `line_color`
uses the official `color.blue` default in runtime snapshots. `polyline.new`
uses the runtime default 50-polyline limit and named `max_polylines_count`
declaration values from 1 through 100 to evict oldest active polyline
snapshots before creating new ones. `line.new`, `line.set_first_point`,
`line.set_second_point`, `box.new`, `box.set_top_left_point`,
`box.set_bottom_right_point`, `label.new`, and `label.set_point` can consume
`chart.point` values. `box.new` chart-point snapshots use the same official
default `border_color`, `bgcolor`, `text_color`, and `text_size` values as the
scalar overload when those arguments are omitted. `chart.point` typed
declarations are fixture-backed for chart-point or `na` initializers, including
`if`/`switch`/`for`/`while` expression results. Polyline
id arrays are fixture-backed through
`array.new_polyline`, official `array.new<polyline>` template syntax, typed
`array<polyline>`/`polyline[]` declarations, `array.from(polyline, ...)`,
the generic object-array helper subset, and array/slice history snapshots.
UDT arrays remain outside generic array mutation semantics until broader
copy/deep-copy rules are designed; the current UDT array subset is limited to
same-local scalar-field `array.new<T>()` and
`array.from(...)` construction with `array.size`/`size()` reads,
`array.get`/`get()` field reads,
same-UDT `array.set`/`set()` replacement, and same-UDT `array.push`/`push()`
append, plus `array.pop`/`pop()` and `array.shift`/`shift()` returns and
`array.first`/`first()` and `array.last`/`last()` reads, plus
`array.clear`/`clear()` reset/reuse, `array.copy`/`copy()` independence, and
`array.concat`/`concat()` same-UDT append, `array.slice`/`slice()`
parent-window read/write mirroring, `array.reverse`/`reverse()` reordering, and
`array.insert`/`insert()` same-UDT insertion, plus `array.remove`/`remove()`
returns, `array.unshift`/`unshift()` same-UDT prepend, `array.sort`/`sort()`
by an `int`, `float`, or `string` `sort_field`, `array.sort_indices`/
`sort_indices()` by the same `sort_field` subset returning original indexes
without mutating the source array, same-local scalar-tree UDT `array<T>` and
`T[]` typed declarations, same-local scalar-tree UDT `array.includes`,
`array.indexof`, and `array.lastindexof` structural equality search,
`array.fill`/`fill()` same-UDT replacement over valid half-open ranges,
`array.join`/`join()` positional UDT stringification,
local field mutation of UDT values read from arrays with explicit same-UDT
`array.set`/`set()` writeback, direct chained slot field mutation through
`array.get(points, index).field := value` or `points.get(index).field := value`
with slice-window parent mirroring,
local pure UDF calls that consume UDT values read from arrays,
local pure method calls on UDT values read from arrays into local variables,
same-local scalar-tree UDT array id history snapshots including dynamic na-offset predicate output, same-local scalar-tree
UDT array statement-form `for...in` value-copy loop variables with field reads
and local field mutation that does not write back to the source slot, and
ordinary `var` realtime rollback, plus same-local scalar-tree UDT array
`varip` backing-store handoff across realtime forming updates.

Phase H reserves `alerts` as a top-level runtime key in `schemaVersion: 3`.
The first supported alert subsets are `alertcondition(condition, title,
message)` with bool-compatible conditions, const-string titles, and
const-string messages, plus fixture-backed OHLCV placeholder interpolation for
`{{open}}`, `{{high}}`, `{{low}}`, `{{close}}`, and `{{volume}}`, plus
`{{ticker}}`, `{{interval}}`, `{{exchange}}`, and `{{time}}`, in the
`alertcondition` message only. `{{time}}` uses the existing UTC
`str.format_time` default format for the triggering bar timestamp.
`alert(message, freq?)` supports string-compatible dynamic messages and the fixture-backed
`alert.freq_once_per_bar`/`alert.freq_all`/`alert.freq_once_per_bar_close`
frequency subset. Reached true alert conditions and reached alert calls emit
`{id, barIndex, time, message, source}` events in program order, subject to
supported `alert()` frequency filtering; false and `na` alert conditions emit
nothing. Forming realtime events are visible in the forming result and roll back
until a confirmed update commits an event, while close-frequency alert calls are
suppressed on forming updates and emitted only on historical or confirmed
bar-close execution. Repeated forming updates recompute alert events from the
confirmed snapshot, so abandoned forming events are neither retained nor
duplicated, and a confirmed update matches the equivalent historical execution
where the same final bar data is available. TradingView-style `{{...}}` alert
placeholder interpolation outside the supported `alertcondition` message
placeholder subset remains unsupported; supported `alert()` messages are
serialized literally.

The official Pine Logs functions `log.info()`, `log.warning()`, and
`log.error()` remain unsupported. They require a host-owned log pane or runtime
output contract, so the analyzer reports them as explicit unsupported `log.*`
calls instead of treating them as unknown functions.

Pine map collections are partial. `map.new<K, V>()` accepts scalar key/value
templates using `int`, `float`, `bool`, `string`, or `color` and returns a
runtime-owned empty map id. `map.size(id)` returns the current entry count for
map ids. `map.put`, `map.get`, and `map.contains` are supported for those
scalar key/value templates; put inserts or replaces entries, get returns `na`
for missing keys, and contains returns key presence. `map.clear` removes all
entries from the map id. `map.remove` deletes a present key and is a no-op for
missing keys. Assignment aliases the runtime map id, while `map.copy` returns an
independent cloned backing store with the same scalar key/value template.
`map.keys` and `map.values` return independent insertion-order array snapshots.
`map.put_all` merges entries from a source map into a target map with the same
scalar key/value template, replacing existing values without moving their order
and appending new keys in source insertion order.
Direct `for key in id` and `for [key, value] in id` iteration is fixture-backed
for scalar maps in insertion order, including statement and expression forms.
The key-only loop local uses the map key template kind; in key/value form, the
first loop local uses the map key template kind and the second loop local uses
the map value template kind. Changing the map size from a direct map `for...in`
body reports a runtime error.
Ordinary realtime rollback restores map-store mutations from the confirmed
runtime snapshot. Equivalent method aliases are supported for the same subset:
`id.size()`, `id.put(key, value)`, `id.get(key)`, `id.contains(key)`,
`id.clear()`, `id.remove(key)`, `id.copy()`, `id.keys()`, and `id.values()`.
`id.put_all(source)` is also supported. Scalar `map<K,V>` typed declarations
preserve map template metadata for compatible or `na` initialization and
same-template reassignment. Bare scalar `map` declarations initialized from
known scalar map expressions infer the same template metadata. Scalar map history snapshots are supported with
independent historical copies. Scalar map `varip` handoff retains map ids and
backing stores across repeated realtime forming updates. Read-only map helper
calls can consume map ids passed through user-defined function parameters when
the map template is known at the caller. Template-less bare map declarations,
non-scalar templates, and non-map map receivers remain unsupported.

Pine matrix collections are partial. Runtime-owned `matrix<float>` ids support
`matrix.new<float>`, `matrix.get`, `matrix.set`, `matrix.fill`, `matrix.concat`,
`values.concat(other)`, `matrix.copy`,
`values.copy()`, `matrix.transpose`, `values.transpose()`, `matrix.reverse`,
`values.reverse()`, `matrix.reshape`, `values.reshape(rows, columns)`,
`matrix.kron`, `values.kron(other)`, matrix-or-scalar namespace `matrix.mult`,
`values.mult(other)`, matrix-or-scalar namespace `matrix.diff`,
`values.diff(other)`,
`matrix.pow`, `values.pow(power)`, `matrix.add_row`,
`values.add_row(row, array_id)`, `matrix.add_col`,
`values.add_col(column, array_id)`, `matrix.remove_row`,
`values.remove_row(row)`, `matrix.remove_col`, `values.remove_col(column)`,
`matrix.swap_rows`, `values.swap_rows(row1, row2)`,
`matrix.swap_columns`, `values.swap_columns(column1, column2)`,
`matrix.sort`, `values.sort(column?, order?)`,
`matrix.rows`, `values.rows()`, `matrix.columns`, `values.columns()`,
`matrix.elements_count`, `values.elements_count()`, `matrix.is_square`,
`values.is_square()`, `matrix.is_binary`, `values.is_binary()`,
`matrix.is_diagonal`, `values.is_diagonal()`, `matrix.is_antidiagonal`,
`values.is_antidiagonal()`, `matrix.is_triangular`,
`values.is_triangular()`, `matrix.is_identity`,
`values.is_identity()`, `matrix.is_symmetric`, `values.is_symmetric()`,
`matrix.is_antisymmetric`, `values.is_antisymmetric()`,
`matrix.is_stochastic`, `values.is_stochastic()`, `matrix.is_zero`,
`values.is_zero()`, `matrix.sum`,
`values.sum()`, `matrix.avg`, `values.avg()`, `matrix.min`,
`values.min()`, `matrix.max`, `values.max()`, `matrix.median`,
`values.median()`, `matrix.mode`, `values.mode()`,
`matrix.trace`, `values.trace()`, `matrix.det`, `values.det()`,
`matrix.eigenvalues`, `values.eigenvalues()`, `matrix.eigenvectors`,
`values.eigenvectors()`, `matrix.inv`, `values.inv()`, `matrix.pinv`,
`values.pinv()`, `matrix.rank`,
`values.rank()`,
`matrix.row`,
`values.row(row)`, `matrix.col`, and `values.col(column)` with rectangular storage,
while runtime-owned `matrix<bool>` ids support `matrix.new<bool>`,
`matrix.get`, `matrix.set`, `matrix.fill`, `matrix.concat`, `matrix.copy`,
`matrix.transpose`, `matrix.reverse`, `matrix.reshape`, `matrix.submatrix`,
`matrix.row`, `matrix.col`, `matrix.add_row`, `matrix.add_col`,
`matrix.remove_row`, `matrix.remove_col`, `matrix.swap_rows`,
`matrix.swap_columns`, `matrix.rows`, `matrix.columns`,
`matrix.elements_count`, and `matrix.is_square`, including the corresponding
supported method aliases, bool or `na` cells, `array<bool>` row/column
snapshots, and `matrix<bool>` typed declarations,
while runtime-owned `matrix<string>` ids support `matrix.new<string>`,
`matrix.get`, `matrix.set`, `matrix.fill`, `matrix.concat`, `matrix.copy`,
`matrix.transpose`, `matrix.reverse`, `matrix.reshape`, `matrix.submatrix`,
`matrix.row`, `matrix.col`, `matrix.add_row`, `matrix.add_col`,
`matrix.remove_row`, `matrix.remove_col`, `matrix.swap_rows`,
`matrix.swap_columns`, `matrix.rows`, `matrix.columns`,
`matrix.elements_count`, and `matrix.is_square`, including the corresponding
supported method aliases, string or `na` cells, `array<string>` row/column
snapshots, and `matrix<string>` typed declarations,
while runtime-owned `matrix<color>` ids support `matrix.new<color>`,
`matrix.get`, `matrix.set`, `matrix.fill`, `matrix.concat`, `matrix.copy`,
`matrix.transpose`, `matrix.reverse`, `matrix.reshape`, `matrix.submatrix`,
`matrix.row`, `matrix.col`, `matrix.add_row`, `matrix.add_col`,
`matrix.remove_row`, `matrix.remove_col`, `matrix.swap_rows`,
`matrix.swap_columns`, `matrix.rows`, `matrix.columns`,
`matrix.elements_count`, and `matrix.is_square`, including the corresponding
supported method aliases, color or `na` cells, `array<color>` row/column
snapshots, and `matrix<color>` typed declarations,
while runtime-owned `matrix<int>` ids support `matrix.new<int>`, `matrix.get`,
`matrix.set`, `matrix.fill`, `matrix.concat`, `matrix.copy`, `matrix.transpose`,
`matrix.reverse`, `matrix.reshape`, `matrix.submatrix`, `matrix.row`,
`matrix.col`, `matrix.kron`, `matrix.mult`, `matrix.diff`, `matrix.pow`,
`matrix.add_row`, `matrix.add_col`, `matrix.remove_row`, `matrix.remove_col`,
`matrix.swap_rows`, `matrix.swap_columns`, `matrix.sort`, `matrix.rows`,
`matrix.columns`, `matrix.elements_count`, and `matrix.is_square`,
`matrix.is_binary`, `matrix.is_diagonal`,
`matrix.is_antidiagonal`, `matrix.is_triangular`, `matrix.is_identity`,
`matrix.is_symmetric`, `matrix.is_antisymmetric`,
`matrix.is_stochastic`, `matrix.is_zero`, `matrix.sum`, `matrix.avg`,
`matrix.min`, `matrix.max`, `matrix.median`, `matrix.mode`, `matrix.trace`,
`matrix.det`,
`matrix.eigenvalues`, `matrix.eigenvectors`, `matrix.inv`, `matrix.pinv`, and
`matrix.rank`, including the corresponding supported method aliases and int or
`na` cells,
namespace and method-call concatenation that mutates and returns the first
matrix by appending a snapshot of the second matrix's rows, preserves the
second matrix, supports self-concatenation, compatible zero-row/zero-column
shapes, ordinary `var` persistence and committed history snapshots, requires
matching element kinds and column counts, and enforces the 100000-cell limit,
namespace and method-call reshape preserving element order and element count,
namespace and method-call reshape element-count mismatch errors,
namespace and method-call matrix-by-matrix multiplication returning independent
matrix results with multiplied shape, `na` propagation, shape-mismatch errors,
and cell-budget errors,
namespace and method-call matrix-by-matrix subtraction returning independent
matrix results with matching shape, `na` propagation, and shape-mismatch
errors,
namespace and method-call matrix powers returning independent identity, copy,
and powered matrices with `na` propagation, non-square errors, and
negative-power errors,
namespace and method-call Kronecker products returning independent
expanded-shape matrices with `na` cell propagation and cell-budget errors,
namespace and method-call row/column insertion from `array<float>` snapshots,
namespace and method-call row/column deletion,
namespace and method-call row swaps preserving shape,
namespace and method-call column swaps preserving shape,
namespace and method-call row sorting by a selected column with default column
`0`, ascending/descending order, stable equal-key row order, and `na` placement,
namespace and method-call element-count reads, matrix sums, averages, minimums,
maximums, medians, modes, traces, determinants, eigenvalue arrays, eigenvector
matrices, inverse matrices, pseudo-inverse matrices, and ranks, where aggregate
readers ignore `na` cells and return `na` for empty or all-`na` matrices,
medians preserve the source element kind with official `series int`/`series
float` overloads and average the two middle values for even element counts
(truncating integer results toward zero), determinants return `na` for any
`na` cell and runtime-error on non-square matrices, ranks support rectangular
matrices and return `na` for any `na` cell, and modes return `na` for no
repeated numeric cells,
namespace and method-call square-shape predicates,
namespace and method-call anti-diagonal predicates that require square shapes,
allow any secondary-diagonal value including `na`, require exact-zero numeric
cells everywhere else, return false for off-diagonal `na` cells, and return
true for empty `0 x 0` matrices, with the official fixed `series bool` return
qualifier,
namespace and method-call triangular predicates that require square shapes and
exact-zero numeric cells either entirely above or entirely below the main
diagonal, allow arbitrary diagonal and opposite-side values including `na`,
return false when neither side is all zero, and return true for empty `0 x 0`
matrices, with the official fixed `series bool` return qualifier,
namespace and method-call transposes returning independent matrix copies with
swapped row/column counts,
namespace and method-call matrix reversals mutating cells in place while
preserving shape,
numeric/na cells,
int-to-float coercion, zero row/column dimensions, shape reads, shape reads
through ordinary for and while loops, read-only UDF
cell/shape reads and row/column extraction reads, UDF-returned independent
copies, loop-local independent copies, while-loop independent copies, while-expression fresh/alias/zero/break/continue/history matrix results including dynamic na-offset predicates, set/get/fill/concat/reshape mutation,
branch/loop set/fill/reshape mutation ordering, while-loop set/fill/reshape mutation ordering, add-row/add-column insertion ordering, row/column deletion ordering, assignment/reference aliasing, explicit
independent copies, ordinary `var`
persistence, committed matrix history snapshots, shape snapshots, and
dynamic-offset matrix snapshots that return fresh copies plus na-offset matrix predicate output,
realtime forming-bar rollback for matrix mutation and shape changes, runtime profile slot/cell
counters, namespace and method-call row/column extraction returning independent
`array<float>` snapshots for float matrices and `array<int>` snapshots for int
matrices, row/column extraction reads through ordinary branches, for loops,
and while loops,
and bounds errors, including row/column `matrix.get` index
bounds, method-alias `values.get(row, column)` row/column index bounds,
namespace `matrix.row`/`matrix.col` row/column extraction index bounds,
method-alias `values.row(row)`/`values.col(column)` row/column extraction index bounds,
namespace `matrix.row`/`matrix.col` negative row/column extraction index bounds,
method-alias `values.row(row)`/`values.col(column)` negative row/column extraction index bounds,
namespace `matrix.row`/`matrix.col` `na` row/column extraction index bounds,
method-alias `values.row(row)`/`values.col(column)` `na` row/column extraction index bounds,
negative row/column `matrix.get` index bounds, method-alias
`values.get(row, column)` negative row/column index bounds, `matrix.set` row/column bounds, negative
`matrix.set` row/column bounds, method-alias
`values.set(row, column, value)` row/column bounds, method-alias
`values.set(row, column, value)` negative row/column bounds, `na` row/column indexes for matrix cell reads
and writes, method-alias `values.get(row, column)` `na` row/column indexes,
method-alias `values.set(row, column, value)` `na` row/column indexes, negative
namespace `matrix.reshape` row/column counts, negative method-alias
`values.reshape(rows, columns)` row/column counts, `na` namespace `matrix.reshape`
row/column counts, `na` method-alias `values.reshape(rows, columns)` row/column
counts, negative and `na` constructor
dimensions, and the matrix
cell-budget guard, plus `matrix.concat` column-count mismatch and concatenation
cell-budget errors, `matrix.add_row` insertion row bounds and array-size
mismatch errors, `matrix.add_col` insertion column bounds and array-size
mismatch errors, `matrix.remove_row` row bounds and `na` row-index errors, and
`matrix.remove_col` column bounds and `na` column-index errors, and
`matrix.swap_rows` row bounds and `na` row-index errors, and
`matrix.swap_columns` column bounds and `na` column-index errors, and
`matrix.sort` column bounds, `na` column-index, and unsupported-order errors.
Matrix get/copy helpers including
`values.get(row, column)` and `values.copy()`, concatenation helpers including
`values.concat(other)`, transform helpers including
`values.transpose()`, shape readers including
`values.rows()`/`values.columns()`/`values.elements_count()`/`values.is_square()`, value predicates including
`values.is_binary()`/`values.is_diagonal()`/`values.is_antidiagonal()`/
`values.is_triangular()`/`values.is_identity()`/`values.is_symmetric()`/
`values.is_antisymmetric()`/`values.is_stochastic()`/`values.is_zero()`,
numeric readers including
`values.sum()`/`values.avg()`/`values.min()`/`values.max()`/`values.median()`/`values.mode()`/`values.trace()`/`values.det()`/`values.rank()`,
row/column extraction helpers including
`values.row(row)`/`values.col(column)`, submatrix helpers including
`values.submatrix(from_row?, to_row?, from_column?, to_column?)`, and mutating helpers including
`values.set(row, column, value)`, `values.fill(value)`,
`values.reverse()`, `values.reshape(rows, columns)`, `values.add_row(row, array_id)`, and
`values.add_col(column, array_id)`, `values.remove_row(row)`, and
`values.remove_col(column)`, `values.swap_rows(row1, row2)`, and
`values.swap_columns(column1, column2)`, and `values.sort(column?, order?)` also reject
non-matrix receivers at semantic
analysis time. Non-numeric `matrix.new<float>`
initial values,
non-int namespace `matrix.row`/`matrix.col` row/column indexes,
non-int method-alias `values.row(row)`/`values.col(column)` row/column indexes,
non-int namespace/method `matrix.add_row` row indexes, non-int namespace/method `matrix.add_col` column indexes, non-int namespace/method `matrix.remove_row` row indexes, non-int namespace/method `matrix.remove_col` column indexes, non-int namespace/method `matrix.swap_rows` row indexes, non-int namespace/method `matrix.swap_columns` column indexes, non-int namespace/method `matrix.sort` column indexes, non-const-string namespace/method `matrix.sort` order arguments, non-int namespace/method `matrix.submatrix` range indexes, matrix row/column insertion data whose array element kind does not match the matrix element kind,
non-numeric float-matrix `matrix.set`/`matrix.fill` values, non-int int-matrix
`matrix.set`/`matrix.fill` values, non-bool bool-matrix
`matrix.set`/`matrix.fill` values, non-string string-matrix `matrix.set`/`matrix.fill` values, non-color color-matrix `matrix.set`/`matrix.fill` values, and method values for
`values.set(row, column, value)` and `values.fill(value)` are rejected at
semantic analysis time. Non-int `matrix.get` row/column indexes are also
rejected at semantic analysis time, including the `values.get(row, column)`
method alias row/column indexes. Non-int namespace `matrix.set` row/column
indexes and `values.set(row, column, value)` method alias row/column indexes are
rejected at semantic analysis time. Non-int namespace `matrix.reshape`
row/column counts and method-alias `values.reshape(rows, columns)` row/column
counts are rejected at semantic analysis time.
`matrix.set`, `matrix.fill`, `matrix.concat`, `matrix.reverse`, `matrix.reshape`, `matrix.add_row`,
`matrix.add_col`, `matrix.remove_row`, `matrix.remove_col`, and
`matrix.swap_rows`, `matrix.swap_columns`, and `matrix.sort`,
including
`values.set(row, column, value)`, `values.fill(value)`,
`values.concat(other)`,
`values.reverse()`, `values.reshape(rows, columns)`, `values.add_row(row, array_id)`,
`values.add_col(column, array_id)`, `values.remove_row(row)`, and
`values.remove_col(column)`, `values.swap_rows(row1, row2)`, and
`values.swap_columns(column1, column2)`, and `values.sort(column?, order?)`,
remain unsupported inside user-defined functions.
Matrix templates beyond the current `float`, `int`, `bool`, `string`, and `color`
subset, including deferred element templates such as `matrix.new<label>`,
method syntax beyond
`values.fill(value)`, `values.get(row, column)`,
`values.set(row, column, value)`, `values.concat(other)`, `values.copy()`,
`values.transpose()`, `values.reverse()`, `values.reshape(rows, columns)`, `values.rows()`, `values.columns()`,
`values.elements_count()`, `values.is_square()`, `values.is_binary()`,
`values.is_diagonal()`, `values.is_antidiagonal()`, `values.is_triangular()`,
`values.is_identity()`, `values.is_symmetric()`, `values.is_antisymmetric()`,
`values.is_stochastic()`, `values.is_zero()`, `values.sum()`, `values.avg()`,
`values.min()`, `values.max()`, `values.median()`, `values.mode()`, `values.trace()`,
`values.det()`, `values.rank()`, `values.row(row)`, `values.col(column)`,
`values.add_row(row, array_id)`, and
`values.add_col(column, array_id)`, `values.remove_row(row)`, and
`values.remove_col(column)`, `values.swap_rows(row1, row2)`, and
`values.swap_columns(column1, column2)`, `values.sort(column?, order?)`, `values.submatrix(from_row?, to_row?, from_column?, to_column?)`,
bare matrix or matrix templates beyond float/int/bool/string/color typed
declarations remain unsupported until their semantics are designed and
fixture-backed.
Statement-form matrix `for...in` iteration is fixture-backed over row snapshots
with optional row-index binding. `matrix<float>`, `matrix<int>`,
`matrix<bool>`, `matrix<string>`, and `matrix<color>` typed declarations are
fixture-backed. Matrix history is fixture-backed for committed, shape, and
dynamic-offset matrix snapshots that return fresh copies.
Matrix `varip` declarations for `matrix<float>`, `matrix<int>`,
`matrix<bool>`, `matrix<string>`, and `matrix<color>` retain matrix ids and
backing contents across realtime forming updates.

Runtime strategy order-fill alert payloads are exposed under `strategy.alerts`
for supported strategy fills in the current runtime schema. Runtime
`schemaVersion: 5` added host-neutral `textWrap` to table cell snapshots.
Runtime `schemaVersion: 6` added top-level `lineFills` snapshots for the
supported linefill subset. Runtime `schemaVersion: 7` is current and adds
top-level `polylines` snapshots for the supported `polyline.new` and lifecycle
subset. The
top-level `alerts[]` array remains limited to reached `alert()` and
`alertcondition()` callsites. Explicit Python, CLI, and WASM host helpers can render
`{{strategy.order.alert_message}}` from selected public strategy fill events,
while external alert delivery remains unsupported.

Checked-in golden JSON snapshots live in `tests/snapshots/`. Snapshot tests are
strict string comparisons against deterministic compact JSON; a public field
rename, omitted `schemaVersion`, or matrix shape change should fail tests. To
refresh snapshots after an intentional public-output change, run:

```text
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli runtime_outputs_match_golden_snapshots
UPDATE_SNAPSHOTS=1 cargo test -p pine-cli matrix_output_matches_golden_snapshot
UPDATE_SNAPSHOTS=1 cargo test -p pine-wasm analysis_outputs_match_golden_snapshots
cargo test --workspace
```

Review the resulting JSON diff before committing. Do not update snapshots to
hide accidental public contract changes.

Snapshot maintenance rules:

- Treat checked-in snapshots as public contract evidence, not generated noise.
- Update snapshots only with the targeted `UPDATE_SNAPSHOTS=1` commands above.
- Include the source change, snapshot diff, and documentation update in the
  same commit when a public output change is intentional.
- Run `scripts/verify.sh` after any snapshot refresh so CLI, WASM, Python, and
  matrix contracts are checked together.

## Numeric Tolerance

Floating point outputs should be compared with an explicit tolerance:

```text
absolute tolerance: 1e-10
relative tolerance: 1e-9
```

Some built-ins may need per-function tolerances if their documented formulas
accumulate rounding differently. Any wider tolerance must be justified in the
fixture metadata.

## Test Data

OHLCV fixtures should be small and deterministic.

Rules:

- Include enough bars to test warmup behavior.
- Include gaps or flat sections where indicators often fail.
- Include first-bar and out-of-range history cases.
- Do not depend on external market data downloads in unit tests.

## Unsupported Features

Unsupported fixtures are first-class tests.

Examples:

- unsupported `request.security` variants outside the same-context identity
  scalar/tuple-literal subset and same-or-higher-timeframe provider
  scalar/tuple-literal subset
- unsupported strategy declaration contexts and strategy order variants outside
  the fixture-backed `strategy.order` subset; `strategy.exit` same-side pairs,
  custom OCA parameters, 3+ triggers, invalid trailing combinations, and
  arbitrary future binding for
  unmatched `from_entry` ids remain fixture-backed unsupported cases.
  Stop-only `strategy.exit(id, from_entry, stop=price)`, limit-only
  `strategy.exit(id, from_entry, limit=price)`, profit-only
  `strategy.exit(id, from_entry, profit=ticks)`, loss-only
  `strategy.exit(id, from_entry, loss=ticks)`, and exactly one-downside plus
  one-upside brackets (`stop + limit`, `stop + profit`, `loss + limit`,
  `loss + profit`), plus trailing stops (`trail_price + trail_offset` and
  `trail_points + trail_offset`), optionally with fixed `qty` or `qty_percent`,
  are the narrow supported subsets for the current one-net-long broker.
  Supported brackets use
  stop/loss-first precedence when both legs are touched on the same eligible
  historical bar. Supported trailing stops do not fill on the activation bar
  and ratchet only upward after activation. Supported fixed `qty` exits close
  `min(qty, position_size)`, keep any remaining long position open at the same
  average price, and do not add public pending-order or remaining-quantity
  fields. Supported `qty_percent` exits evaluate the percent at placement time,
  resolve it to an absolute quantity against the current position size or the
  matching pending entry quantity for same-calculation absolute exit attachment,
  clamp fills to the current position, and expose only the absolute filled `qty`.
  When supported `strategy.exit` shapes supply both `qty` and `qty_percent`,
  fixed `qty` determines the reserved or filled quantity and `qty_percent` is
  ignored.
- minimal `strategy.entry` long market, long limit, long stop, and long
  stop-limit entries in strategy-mode scripts; market entries fill at the next
  historical bar open, limit entries fill at the limit price on a later
  historical bar when `low <= limit`, stop entries fill at the stop price on a
  later historical bar when `high >= stop`, stop-limit entries activate on a
  later historical bar when `high >= stop` and fill at the limit price on a
  subsequent historical bar when `low <= limit`, and no public pending-order
  output is exposed; unsupported short/indicator-mode variants are
  fixture-backed; entries may omit `qty` only when the strategy declaration
  configures the fixed default quantity subset
- minimal `strategy.close` full-position closes for matching long entry ids,
  with flat, wrong-entry, or repeated closes treated as no-op
- minimal `strategy.close_all` full-position closes for the current supported
  long position, with flat or already-closed calls treated as no-op
- minimal `strategy.cancel(id)` cancellation for matching supported internal
  pending entry ids and pending exit ids; filled, unknown, and already-cancelled
  ids are no-op, and no public pending-order or cancellation records are
  exposed
- minimal `strategy.cancel_all()` cancellation for all supported internal
  pending entries and pending exits; calling it without pending orders is a
  no-op, and no public pending-order or cancellation records are exposed
- minimal strategy equity snapshots with bar-close mark-to-market accounting,
  with broader broker settings and rich strategy reporting variables
  unsupported
- unsupported strategy reporting helpers beyond the supported position,
  profit, equity, run-up/drawdown, and trade-count variables, plus unknown `strategy.*`
  reporting helpers
- unsupported collection families or unsupported array variants
- unsupported label and line methods
- unsupported import variants outside the host-provided alias/exported
  const/pure-function subset
- unsupported `varip` forms such as drawing ids, drawing-id typed arrays,
  tuples, and value families outside the scalar, scalar typed-array,
  `chart.point` typed-array, scalar map/matrix, scalar-tree UDT/UDT-array, and
  explicit non-scalar UDT typed-na subset
- non-integer or negative history offsets
- unsupported function side effects, including drawing, alert, strategy order,
  and UDT parameter field mutation side effects

Expected result:

- no panic
- stable diagnostic code
- source span
- machine-readable compatibility report entry

## Diagnostic Stability

Diagnostics should include:

```text
code
severity
message
span
feature id when applicable
help text when useful
```

Messages can improve over time, but codes should remain stable once published.

## Comparison Policy

Allowed comparison sources:

- public language documentation
- original mathematical formulas
- project-owned fixtures
- permissively licensed scripts with metadata
- user-provided scripts when the user has the right to use them

Disallowed:

- copied proprietary scripts
- private TradingView APIs
- scraped TradingView data
- copied official documentation text beyond short references
- TradingView UI or error text reproduction

## Release Compatibility Matrix

Every release should publish a generated or manually maintained matrix:

```text
feature              status       notes
indicator            supported
input.int            supported
ta.sma               supported
ta.ema               supported
ta.rsi               supported    fixture-derived executable subset
request.security     partial      same-context identity scalar-expression subset plus same-context tuple literals made from side-effect-free elements and selected same-context tuple-returning calls destructured directly from the request, currently ta.macd, ta.bb, ta.kc, ta.supertrend, ta.dmi, and ta.vwap(source, anchor, stdev_mult), and same-or-higher-timeframe provider scalar-expression subset with direct sources, arithmetic, history, na/nz, selected stateless math.* calls, fixed-mintick math.round_to_mintick, math.sum, ta.cum, ta.sma, ta.ema, ta.dema, ta.tema, ta.rma, ta.rsi, ta.accdist, ta.iii, ta.nvi, ta.obv, ta.pvi, ta.pvt, ta.wvad, ta.tsi, ta.cmo, ta.cci, ta.cog, ta.bop, ta.ao, ta.max, ta.min, ta.mfi, ta.stoch, ta.wpr, ta.sar, ta.tr function calls, ta.atr, ta.highest, ta.lowest, ta.highestbars, ta.lowestbars, ta.change, ta.mom, ta.roc, ta.range, ta.dev, ta.vwap source-call, ta.bbw, ta.kcw, ta.pivothigh, ta.pivotlow, ta.correlation, ta.covariance, ta.median, ta.mode, ta.percentile_nearest_rank, ta.percentile_linear_interpolation, ta.percentrank, ta.stdev, ta.variance, ta.wma, ta.vwma, ta.swma, ta.hma, ta.alma, ta.linreg, ta.rising, ta.falling, ta.barssince, ta.valuewhen, ta.cross, ta.crossover, and ta.crossunder only, plus provider-backed tuple literals made from supported scalar elements and provider-backed ta.macd, ta.bb, ta.kc, ta.supertrend, ta.dmi, and ta.vwap(source, anchor, stdev_mult) tuple expressions destructured directly from the request; other provider-backed tuple expressions remain unsupported
alertcondition       partial      bool-compatible condition plus const-string title/message runtime events, with OHLCV plus ticker/interval/exchange/time placeholders in alertcondition messages only
alert                partial      string-compatible dynamic message runtime events when execution reaches the call, with const-string frequency subset only
log.*                unsupported  Pine Logs output functions require a host-owned log pane/output contract and are not implemented
strategy             partial      declaration plus strategy-mode runtime result; positive const numeric initial_capital, fixed, cash, and percent-of-equity default_qty subsets, supported cash-per-contract, cash-per-order, and percent commission modes, finite non-negative integer slippage ticks, finite non-negative integer limit-verification ticks, explicit close_entries_rule="FIFO" default allocation, and fixture-backed close_entries_rule="ANY" id-specific long-only close/exit allocation including same-entry-id partial exit allocation
strategy.account_currency partial default or explicitly declared currency.NONE account currency as a read-only simple string in strategy-mode scripts only; inherits the current fixed syminfo.currency value USD; supports simple-string consumers plus direct, UDF, and history reads; const-string consumers, indicator/requested-context use, mutation, non-NONE currency declarations or settings overrides, and cross-currency conversion remain unsupported; no public schema expansion
strategy.currency    partial      named const-string declaration subset accepting currency.NONE only as the explicit default no-conversion account-currency path; non-NONE currency values, settings overrides, and cross-currency conversion remain unsupported; no public schema expansion
strategy.convert_to_account partial default currency.NONE same-currency strategy-mode series-float identity from symbol currency to account currency; accepts one series/simple numeric value, coerces integers to floats, preserves typed na, and supports direct, named, UDF, and history calls; indicator/requested-context use and cross-currency conversion remain unsupported; no public schema expansion
strategy.convert_to_symbol partial default currency.NONE same-currency strategy-mode series-float identity from account currency to symbol currency; accepts one series/simple numeric value, coerces integers to floats, preserves typed na, and supports direct, named, UDF, and history calls; indicator/requested-context use and cross-currency conversion remain unsupported; no public schema expansion
strategy.default_entry_qty partial read-only strategy-mode series float that calculates the configured fixed, cash, or percent-of-equity default entry quantity at a supplied fill price without placing an order or adding position-reversal quantity; direct, named, UDF, and history reads are supported; cash and percent modes return na for non-positive or non-finite prices, and percent mode does the same for non-positive or non-finite supported equity; indicator/requested-context use, cross-currency conversion, symbol point value, precision, and lot-step handling remain unsupported; no public schema expansion
strategy.entry       partial      long market entry filled at next historical bar open plus long limit entry filled at limit price on a later historical bar when low <= limit or below the configured verified limit threshold, long stop entry filled at stop price on a later historical bar when high >= stop, and long stop-limit entry activated on a later historical bar when high >= stop then filled at limit price on a subsequent historical bar when low <= limit or below the configured verified limit threshold; configured slippage worsens long entry fill prices after trigger selection; explicit positive qty, fixed default qty, cash default qty resolved as cash/current close, or percent-of-equity default qty resolved at placement time from current supported equity and close; explicit active margin_long rejects fills whose required margin exceeds simulated equity at the actual fill price; same-direction long market entries honor the configured positive integer pyramiding limit, while multiple long limit, stop, or stop-limit entries triggered on the same historical fill pass can exceed that limit when they are all eligible in that pass; comment, alert_message, and disable_alert metadata syntax is semantically accepted and stored internally on pending and filled entries; supported fill payloads are exposed in `strategy.alerts`; explicit Python, CLI, and WASM host helpers can render `{{strategy.order.alert_message}}` for selected public fill events, while external alert delivery remains unsupported; same-tick exceptions beyond the fixture-backed long price-based entry subset remain unsupported; no public pending-order output
strategy.close       partial      full long-position close, fixed-qty partial close, or qty_percent partial close of the matching current long entry id at current bar close; fixed qty and qty_percent must be finite and positive; qty_percent resolves against the current matching position size; qty wins when both quantity forms are supplied; oversized quantities clamp to the current matching position size, keep remaining long position state open at the same average price, preserve the public strategy JSON shape without close order events, and cancel matching pending exits only when the close fully flattens the entry; configured slippage worsens the long close fill price; flat, wrong-entry, or repeated closes are no-op; comment, alert_message, and disable_alert syntax is accepted and stored internally on closed-trade metrics; supported fill payloads are exposed in `strategy.alerts`; explicit Python, CLI, and WASM host helpers can render `{{strategy.order.alert_message}}` for selected public fill events, while external alert delivery remains unsupported; immediately, partial strategy.close_all, and multi-entry close allocation remain unsupported
strategy.close_all   partial      full close of the current supported long position at current bar close; flat or already-closed calls are no-op; closed trade output uses the current entry id; comment, alert_message, and disable_alert syntax is accepted and stored internally on closed-trade metrics; supported fill payloads are exposed in `strategy.alerts`; explicit Python, CLI, and WASM host helpers can render `{{strategy.order.alert_message}}` for selected public fill events, while external alert delivery remains unsupported
strategy.cancel      partial      cancels matching internal pending entry ids and pending exit ids in the supported order subset; filled, unknown, and already-cancelled ids are no-op; no public pending-order output or cancellation records
strategy.cancel_all  partial      cancels all supported internal pending entries and pending exits; no-op when there are no pending orders; no public pending-order output or cancellation records
strategy equity      partial      per-bar cash, marketValue, equity, and netProfit snapshots; supports strategy.commission.cash_per_contract, strategy.commission.cash_per_order, and strategy.commission.percent commission debits plus declaration slippage applied to supported fill prices
strategy.position_size partial    current long-only position size read-only series in strategy-mode scripts only; supports fixture-backed control-flow, UDF argument, and history-reference interactions
strategy.position_avg_price partial current long-only average entry price read-only series, na when flat, in strategy-mode scripts only
strategy.position_entry_name partial entry order ID that initially opened the current continuous net long position as a read-only series string in strategy-mode scripts only; na while flat, preserved across pyramiding additions and partial allocation closes, and reset after the net position becomes flat; no public strategy-result schema expansion
strategy.initial_capital partial  configured or default broker starting capital as a read-only series float in strategy-mode scripts only; constant across bars with fixture-backed UDF and history reads; no public strategy-result schema expansion
strategy.max_contracts_held_all partial maximum contracts/shares/lots/units held over the whole trading range as a read-only series float in strategy-mode scripts only; aliases the supported long-only maximum while shorts are unsupported
strategy.max_contracts_held_long partial maximum long contracts/shares/lots/units held over the whole trading range as a read-only series float in strategy-mode scripts only
strategy.max_contracts_held_short partial maximum short contracts/shares/lots/units held over the whole trading range as a read-only series float in strategy-mode scripts only; remains 0.0 because short entries are unsupported
strategy.openprofit partial       current long-only unrealized profit read-only series, 0 when flat, in strategy-mode scripts only; supports fixture-backed control-flow, UDF argument, and history-reference interactions
strategy.openprofit_percent partial current long-only unrealized profit divided by realized equity as a read-only series float in strategy-mode scripts only; returns na for a non-positive or non-finite realized-equity denominator
strategy.netprofit  partial       cumulative realized closed-trade profit read-only series, excluding current open profit, in strategy-mode scripts only
strategy.netprofit_percent partial cumulative realized closed-trade profit as a percentage of initial_capital, excluding current open profit, in strategy-mode scripts only
strategy.grossprofit partial      cumulative positive realized closed-trade profit read-only series, excluding losing, flat, and current open trades, in strategy-mode scripts only
strategy.grossprofit_percent partial cumulative positive realized closed-trade profit as a percentage of initial_capital, excluding losing, flat, and current open trades, in strategy-mode scripts only
strategy.grossloss partial        cumulative realized closed-trade loss read-only series as a positive value, excluding winning, flat, and current open trades, in strategy-mode scripts only
strategy.grossloss_percent partial cumulative realized closed-trade loss as a positive percentage of initial_capital, excluding winning, flat, and current open trades, in strategy-mode scripts only
strategy.buy_and_hold_return_percent partial close-based buy-and-hold percentage return from the first loaded bar close, returning na when the first close is zero or non-finite, in strategy-mode scripts only
strategy.avg_trade partial        average realized profit/loss per closed trade read-only series, na before the first closed trade and excluding current open trades, in strategy-mode scripts only
strategy.avg_trade_percent partial average realized per-trade profit/loss percentage read-only series, using each closed trade entry value as denominator, na before the first closed trade and excluding current open trades, in strategy-mode scripts only
strategy.avg_winning_trade partial average realized profit among winning closed trades only, na before the first winning closed trade and excluding losing, flat, and current open trades, in strategy-mode scripts only
strategy.avg_winning_trade_percent partial average realized percentage gain among winning closed trades only, using each closed trade entry value as denominator, na before the first winning trade and excluding losing, flat, and current open trades, in strategy-mode scripts only
strategy.avg_losing_trade partial average realized loss among losing closed trades only as a positive value, na before the first losing closed trade and excluding winning, flat, and current open trades, in strategy-mode scripts only
strategy.avg_losing_trade_percent partial average realized percentage loss among losing closed trades only as a positive value, using each closed trade entry value as denominator, na before the first losing trade and excluding winning, flat, and current open trades, in strategy-mode scripts only
strategy.max_runup partial        maximum intrabar equity run-up amount read-only series over the current supported long-only trading interval, using supported entry equity, minimum equity before that entry, and the highest high reached while the supported position is open
strategy.max_runup_percent partial maximum intrabar equity run-up percentage read-only series over the current supported long-only trading interval, dividing the supported run-up amount by entry price times current supported position quantity and multiplying by 100
strategy.max_drawdown partial     maximum intrabar equity drawdown amount read-only series over the current supported long-only trading interval, using supported entry equity, maximum equity before that entry, and the lowest low reached while the supported position is open
strategy.max_drawdown_percent partial maximum intrabar equity drawdown percentage read-only series over the current supported long-only trading interval, dividing the supported drawdown amount by entry price times current supported position quantity and multiplying by 100
strategy.equity     partial       cash plus current market value read-only series in strategy-mode scripts only; without configured commission or slippage this matches initial_capital plus realized net profit plus current open profit, and with supported commission/slippage it reflects entry commission debits on open positions and slippage-adjusted fill prices
strategy.closedtrades partial     closed-trade count read-only series int in strategy-mode scripts only; immediate after strategy.close or strategy.close_all and next-bar visible after pending strategy.exit fills
strategy.closedtrades.first_index partial oldest retained closed-trade index read-only series int in strategy-mode scripts only; remains 0 in the current untrimmed ledger, including before the first close; platform order-limit trimming remains unsupported
strategy.closedtrades.* partial   closed-trade entry_price, entry_comment, entry_id, exit_price, exit_comment, exit_id, entry_bar_index, exit_bar_index, entry_time, exit_time, commission, size, profit, profit_percent, max_runup, max_runup_percent, max_drawdown, and max_drawdown_percent field functions in strategy-mode scripts only; entry_comment returns the retained entry comment when present; entry_id returns the retained entry id; exit_comment returns the retained close or selected exit comment when present; exit_id returns the retained close or exit id; commission is 0.0 without configured commission or supported entry-plus-exit commission when configured; max_runup returns the largest high-based favorable excursion retained for the selected closed trade quantity; max_drawdown returns the largest low-based adverse excursion retained for the selected closed trade quantity; the percentage helpers divide the selected amount by entry price times absolute quantity and multiply by 100; trade_num is zero-based integer-only and can read fixture-backed pyramided closed trades by index; invalid, negative, non-integer, or out-of-range indexes return na; no public runtime schema expansion
strategy.closedtrades.profit_percent partial closed-trade realized profit percentage field function in strategy-mode scripts only; can read fixture-backed pyramided closed trades by index; divides profit by entry price times absolute quantity and multiplies by 100; no public runtime schema expansion
strategy.closedtrades.max_runup partial closed-trade max runup field function in strategy-mode scripts only; can read fixture-backed pyramided closed trades by index; uses the largest high-based favorable excursion retained for the selected closed trade quantity; no public runtime schema expansion
strategy.closedtrades.max_runup_percent partial closed-trade max runup percentage field function in strategy-mode scripts only; can read fixture-backed pyramided closed trades by index; divides max runup by entry price times absolute quantity and multiplies by 100; no public runtime schema expansion
strategy.closedtrades.max_drawdown partial closed-trade max drawdown field function in strategy-mode scripts only; can read fixture-backed pyramided closed trades by index; uses the largest low-based adverse excursion retained for the selected closed trade quantity; no public runtime schema expansion
strategy.closedtrades.max_drawdown_percent partial closed-trade max drawdown percentage field function in strategy-mode scripts only; can read fixture-backed pyramided closed trades by index; divides max drawdown by entry price times absolute quantity and multiplies by 100; no public runtime schema expansion
strategy.closedtrades.entry_comment partial closed-trade entry comment field function in strategy-mode scripts only; returns the retained entry comment when present; can read fixture-backed commented pyramided closed trades by index; no public runtime schema expansion
strategy.closedtrades.exit_comment partial closed-trade exit comment field function in strategy-mode scripts only; returns the retained close or selected exit comment when present; can read fixture-backed commented pyramided closed trades by index; no public runtime schema expansion
strategy.wintrades partial        closed winning-trade count read-only series int in strategy-mode scripts only; counts closed trades with positive realized profit
strategy.losstrades partial       closed losing-trade count read-only series int in strategy-mode scripts only; counts closed trades with negative realized profit
strategy.eventrades partial       closed even-trade count read-only series int in strategy-mode scripts only; counts closed trades with zero realized profit
strategy.opentrades partial       open-trade count read-only series int in strategy-mode scripts only; returns 0 when flat, 1 for the default single-open-trade subset, and the fixture-backed open-trade ledger count for supported pyramiding entries
strategy.opentrades.* partial     open-trade field function subset limited to entry_price, entry_comment, entry_id, entry_bar_index, entry_time, size, profit, profit_percent, commission, max_runup, max_runup_percent, max_drawdown, and max_drawdown_percent over the current long-only open-trade ledger, plus the capital_held variable; entry_comment returns the retained entry comment when present; trade_num is zero-based and can read fixture-backed pyramided long open trades by index; invalid, negative, non-integer, out-of-range, or flat-state function reads return na; commission returns 0.0 without configured commission or current open supported entry commission when configured; max_runup returns the largest high-based favorable excursion seen so far for the selected open trade; max_drawdown returns the largest low-based adverse excursion seen so far for the selected open trade; the percentage helpers divide the selected amount by entry price times absolute quantity and multiply by 100; capital_held returns na without active margin, 0.0 while flat with active margin, and current open long market value times margin_long / 100 with explicit active margin_long; no public runtime schema expansion
strategy.opentrades.capital_held partial open-trade capital held variable in strategy-mode scripts only; returns na in the no-margin subset, 0.0 while flat with active margin, and current open long market value times margin_long / 100 while the supported long position is open, including after long-only forced liquidation reduces the position; short margin remains unsupported; no public runtime schema expansion
strategy.margin_liquidation_price partial long-only margin liquidation price read-only series in strategy-mode scripts only; returns na without active long margin, while flat, or when the long-margin denominator is unattainable; symbol tick rounding, short margin, and margin-specific public schema expansion remain unsupported
strategy.opentrades.entry_price partial current open-trade entry price field function in strategy-mode scripts only; can read fixture-backed pyramided long open trades by index; no public runtime schema expansion
strategy.opentrades.entry_comment partial current open-trade entry comment field function in strategy-mode scripts only; returns the retained entry comment when present; can read fixture-backed commented pyramided long open trades by index; no public runtime schema expansion
strategy.opentrades.entry_id partial current open-trade entry id field function in strategy-mode scripts only; can read fixture-backed pyramided long open trades by index; no public runtime schema expansion
strategy.opentrades.entry_bar_index partial current open-trade entry bar index field function in strategy-mode scripts only; can read fixture-backed pyramided long open trades by index; no public runtime schema expansion
strategy.opentrades.entry_time partial current open-trade entry time field function in strategy-mode scripts only; can read fixture-backed pyramided long open trades by index; no public runtime schema expansion
strategy.opentrades.size partial  current open-trade size field function in strategy-mode scripts only; can read fixture-backed pyramided long open trades by index; no public runtime schema expansion
strategy.opentrades.profit partial current open-trade floating profit field function in strategy-mode scripts only; can read fixture-backed pyramided long open trades by index; no public runtime schema expansion
strategy.opentrades.profit_percent partial current open-trade floating profit percentage field function in strategy-mode scripts only; can read fixture-backed pyramided long open trades by index; divides floating profit by entry price times absolute quantity and multiplies by 100; no public runtime schema expansion
strategy.opentrades.commission partial current open-trade commission field function in strategy-mode scripts only; can read fixture-backed pyramided long open trades by index; returns 0.0 without configured commission or selected open-trade supported entry commission when configured; no public runtime schema expansion
strategy.opentrades.max_runup partial current open-trade max runup field function in strategy-mode scripts only; can read fixture-backed pyramided long open trades by index; uses the largest high-based favorable excursion seen so far for the selected open trade; no public runtime schema expansion
strategy.opentrades.max_runup_percent partial current open-trade max runup percentage field function in strategy-mode scripts only; can read fixture-backed pyramided long open trades by index; divides max runup by entry price times absolute quantity and multiplies by 100; no public runtime schema expansion
strategy.opentrades.max_drawdown partial current open-trade max drawdown field function in strategy-mode scripts only; can read fixture-backed pyramided long open trades by index; uses the largest low-based adverse excursion seen so far for the selected open trade; no public runtime schema expansion
strategy.opentrades.max_drawdown_percent partial current open-trade max drawdown percentage field function in strategy-mode scripts only; can read fixture-backed pyramided long open trades by index; divides max drawdown by entry price times absolute quantity and multiplies by 100; no public runtime schema expansion
strategy.exit       partial      stop-only, limit-only, profit-only, loss-only, one-downside/one-upside bracket, trailing, and optional fixed-qty or qty-percent long exits; absolute stop/limit exits can match a requested open pyramided long entry id by `from_entry`, and omitted-`from_entry` absolute stop/limit exits can close all currently open pyramided long entries and persist for later open long entries until the position closes; single-trigger and bracket profit/loss tick exits plus trailing trail_points activation for an open pyramided long entry convert from the matched entry price; omitted-`from_entry` full profit/loss-tick exits and full stop+limit, stop+profit, loss+limit, or loss+profit brackets can close currently open pyramided long entries with unique entry ids using each entry price for relative legs when present; omitted-`from_entry` current full profit/loss-tick exits, full trail_points+trail_offset and trail_price+trail_offset trailing exits, plus full loss+profit, stop+profit, loss+limit, and stop+limit brackets can also close same-entry-id pyramided long trades using each open trade entry price; omitted-`from_entry` full profit/loss-tick exits, full trail_points+trail_offset and trail_price+trail_offset trailing exits, plus full loss+profit, stop+profit, loss+limit, and stop+limit brackets can also persist for later same-entry-id pyramided long trades using each later open trade entry price for relative legs when present; omitted-`from_entry` full profit/loss-tick exits and full loss+profit, stop+profit, and loss+limit brackets can also persist for later open long entries with unique entry ids until the position closes; omitted-`from_entry` full stop+limit brackets can also persist for later open long entries until the position closes; omitted-`from_entry` full trail_price+trail_offset trailing exits can close currently open pyramided long entries and persist for later open long entries until the position closes, and full trail_points+trail_offset trailing exits can do the same for currently open unique entry ids and persist for later open long entries with unique entry ids using each entry price for activation; exits matching multiple open trades with the same entry id emit one public exit order and one closed trade per matched ledger allocation; single-trigger same-calculation absolute stop/limit/trail_price attachment and single-trigger same-calculation entry-relative profit/loss/trail_points attachment to a pending entry are supported for the active entry id; active-entry relative bracket forms remain unsupported until Stage 10 behavior slices resolve deferred bracket legs; bracket forms are stop+limit, stop+profit, loss+limit, and loss+profit for the current one-net-long entry; trailing forms are trail_price+trail_offset and trail_points+trail_offset; profit/loss/trailing ticks convert with fixed syminfo.mintick; configured limit verification requires long limit/profit exit fills to move beyond the limit/profit price while preserving the original limit/profit fill price; qty is placement-time finite positive absolute quantity; qty_percent is placement-time finite positive percent resolved to an absolute quantity against current position size, matching open pyramided entry quantity, or matching pending entry quantity; when qty and qty_percent are both supplied, qty determines the reserved or filled quantity; omitted qty and qty_percent keep full-position one-effective-pending replacement behavior; explicit fixed-qty or qty-percent single-trigger, bracket, and trailing calls can keep multiple reserved pending exits; comment, comment_profit, comment_loss, comment_trailing, alert_message, alert_profit, alert_loss, alert_trailing, and disable_alert metadata syntax is semantically accepted and stored internally on pending and deferred exits; supported fill payloads are exposed in `strategy.alerts`; explicit Python, CLI, and WASM host helpers can render `{{strategy.order.alert_message}}` for selected public fill events, while external alert delivery remains unsupported; fills clamp to current position size, leave remaining long position open when partial, expose only absolute filled qty, and apply configured slippage to the long exit fill price after trigger selection; later-bar low <= stop/loss/active trailing stop or high >= verified limit/profit/activation price drives fills/activation; same-side touched exits fill in placement order; mixed downside/upside same-bar touches fill downside candidates only; bracket both-leg touches contribute the downside candidate; trailing activation bars do not fill; branch/switch/loop/state/history/incremental/host interactions fixture-backed
strategy.*           unsupported  strategy order functions beyond strategy.entry, the fixture-backed explicit/default-quantity market/limit/stop/stop-limit long and explicit-quantity reduce-only market short strategy.order subset, strategy.close/strategy.close_all/strategy.cancel/strategy.cancel_all, the supported single-trigger, one-downside/one-upside bracket, trailing, optional fixed-qty and qty-percent strategy.exit subset, and fixed-qty or qty-percent single-trigger/bracket/trailing multiple-exit reservation subset; strategy.order omitted qty for strategy.short, short exposure, reversals, short price-based orders, OCA, exit attachment semantics, and broader price-based order families; strategy.exit same-side pairs stop+loss and limit+profit, 3+ trigger/invalid trailing/multiple-pending outside that subset/omitted-quantity multiple reservations/reservation outside that subset/arbitrary future binding for unmatched `from_entry` ids; rich order types, cash/contracts sizing, mutable strategy state, margin behavior beyond long-entry affordability, long-only capital_held, and long-only forced liquidation, open-trade namespace functions outside entry_price/entry_comment/entry_id/entry_bar_index/entry_time/size/profit/profit_percent/commission/max_runup/max_runup_percent/max_drawdown/max_drawdown_percent/capital_held, closed-trade namespace members outside first_index/entry_price/entry_comment/entry_id/exit_price/exit_comment/exit_id/entry_bar_index/exit_bar_index/entry_time/exit_time/commission/size/profit/profit_percent/max_runup/max_runup_percent/max_drawdown/max_drawdown_percent, commission modes outside strategy.commission.cash_per_contract, strategy.commission.cash_per_order, and strategy.commission.percent, fill models beyond fixed-tick slippage and fixed-tick limit verification on supported long fills, and strategy reporting helpers beyond the supported initial-capital/position/profit/equity/count/held-quantity/runup/drawdown/buy-and-hold return and supported trade field variables are not implemented
array.*              partial      float/int/bool/string/color/color/label/line/linefill/polyline/box/table array creation through type-specific array.new_* calls and official array.new<type> syntax plus chart.point array.new<chart.point> construction and array.from inference, same-local scalar-tree UDT array.new<T>/array.from construction with typed array<T>/T[] declarations, simple-int array.new<T> size checks, size reads, array.get field reads, local field mutation with explicit same-UDT array.set writeback and direct chained same-slot field writeback, local pure UDF calls on values read from arrays, local pure method calls on values read into locals, array.set replacement, array.push append, array.insert same-UDT insertion, array.pop returns, array.remove returns, array.shift returns, array.unshift same-UDT prepend, array.fill same-UDT replacement, array.join positional UDT stringification, array.first reads, array.last reads, array.clear reset/reuse, array.copy independence, array.concat same-UDT append, array.slice parent-window read/write mirroring, array.reverse reordering, same-local and same-imported UDT array.sort and array.sort_indices by int/float/string sort_field, same-local scalar-tree and same-imported scalar-tree UDT-array includes/indexof/lastindexof structural equality search, same-local and same-imported scalar-tree UDT-array variable history snapshots, label, line, linefill, polyline, box, and table array for-in shallow-id iteration with getter/setter or lifecycle calls, chart-point array for-in value-copy iteration with field reads and local field mutation, same-local scalar-tree and same-imported scalar-tree UDT array for-in value-copy and index/value iteration with field reads and local field mutation, array<int>, array<float>, array<bool>, array<string>, array<color>, array<label>, array<line>, array<linefill>, array<polyline>, array<box>, array<table>, array<chart.point>, and same-local scalar-tree or same-imported scalar-tree UDT arrays index/value for-in iteration with a zero-based series int index loop local, and ordinary var realtime rollback, size, get/set/insert/remove with negative indexes, push/pop/shift/unshift, fill, first/last, copy, slice/concat, includes/indexof/lastindexof including linefill, polyline, chart.point object-array, and same-local plus same-imported scalar-tree UDT-array coverage, float/int/bool every/some, numeric binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev, float/int/string sort/sort_indices, reverse, scalar-array plus same-local scalar-tree and same-imported scalar-tree UDT-array join, clear, scalar array, scalar slice, label-array, label-slice, line-array, line-slice, box-array, box-slice, linefill-array, linefill-slice, polyline-array, polyline-slice, table-array, table-slice, chart.point-array, chart.point-slice, and same-local and same-imported scalar-tree UDT-array including first-bar array na predicates, scalar array/slice dynamic content reads plus repeated same-bar copy independence, label-array/slice repeated same-bar copy independence, line-array/slice repeated same-bar copy independence, box-array/slice repeated same-bar copy independence, linefill-array/slice repeated same-bar copy independence, polyline-array/slice repeated same-bar copy independence, table-array/slice repeated same-bar copy independence, chart.point-array/slice, and same-local and same-imported scalar-tree UDT-array dynamic na-offset predicates, dynamically selected historical chart.point-array/slice field reads plus repeated same-bar copy independence, dynamically selected historical drawing-id array/slice content reads for label, line, box, linefill, polyline, and table ids plus label, line, box, linefill, polyline, and table array/slice repeated same-bar copy independence, same-local and same-imported scalar-tree UDT-array/slice dynamic-history field reads plus same-local UDT-array/slice repeated same-bar copy independence, while-expression scalar-array result history snapshots including dynamic na-offset predicates and dynamically selected historical content reads, method-call syntax, and ordinary branch/loop plus independent while-loop control-flow coverage across supported non-UDT array operations only; fixture-backed same-local and same-imported scalar-tree UDT array identity through ternary, if, switch, for, for...in, and while results, including array/na branches, block aliases, typed/inferred declarations, and helper/iteration consumers, with per-call generic UDF lowering isolation; local UDF and user-method same-local scalar-tree UDT array returns preserve call-specific identity through direct parameters, block aliases, copy/new/from, nested local calls, named/reordered arguments, and final control flow, including A-to-B-to-A field-order interleaving; imported UDF and user-method same-imported scalar-tree UDT array returns preserve call-specific identity through direct parameters, block aliases, copy/new/from, private nested calls, final control-flow results, and typed method named/reordered arguments, including source-aware imported type-position rewrites and same-library dual-alias call-site isolation; local and imported UDF/method tuple returns preserve same-local or same-imported scalar-tree UDT-array identity independently for each destructured slot through direct, block, nested, final-flow, typed-na, typed-destination, A-to-B-to-A, same-library dual-alias, tuple-declaration direct/self-alias, control-flow, shadowing, later-destructuring, same-identity control-flow reassignment, and na-reassignment paths; cross-identity direct/control-flow reassignment, unresolved nested tuple consumers, and conflicting identities within one scalar return or tuple slot; qualified user-defined call results and unqualified local-UDF call results returning supported array kinds support direct size/get/first/last/copy/slice/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost reads, abs transformations, and min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev statistics plus int/float/string sort_indices transformations and applicable scalar/same-identity scalar-tree UDT join reads and same-kind live slice continuations; same-local or same-imported scalar-tree UDT-array results require concrete per-call identity, including named get indexes, empty/na reads, A-to-B-to-A, and dual-alias isolation; unqualified local-UDF call results returning scalar UDT values dispatch existing pure user methods; builtin-qualified calls outside the registered static-array producer allowlist, untyped unknown/na or non-array/non-UDT results, mixed/non-scalar UDT-array identities, helpers outside size/get/first/last/copy/slice/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev plus int/float/string sort_indices and scalar/same-identity scalar-tree UDT join, and UDF/method mutation side effects remain unsupported; local UDF and typed user-method UDT-array parameters preserve call-local element identity for value-only and index/value statement for-in plus final for-in expressions returning a field/scalar result, the UDT element itself, or a same-identity UDT array rebuilt from that element, including block-local array aliases, named method arguments, and A-to-B-to-A calls; registered static-array builtin/template producers (array.new_* and supported array.new<T>, array.from, array.copy, array.slice, array.concat, array.abs, array.standardize, and array.sort_indices) support direct call-result size/get/first/last/copy/slice/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost reads, abs transformations, and min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev statistics plus int/float/string sort_indices transformations and applicable scalar/same-identity scalar-tree UDT join reads and same-kind live slice continuations; array.concat still mutates and returns its first array, array.slice remains a live window, and other array results, other namespaces, map/matrix templates, broader postfix helpers, and postfix mutation remain gated; the exact non-array-namespace scalar-array producers str.split, ta.pivot_point_levels, matrix.row, matrix.col, matrix.eigenvalues, map.keys, and map.values support direct call-result size/get/first/last/copy/slice/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost reads, abs transformations, and min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev statistics plus int/float/string sort_indices transformations and applicable scalar/same-identity scalar-tree UDT join reads and same-kind live slice continuations, with copy/slice, numeric abs/standardize, and int/float/string sort_indices able to continue allowed array chains; array-returning namespace matrix.mult(...) overloads (matrix-by-array, array-by-matrix, and array-by-array) support the same nine all-kind helpers plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev plus int/float/string sort_indices with copy/slice/abs/standardize/sort_indices continuation and terminal scalar join; matrix-returning namespace matrix.mult(...) overloads are outside this array-helper evidence path; exact namespace matrix.mult(...) matrix results, matrix.copy(...)/matrix.transpose(...)/matrix.submatrix(...) SameAsArg results, and matrix.kron(...)/matrix.diff(...)/matrix.pow(...)/matrix.inv(...)/matrix.pinv(...)/matrix.eigenvectors(...) fixed simple-float-matrix results have a separately fixture-backed namespace-only rows()/columns()/elements_count()/get(row, column)/copy() subset documented under matrix.*, with copy preserving shape, transpose swapping shape, submatrix selecting an independent range, kron expanding both dimensions, diff preserving selected matrix shape and operand direction, pow preserving square shape across identity/copy/positive powers, inv preserving square shape or na for singular inputs, pinv swapping rectangular shape and preserving singular matrix results, eigenvectors preserving square shape or na for non-real or invalid-cell results, and copy/transpose/submatrix preserving float/int/bool/string/color element kinds; exact matrix.new<float>/matrix.new<int>/matrix.new<bool>/matrix.new<string>/matrix.new<color> template results support rows()/columns()/elements_count()/get(row, column)/copy() with element-kind preservation, default na cells, zero dimensions, fresh allocation, and copy-only continuation; exact bound matrix-receiver values.copy() results support the same direct reads/copy with preserved element kind and shape, independent storage, and copy-only continuation; exact bound matrix-receiver values.transpose() results support the same direct reads/copy with preserved element kind, swapped shape, independent storage, and copy-only continuation; exact bound matrix-receiver values.submatrix(...) results support the same direct reads/copy with preserved element kind, selected independent ranges, default and empty ranges, and copy-only continuation; exact bound numeric-matrix-receiver values.kron(other) results support the same direct reads/copy with expanded shape, fixed float-matrix results, independent storage, and copy-only continuation; exact bound numeric-matrix-receiver values.diff(other) results support the same direct reads/copy for matrix or scalar operands with selected matrix shape, operand direction, fixed float-matrix results, independent storage, and copy-only continuation; exact bound numeric-square-matrix-receiver values.pow(power) results support the same direct reads/copy across identity, copy, and positive powers with fixed float-matrix results, independent storage, and copy-only continuation; exact bound numeric-square-matrix-receiver values.inv() results support the same direct reads/copy with fixed float-matrix results, preserved invertible square shape, empty 0 x 0 results, na singular/invalid-cell results, independent storage, and copy-only continuation; exact bound numeric-matrix-receiver values.pinv() results support the same direct reads/copy with fixed float-matrix results, swapped rectangular shape, singular matrix results, swapped zero-cell shapes, na invalid-cell results, independent storage, and copy-only continuation; exact bound numeric-square-matrix-receiver values.eigenvectors() results support the same direct reads/copy with fixed float-matrix results, preserved real square shape, empty 0 x 0 results, na invalid-cell/non-real/incomplete results, independent storage, and copy-only continuation; exact bound numeric-matrix-receiver values.mult(other) matrix results support the same direct reads/copy for matrix or scalar operands with multiplied or preserved shape, fixed float-matrix results, na propagation, zero-inner-dimension behavior, independent storage, and copy-only continuation while array-result overloads retain array-helper dispatch; other bound matrix producers, non-matrix receivers, broader helpers, and mutation remain gated, while bound matrix-result call-result helpers, matrix/map templates, other namespace producers, broader postfix helpers, and postfix mutation remain gated
typed declarations                     partial      tests/fixtures/runtime/scalar_typed_declarations.pine;tests/fixtures/runtime/typed_declaration_qualifiers.pine;tests/fixtures/sema/supported_typed_declaration_qualifiers.pine;tests/fixtures/sema/supported_typed_na_declaration_qualifier_reassignment.pine;tests/fixtures/runtime/chart_point_typed_decl.pine;tests/fixtures/runtime/chart_point_typed_flow_decl.pine;tests/fixtures/runtime/chart_point_varip.pine;tests/fixtures/sema/supported_chart_point_varip.pine;tests/fixtures/runtime/drawing_typed_declarations.pine;tests/fixtures/runtime/array_typed_declarations.pine;tests/fixtures/runtime/chart_point_array_typed_declarations.pine;tests/fixtures/runtime/object_array_typed_declarations.pine;tests/fixtures/runtime/array_type_alias_declarations.pine;tests/fixtures/runtime/user_type_array_typed_declarations.pine;tests/fixtures/runtime/user_type_array_scalar_tree.pine;tests/fixtures/runtime/user_type_array_scalar_tree_helpers.pine;tests/fixtures/runtime/user_type_array_varip.pine;tests/fixtures/sema/supported_user_type_array_varip_decl.pine;tests/fixtures/runtime/import_udt_typed_declaration.pine;tests/fixtures/runtime/import_udt_var.pine;tests/fixtures/runtime/import_udt_varip.pine;tests/fixtures/runtime/import_udt_array_typed_declarations.pine;tests/fixtures/runtime/import_udt_array_scalar_tree.pine;tests/fixtures/runtime/import_udt_array_varip.pine;tests/fixtures/runtime/matrix_typed_declarations.pine;tests/fixtures/runtime/map_typed_declarations.pine;tests/fixtures/sema/supported_map_typed_decl.pine;tests/fixtures/sema/supported_map_control_flow.pine;tests/fixtures/sema/unsupported_scalar_typed_decl_initial.pine;tests/fixtures/sema/unsupported_chart_point_typed_decl_initial.pine;tests/fixtures/sema/unsupported_chart_point_array_typed_decl_initial.pine;tests/fixtures/sema/unsupported_array_typed_decl.pine;tests/fixtures/sema/unsupported_var_array_typed_decl.pine;tests/fixtures/sema/unsupported_array_na_typed_decl.pine;tests/fixtures/sema/unsupported_array_from_typed_decl.pine;tests/fixtures/sema/unsupported_array_typed_decl_initial.pine;tests/fixtures/sema/supported_user_type_array_decl.pine;tests/fixtures/sema/supported_user_type_array_alias_decl.pine;tests/fixtures/sema/unsupported_user_type_array_from_decl.pine;tests/fixtures/sema/supported_user_type_array_varip_nested_decl.pine;tests/fixtures/sema/unsupported_array_map_typed_decl.pine;tests/fixtures/sema/unsupported_array_matrix_typed_decl.pine;tests/fixtures/sema/unsupported_array_nested_typed_decl.pine;tests/fixtures/sema/unsupported_array_tuple_typed_decl.pine;tests/fixtures/sema/unsupported_array_strategy_typed_decl.pine;tests/fixtures/sema/unsupported_map_typed_decl.pine;tests/fixtures/sema/unsupported_map_typed_decl_template.pine;tests/fixtures/sema/unsupported_map_typed_decl_assign.pine;tests/fixtures/sema/unsupported_matrix_typed_decl.pine;tests/fixtures/sema/unsupported_matrix_int_typed_decl.pine;tests/fixtures/sema/unsupported_matrix_label_typed_decl.pine;tests/fixtures/runtime/user_type_varip.pine;tests/fixtures/sema/unsupported_user_type_varip_non_scalar_reassign.pine;tests/fixtures/sema/unsupported_user_type_varip_non_scalar_field_reassign.pine;tests/fixtures/sema/unsupported_user_type_varip_assign_identity.pine;tests/fixtures/sema/unsupported_imported_udt_typed_decl_identity.pine;tests/fixtures/sema/supported_imported_udt_array_decl.pine;tests/fixtures/sema/supported_imported_udt_array_alias_decl.pine;tests/fixtures/sema/unsupported_imported_udt_var_identity.pine;tests/fixtures/sema/unsupported_imported_udt_varip_identity.pine;tests/fixtures/sema/supported_user_type_varip_decl.pine;tests/fixtures/sema/supported_imported_udt_varip_decl.pine;tests/fixtures/sema/supported_imported_udt_varip_non_scalar_typed_na.pine;tests/fixtures/sema/unsupported_imported_udt_varip_non_scalar_reassign.pine;tests/fixtures/sema/unsupported_imported_udt_array_decl_non_scalar.pine;tests/fixtures/sema/unsupported_imported_udt_array_alias_decl_non_scalar.pine;tests/fixtures/sema/unsupported_imported_udt_array_varip_decl_non_scalar.pine;tests/fixtures/sema/unsupported_imported_udt_array_varip_alias_decl_non_scalar.pine;tests/fixtures/sema/supported_user_type_array_control_flow.pine;tests/fixtures/sema/unsupported_user_type_array_control_flow_identity.pine;tests/fixtures/sema/supported_imported_user_type_array_control_flow.pine;tests/fixtures/sema/unsupported_imported_user_type_array_control_flow_identity.pine;tests/fixtures/sema/supported_user_type_array_udf_method_returns.pine;tests/fixtures/sema/unsupported_user_type_array_udf_method_return_identities.pine;tests/fixtures/runtime/user_type_array_tuple_returns.pine;tests/fixtures/sema/supported_user_type_array_tuple_returns.pine;tests/fixtures/sema/unsupported_user_type_array_tuple_return_identities.pine;tests/fixtures/sema/unsupported_user_type_array_tuple_alias_mutation.pine;tests/fixtures/sema/unsupported_local_user_type_array_call_result_chaining.pine;tests/fixtures/runtime/import_udt_array_udf_method_returns.pine;tests/fixtures/sema/supported_imported_user_type_array_udf_method_returns.pine;tests/fixtures/sema/unsupported_imported_user_type_array_udf_method_return_identities.pine;tests/fixtures/runtime/import_udt_array_tuple_returns.pine;tests/fixtures/sema/supported_imported_user_type_array_tuple_returns.pine;tests/fixtures/sema/unsupported_imported_user_type_array_tuple_return_identities.pine;tests/fixtures/sema/unsupported_imported_user_type_array_tuple_alias_mutation.pine;tests/fixtures/sema/unsupported_imported_user_type_array_call_result_chaining.pine;tests/fixtures/libraries/import_udt_array_return_lib.pine;tests/fixtures/sema/supported_user_type_array_param_for_in.pine;tests/fixtures/runtime/builtin_array_call_result_reads.pine;tests/fixtures/sema/supported_builtin_array_call_result_reads.pine;tests/fixtures/sema/unsupported_builtin_array_call_result_reads.pine;tests/fixtures/runtime/builtin_namespace_array_call_result_reads.pine;tests/fixtures/sema/supported_builtin_namespace_array_call_result_reads.pine;tests/fixtures/sema/unsupported_builtin_namespace_array_call_result_reads.pine;tests/fixtures/runtime/builtin_namespace_matrix_call_result_reads.pine;tests/fixtures/sema/supported_builtin_namespace_matrix_call_result_reads.pine;tests/fixtures/sema/unsupported_builtin_namespace_matrix_call_result_reads.pine;tests/fixtures/runtime/bound_matrix_copy_call_result_reads.pine;tests/fixtures/sema/supported_bound_matrix_copy_call_result_reads.pine;tests/fixtures/sema/unsupported_bound_matrix_copy_call_result_reads.pine;tests/fixtures/runtime/bound_matrix_transpose_call_result_reads.pine;tests/fixtures/sema/supported_bound_matrix_transpose_call_result_reads.pine;tests/fixtures/sema/unsupported_bound_matrix_transpose_call_result_reads.pine;tests/fixtures/runtime/bound_matrix_submatrix_call_result_reads.pine;tests/fixtures/sema/supported_bound_matrix_submatrix_call_result_reads.pine;tests/fixtures/sema/unsupported_bound_matrix_submatrix_call_result_reads.pine;tests/fixtures/runtime/bound_matrix_kron_call_result_reads.pine;tests/fixtures/sema/supported_bound_matrix_kron_call_result_reads.pine;tests/fixtures/sema/unsupported_bound_matrix_kron_call_result_reads.pine;tests/fixtures/runtime/bound_matrix_diff_call_result_reads.pine;tests/fixtures/sema/supported_bound_matrix_diff_call_result_reads.pine;tests/fixtures/sema/unsupported_bound_matrix_diff_call_result_reads.pine;tests/fixtures/runtime/bound_matrix_pow_call_result_reads.pine;tests/fixtures/sema/supported_bound_matrix_pow_call_result_reads.pine;tests/fixtures/sema/unsupported_bound_matrix_pow_call_result_reads.pine;tests/fixtures/runtime/bound_matrix_inv_call_result_reads.pine;tests/fixtures/sema/supported_bound_matrix_inv_call_result_reads.pine;tests/fixtures/sema/unsupported_bound_matrix_inv_call_result_reads.pine;tests/fixtures/runtime/bound_matrix_pinv_call_result_reads.pine;tests/fixtures/sema/supported_bound_matrix_pinv_call_result_reads.pine;tests/fixtures/sema/unsupported_bound_matrix_pinv_call_result_reads.pine;tests/fixtures/runtime/bound_matrix_eigenvectors_call_result_reads.pine;tests/fixtures/sema/supported_bound_matrix_eigenvectors_call_result_reads.pine;tests/fixtures/sema/unsupported_bound_matrix_eigenvectors_call_result_reads.pine;tests/fixtures/runtime/bound_matrix_mult_call_result_reads.pine;tests/fixtures/sema/supported_bound_matrix_mult_call_result_reads.pine;tests/fixtures/sema/unsupported_bound_matrix_mult_call_result_reads.pine;tests/fixtures/runtime/local_udf_matrix_call_result_reads.pine;tests/fixtures/sema/supported_local_udf_matrix_call_result_reads.pine;tests/fixtures/sema/unsupported_local_udf_matrix_call_result_reads.pine;tests/fixtures/runtime/builtin_map_call_result_reads.pine;tests/fixtures/sema/supported_builtin_map_call_result_reads.pine;tests/fixtures/sema/unsupported_builtin_map_call_result_reads.pine;tests/fixtures/runtime/builtin_map_copy_call_result_reads.pine;tests/fixtures/sema/supported_builtin_map_copy_call_result_reads.pine;tests/fixtures/sema/unsupported_builtin_map_copy_call_result_reads.pine;tests/fixtures/runtime/local_udf_map_call_result_reads.pine;tests/fixtures/sema/supported_local_udf_map_call_result_reads.pine;tests/fixtures/sema/unsupported_local_udf_map_call_result_reads.pine;tests/fixtures/runtime/local_user_method_map_call_result_reads.pine;tests/fixtures/sema/supported_local_user_method_map_call_result_reads.pine;tests/fixtures/sema/unsupported_local_user_method_map_call_result_reads.pine;tests/fixtures/runtime/import_user_method_map_call_result_reads.pine;tests/fixtures/sema/supported_imported_user_method_map_call_result_reads.pine;tests/fixtures/sema/unsupported_imported_user_method_map_call_result_reads.pine;tests/fixtures/runtime/import_function_map_call_result_reads.pine;tests/fixtures/sema/supported_imported_function_map_call_result_reads.pine;tests/fixtures/sema/unsupported_imported_function_map_call_result_reads.pine;tests/fixtures/runtime/user_method_matrix_call_result_reads.pine;tests/fixtures/sema/supported_user_method_matrix_call_result_reads.pine;tests/fixtures/sema/unsupported_user_method_matrix_call_result_reads.pine;tests/fixtures/runtime/import_user_method_matrix_call_result_reads.pine;tests/fixtures/sema/supported_imported_user_method_matrix_call_result_reads.pine;tests/fixtures/sema/unsupported_imported_user_method_matrix_call_result_reads.pine;tests/fixtures/libraries/import_udt_lib.pine;tests/fixtures/runtime/import_function_matrix_call_result_reads.pine;tests/fixtures/sema/supported_imported_function_matrix_call_result_reads.pine;tests/fixtures/sema/unsupported_imported_function_matrix_call_result_reads.pine  fixture-backed explicit scalar declarations preserve non-na initializer qualifiers for const/input/simple values, explicit scalar typed-na declarations take const/input/simple qualifiers from later compatible scalar reassignments, and compatible reassignments can promote scalar typed declarations, including simple-parameter calls before promotion; fixture-backed int, float, bool, string, color, chart.point including direct values, na, if/switch/for/for...in/while expression results, and chart.point varip declarations, drawing-id label/line/linefill/box/table/polyline, scalar array<int>/array<float>/array<bool>/array<string>/array<color>, object-id array<label>/array<line>/array<linefill>/array<polyline>/array<box>/array<table>, array<chart.point>, same-local scalar-tree UDT array<T>, same-imported scalar-tree UDT array<lib.Type>/lib.Type[] declarations, same-local scalar-tree or same-imported scalar-tree UDT array varip declarations including same-local nested scalar-tree elements and same-imported array.new<lib.Type>() initialization, scalar-tree imported UDT declarations initialized or reassigned from the same imported identity, including ordinary var and scalar-tree varip declarations initialized from same-imported ternary/switch/if/for/for...in/while expressions, including nested same-imported scalar-tree Wrapper values, and equivalent type[] aliases for those supported array element types, including var declarations, the scalar typed-array varip subset, and explicitly typed same-local scalar-tree UDT varip declarations initialized from na, same-UDT constructors, same-UDT ternary expressions, same-UDT switch expressions, same-UDT if expressions, same-UDT for expressions, same-UDT for...in expressions, or same-UDT while expressions, including nested scalar-tree Wrapper values initialized from those expression forms, matrix<float>, matrix<int>, matrix<bool>, matrix<string>, or matrix<color> declarations with compatible or na initializers and later compatible reassignment, scalar map<K,V> declarations with compatible direct, na, or same-template control-flow initializers and later same-template reassignment, and bare scalar map declarations initialized from known direct or control-flow map expressions; bare array, template-less bare map declarations, map templates beyond int/float/bool/string/color keys and values, bare matrix, matrix templates beyond float/int/bool/string/color, cross-element matrix declaration initializers, and other typed declarations remain unsupported unless covered by narrower feature rows; fixture-backed same-local and same-imported scalar-tree UDT array identity through ternary, if, switch, for, for...in, and while results, including array/na branches, block aliases, typed/inferred declarations, and helper/iteration consumers, with per-call generic UDF lowering isolation; local UDF and user-method same-local scalar-tree UDT array returns preserve call-specific identity through direct parameters, block aliases, copy/new/from, nested local calls, named/reordered arguments, and final control flow, including A-to-B-to-A field-order interleaving; imported UDF and user-method same-imported scalar-tree UDT array returns preserve call-specific identity through direct parameters, block aliases, copy/new/from, private nested calls, final control-flow results, and typed method named/reordered arguments, including source-aware imported type-position rewrites and same-library dual-alias call-site isolation; local and imported UDF/method tuple returns preserve same-local or same-imported scalar-tree UDT-array identity independently for each destructured slot through direct, block, nested, final-flow, typed-na, typed-destination, A-to-B-to-A, same-library dual-alias, tuple-declaration direct/self-alias, control-flow, shadowing, later-destructuring, same-identity control-flow reassignment, and na-reassignment paths; cross-identity direct/control-flow reassignment, unresolved nested tuple consumers, and conflicting identities within one scalar return or tuple slot; qualified user-defined call results and unqualified local-UDF call results returning supported array kinds support direct size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost reads, abs transformations, and min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev statistics plus int/float/string sort_indices transformations and applicable scalar/same-identity scalar-tree UDT join reads; same-local or same-imported scalar-tree UDT-array results require concrete per-call identity, including named get indexes, empty/na reads, A-to-B-to-A, and dual-alias isolation; unqualified local-UDF call results returning scalar UDT values dispatch existing pure user methods; builtin-qualified calls outside the registered static-array producer allowlist, untyped unknown/na or non-array/non-UDT results, mixed/non-scalar UDT-array identities, helpers outside size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev plus int/float/string sort_indices and scalar/same-identity scalar-tree UDT join, and UDF/method mutation side effects remain unsupported; local UDF and typed user-method UDT-array parameters preserve call-local element identity for value-only and index/value statement for-in plus final for-in expressions returning a field/scalar result, the UDT element itself, or a same-identity UDT array rebuilt from that element, including block-local array aliases, named method arguments, and A-to-B-to-A calls; registered static-array builtin/template producers (array.new_* and supported array.new<T>, array.from, array.copy, array.slice, array.concat, array.abs, array.standardize, and array.sort_indices) support direct call-result size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost reads, abs transformations, and min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev statistics plus int/float/string sort_indices transformations and applicable scalar/same-identity scalar-tree UDT join reads; array.concat still mutates and returns its first array, array.slice remains a live window, and other array results, other namespaces, map/matrix templates, broader postfix helpers, and postfix mutation remain gated; the exact non-array-namespace scalar-array producers str.split, ta.pivot_point_levels, matrix.row, matrix.col, matrix.eigenvalues, map.keys, and map.values support direct call-result size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost reads, abs transformations, and min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev statistics plus int/float/string sort_indices transformations and applicable scalar/same-identity scalar-tree UDT join reads, with copy, numeric abs/standardize, and int/float/string sort_indices able to continue allowed array chains; array-returning namespace matrix.mult(...) overloads (matrix-by-array, array-by-matrix, and array-by-array) support the same eight all-kind helpers plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev plus int/float/string sort_indices with copy/abs/standardize/sort_indices continuation and terminal scalar join; namespace matrix.mult(...) matrix-by-matrix, matrix-by-scalar, and scalar-by-matrix direct results plus namespace matrix.copy(...)/matrix.transpose(...)/matrix.submatrix(...) SameAsArg results plus namespace matrix.kron(...)/matrix.diff(...)/matrix.pow(...)/matrix.inv(...)/matrix.pinv(...)/matrix.eigenvectors(...) fixed simple-float-matrix results support rows()/columns()/elements_count()/get(row, column)/copy()/row(index)/col(index), with copy preserving shape, transpose swapping shape, submatrix selecting an independent range, kron expanding both dimensions, diff preserving selected matrix shape and operand direction, pow preserving square shape across identity/copy/positive powers, inv preserving square shape or na for singular inputs, pinv swapping rectangular shape and preserving singular matrix results, eigenvectors preserving square shape or na for non-real or invalid-cell results, copy/transpose/submatrix preserving float/int/bool/string/color element kinds, and copy continuing matrix-helper chains and row switching to fresh element-kind-preserving size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev plus int/float/string sort_indices arrays with copy/abs/standardize/sort_indices continuation; exact matrix.new<float>/matrix.new<int>/matrix.new<bool>/matrix.new<string>/matrix.new<color> template results support rows()/columns()/elements_count()/get(row, column)/copy()/row(index)/col(index) with element-kind preservation, default na cells, zero dimensions, fresh allocation, and copy-only continuation; exact bound matrix-receiver values.copy() results support the same direct reads/copy with preserved element kind and shape, independent storage, and copy-only continuation; exact bound matrix-receiver values.transpose() results support the same direct reads/copy with preserved element kind, swapped shape, independent storage, and copy-only continuation; exact bound matrix-receiver values.submatrix(...) results support the same direct reads/copy with preserved element kind, selected independent ranges, default and empty ranges, and copy-only continuation; exact bound numeric-matrix-receiver values.kron(other) results support the same direct reads/copy with expanded shape, fixed float-matrix results, independent storage, and copy-only continuation; exact bound numeric-matrix-receiver values.diff(other) results support the same direct reads/copy for matrix or scalar operands with selected matrix shape, operand direction, fixed float-matrix results, independent storage, and copy-only continuation; exact bound numeric-square-matrix-receiver values.pow(power) results support the same direct reads/copy across identity, copy, and positive powers with fixed float-matrix results, independent storage, and copy-only continuation; exact bound numeric-square-matrix-receiver values.inv() results support the same direct reads/copy with fixed float-matrix results, preserved invertible square shape, empty 0 x 0 results, na singular/invalid-cell results, independent storage, and copy-only continuation; exact bound numeric-matrix-receiver values.pinv() results support the same direct reads/copy with fixed float-matrix results, swapped rectangular shape, singular matrix results, swapped zero-cell shapes, na invalid-cell results, independent storage, and copy-only continuation; exact bound numeric-square-matrix-receiver values.eigenvectors() results support the same direct reads/copy with fixed float-matrix results, preserved real square shape, empty 0 x 0 results, na invalid-cell/non-real/incomplete results, independent storage, and copy-only continuation; exact bound numeric-matrix-receiver values.mult(other) matrix results support the same direct reads/copy for matrix or scalar operands with multiplied or preserved shape, fixed float-matrix results, na propagation, zero-inner-dimension behavior, independent storage, and copy-only continuation while array-result overloads retain array-helper dispatch; other bound matrix producers, non-matrix receivers, broader helpers, and mutation remain gated; exact supported scalar map.new<K,V> template results support direct size()/get(key)/contains(key)/copy()/keys()/values() plus terminal put(key, value), clear(), remove(key), and put_all(source) with known key/value kinds, fresh empty allocation, independent copy, and copy-only continuation; map mutation other than terminal put/clear/remove/put_all and unsupported templates remain gated; exact namespace map.copy(existing) results support the same direct helpers and terminal put/clear/remove/put_all with retained key/value kinds, retained entries, independent backing storage, and copy-only continuation; non-map inputs and map mutation other than terminal put/clear/remove/put_all remain gated; supported call-result keys and values produce fresh key/value-kind-preserving arrays with size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev plus int/float/string sort_indices with copy/abs/standardize/sort_indices continuation and terminal scalar join; unqualified local-UDF results with one concrete supported scalar map template support the same direct size/get/contains/copy/keys/values helpers plus terminal put/clear/remove/put_all mutation across parameter passthrough, block aliases, nested calls, same-template control flow, constructed and copied results, named/reordered arguments, per-call int/float/bool/string/color key and value kinds, empty maps, independent copy storage, and copy-only continuation; imported pure-function results with one concrete supported scalar map template support the same helpers across alias-qualified, block-return, nested-function, same-template control-flow, constructed-result, scalar-template-interleaving, same-library dual-alias, independent-copy, and copy-only-continuation paths; local and imported user-method results retain their receiver-style, local-type-qualified or alias-qualified, and direct-constructor-receiver coverage; unknown/na, scalar, array, matrix, wrong-template or key/value, broader-helper, map mutation other than terminal put/clear/remove/put_all, array mutation, and terminal key/value-reader continuation boundaries remain gated; every concrete scalar map-result producer exposes the complete scalar map helper set, including terminal put(key, value), clear(), remove(key), and put_all(source), with concrete key/value-kind validation, insertion-order-preserving replacement or append, clear-to-empty behavior, existing/missing-key removal without retained-key reordering, same-template self-safe ordered put-all merging, void returns, no continuation, local UDF/user-method alias mutation, fresh-result isolation for map.new/map.copy/imported function/imported method producers, and UDF-side-effect rejection; the existing bound-receiver matrix_id.mult(array).size() path is unchanged, unqualified local-UDF results with a concrete supported matrix kind support the same seven direct helpers across parameter passthrough, block aliases, nested calls, same-kind control flow, constructed and matrix-operation results, call-specific float/int/bool/string/color kinds, zero dimensions, independent copy storage, named/reordered arguments, and copy-only continuation; local and imported user-method results with a concrete supported matrix kind support the same seven direct helpers across receiver-style, local-type-qualified or alias-qualified, direct-constructor-receiver, block/nested/same-kind-control-flow, call-specific float/int/bool/string/color, zero-dimension, same-library dual-alias, independent-copy, and copy-only-continuation paths; registered imported pure-function results with a concrete supported matrix kind support the same five helpers across alias-qualified, block-return, nested-function, same-kind-control-flow, constructed-result, call-specific float/int/bool/string/color, zero-dimension, same-library dual-alias, independent-copy, and copy-only-continuation paths; unknown/na, scalar, array, map, unregistered or unresolved user-function matrix results, broader-helper, mutation, and terminal-read continuation cases remain gated; every concrete matrix-result producer additionally exposes row(index) and col(index) as fresh element-kind-preserving arrays with size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev plus int/float/string sort_indices with copy/abs/standardize/sort_indices array continuation and applicable scalar/same-identity scalar-tree UDT join reads; concrete numeric matrix-result producers additionally expose eigenvalues() as a fresh array<float> under the existing numeric type check and square-matrix runtime boundary; every concrete matrix-result producer also exposes terminal is_square() as simple bool; concrete numeric matrix-result producers also expose terminal is_zero(), is_binary(), is_diagonal(), is_identity(), is_symmetric(), is_antisymmetric(), and is_stochastic() as simple bool values under the existing numeric type checks and value-predicate runtime rules, plus terminal sum(), avg(), min(), max(), mode(), trace(), and det() reads as series float values under the existing numeric aggregate runtime rules and terminal rank() reads as a series int under the existing numeric rank runtime rules; every concrete matrix-result producer also exposes transpose() and submatrix(...) as independent element-kind-preserving matrix continuations alongside copy(), with transpose swapping shape and submatrix selecting an optional half-open range; every concrete numeric matrix-result producer additionally exposes inv() as an independent fixed-float matrix continuation with the existing square, singular, invalid-cell, and upstream-na boundaries; the same numeric producer set additionally exposes pinv() as an independent fixed-float continuation that swaps rectangular shape, preserves singular matrix values and swapped zero-cell shapes, and retains invalid-cell/upstream-na propagation; it also exposes eigenvectors() as an independent fixed-float continuation that preserves square shape for complete real eigenvectors, returns empty 0 x 0, retains the non-square runtime error, and yields na for invalid-cell, non-real, incomplete, or upstream-na results; the same numeric producer set exposes pow(power) as an independent fixed-float continuation with the simple-int argument gate, square-matrix runtime boundary, identity/copy/positive-power behavior, empty 0 x 0 results, negative/na-power errors, and upstream-na propagation; the same numeric producer set additionally exposes kron(other) as an independent fixed-float continuation with a numeric-matrix operand gate, product-expanded row/column shape, na-cell and upstream-na propagation, zero-dimension preservation, independent storage, and the existing cell-budget error; the same numeric producer set additionally exposes diff(other) as an independent fixed-float continuation with a numeric-matrix-or-scalar operand gate, receiver-shape preservation, left-to-right subtraction, na-cell, na-scalar, and upstream-na propagation, zero-dimension preservation, independent storage, and the matching-shape runtime error for matrix operands; the same numeric producer set additionally exposes mult(other) with result-type-directed continuation: matrix and scalar operands yield independent fixed-float matrices with multiplied or preserved shape, numeric-array operands yield independent float arrays with one value per receiver row, and the resolved result selects the closed matrix or array helper set while retaining numeric operand gates, na propagation, zero-inner-dimension behavior, multiplication order, matrix cell-budget and dimension errors, and vector-length errors; producer-specific copy/diff/eigenvectors/inv/kron/mult/pinv/pow/submatrix/transpose-only wording applies only to matrix-result continuation, while broader matrix helpers and mutation remain gated
chart.point          partial      chart.point.new/now/from_index/from_time/copy constructors, time/index/price field reads, top-level field mutation, single chart.point value history with constant and dynamic na offsets including UDF-returned and method-returned point values, chart.point typed declarations including chart.point varip declarations with confirmed-bar history reads, and array.new<chart.point>/array.from chart-point array storage/read/mutation/search are fixture-backed; line.new, line point setters, box.new, box point setters, label.new, and label.set_point consume chart.point values through dedicated partial rows, and polyline.new consumes chart-point arrays through its dedicated partial row, including omitted line_color defaulting to color.blue and default/declaration-driven max-count eviction; polyline id arrays are fixture-backed through array.new_polyline, array.new<polyline>, array.from(polyline, ...), and array/slice history snapshots
map.*                                  partial      tests/fixtures/runtime/map_new_size.pine;tests/fixtures/runtime/map_put_get_contains.pine;tests/fixtures/runtime/map_clear.pine;tests/fixtures/runtime/map_remove.pine;tests/fixtures/runtime/map_copy.pine;tests/fixtures/runtime/map_methods.pine;tests/fixtures/runtime/map_keys_values.pine;tests/fixtures/runtime/map_for_in.pine;tests/fixtures/regressions/map_for_in_put_size_change.pine;tests/fixtures/regressions/map_for_in_key_put_size_change.pine;tests/fixtures/sema/supported_map_for_in.pine;tests/fixtures/runtime/map_put_all.pine;tests/fixtures/runtime/map_history.pine;tests/fixtures/runtime/map_varip.pine;tests/fixtures/runtime/map_udf_read.pine;tests/fixtures/runtime/map_typed_declarations.pine;tests/fixtures/runtime/map_control_flow.pine;tests/fixtures/realtime/map_rollback.pine;tests/fixtures/realtime/map_varip.pine;tests/fixtures/sema/supported_map_new_size.pine;tests/fixtures/sema/supported_map_size_simple_return_qualifier.pine;tests/fixtures/sema/unsupported_map_size_const_input_return_qualifier.pine;tests/fixtures/sema/supported_map_put_get_contains.pine;tests/fixtures/sema/supported_map_clear.pine;tests/fixtures/sema/supported_map_remove.pine;tests/fixtures/sema/supported_map_copy.pine;tests/fixtures/sema/supported_map_methods.pine;tests/fixtures/sema/supported_map_keys_values.pine;tests/fixtures/sema/supported_map_put_all.pine;tests/fixtures/sema/supported_map_history.pine;tests/fixtures/sema/supported_map_varip.pine;tests/fixtures/sema/supported_map_udf_read.pine;tests/fixtures/sema/supported_map_typed_decl.pine;tests/fixtures/sema/supported_map_control_flow.pine;tests/fixtures/sema/supported_map_udf_method_returns.pine;tests/fixtures/sema/unsupported_map_control_flow_template.pine;tests/fixtures/sema/unsupported_map_udf_method_return_templates.pine;tests/fixtures/sema/unsupported_map.pine;tests/fixtures/sema/unsupported_map_new_template.pine;tests/fixtures/sema/unsupported_map_new_dotted_template.pine;tests/fixtures/sema/unsupported_map_get.pine;tests/fixtures/sema/unsupported_map_contains.pine;tests/fixtures/sema/unsupported_map_put_key_type.pine;tests/fixtures/sema/unsupported_map_put_value_type.pine;tests/fixtures/sema/unsupported_map_get_key_type.pine;tests/fixtures/sema/unsupported_map_remove_key_type.pine;tests/fixtures/sema/unsupported_map_assign_template.pine;tests/fixtures/sema/unsupported_map_put_udf.pine;tests/fixtures/sema/unsupported_map_put_method_udf.pine;tests/fixtures/sema/unsupported_map_clear_udf.pine;tests/fixtures/sema/unsupported_map_remove_udf.pine;tests/fixtures/sema/unsupported_map_put_all_udf.pine;tests/fixtures/sema/unsupported_map_put_all_method_udf.pine;tests/fixtures/sema/unsupported_map_size.pine;tests/fixtures/sema/unsupported_map_remove.pine;tests/fixtures/sema/unsupported_map_clear.pine;tests/fixtures/sema/unsupported_map_copy.pine;tests/fixtures/sema/unsupported_map_keys.pine;tests/fixtures/sema/unsupported_map_values.pine;tests/fixtures/sema/unsupported_map_put_all.pine;tests/fixtures/sema/unsupported_map_put_all_template.pine;tests/fixtures/sema/unsupported_map_typed_decl.pine;tests/fixtures/sema/unsupported_map_typed_decl_template.pine;tests/fixtures/sema/unsupported_map_typed_decl_assign.pine;tests/fixtures/sema/supported_map_operation_return_qualifier.pine;tests/fixtures/sema/unsupported_map_operation_return_qualifier.pine;tests/fixtures/runtime/builtin_namespace_array_call_result_reads.pine;tests/fixtures/sema/supported_builtin_namespace_array_call_result_reads.pine;tests/fixtures/sema/unsupported_builtin_namespace_array_call_result_reads.pine;tests/fixtures/runtime/builtin_map_call_result_reads.pine;tests/fixtures/sema/supported_builtin_map_call_result_reads.pine;tests/fixtures/sema/unsupported_builtin_map_call_result_reads.pine;tests/fixtures/runtime/builtin_map_copy_call_result_reads.pine;tests/fixtures/sema/supported_builtin_map_copy_call_result_reads.pine;tests/fixtures/sema/unsupported_builtin_map_copy_call_result_reads.pine;tests/fixtures/runtime/local_udf_map_call_result_reads.pine;tests/fixtures/sema/supported_local_udf_map_call_result_reads.pine;tests/fixtures/sema/unsupported_local_udf_map_call_result_reads.pine;tests/fixtures/runtime/local_user_method_map_call_result_reads.pine;tests/fixtures/sema/supported_local_user_method_map_call_result_reads.pine;tests/fixtures/sema/unsupported_local_user_method_map_call_result_reads.pine;tests/fixtures/runtime/import_user_method_map_call_result_reads.pine;tests/fixtures/sema/supported_imported_user_method_map_call_result_reads.pine;tests/fixtures/sema/unsupported_imported_user_method_map_call_result_reads.pine;tests/fixtures/runtime/import_function_map_call_result_reads.pine;tests/fixtures/sema/supported_imported_function_map_call_result_reads.pine;tests/fixtures/sema/unsupported_imported_function_map_call_result_reads.pine  map.new<int|float|bool|string|color, int|float|bool|string|color>() creates runtime-owned map ids, scalar map<K,V> typed declarations with compatible direct, na, or same-template control-flow initialization and bare scalar map declarations initialized from known direct or control-flow map expressions are supported, map.size(id) returns the current entry count with fixture-backed fixed simple-int return qualifier coverage for namespace and method-call forms, map.get/map.contains return series value/bool results plus map.keys/map.values return simple key/value arrays with fixture-backed namespace and method-call return qualifier coverage, and map.put/get/contains/clear/remove/copy/keys/values/put_all plus equivalent size/get/contains/put/clear/remove/copy/keys/values/put_all method aliases are fixture-backed for scalar key/value templates with replacement, missing-key na, key-presence, full-clear, post-clear reuse, single-key removal, missing-key remove no-op, id-alias assignment, independent map.copy backing-store behavior, insertion-order map.keys/map.values array snapshots, insertion-order map.put_all merge semantics, same-template map metadata propagation through ternary, if, switch, for, for...in, and while expression results including map/na branches and block-local aliases with different branch templates rejected, direct for key in map and for [key, value] in map iteration over scalar maps in insertion order with statement and expression forms plus runtime rejection when the loop body changes map size, scalar map history snapshots with independent historical copies plus dynamic na-offset predicates, dynamically selected historical key/size reads, and repeated same-bar copy independence, scalar map varip intrabar backing-store handoff, known scalar map results returned from local UDFs or user methods through direct, block-local, constructor, copy, nested-call, and final control-flow paths for namespace-helper, history, for-in, and bound method-alias consumption, read-only UDF map helper calls, method-alias lowering, method mutation UDF rejection, and ordinary realtime rollback of map-store mutations; template-less bare map declarations, non-scalar key/value templates, and non-map map receivers remain unsupported; the exact non-array-namespace scalar-array producers str.split, ta.pivot_point_levels, matrix.row, matrix.col, matrix.eigenvalues, map.keys, and map.values support direct call-result size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost reads, abs transformations, and min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev statistics plus int/float/string sort_indices transformations and applicable scalar/same-identity scalar-tree UDT join reads, with copy, numeric abs/standardize, and int/float/string sort_indices able to continue allowed array chains; array-returning namespace matrix.mult(...) overloads (matrix-by-array, array-by-matrix, and array-by-array) support the same eight all-kind helpers plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev plus int/float/string sort_indices with copy/abs/standardize/sort_indices continuation and terminal scalar join; matrix-returning namespace matrix.mult(...) overloads are outside this array-helper evidence path; exact namespace matrix.mult(...) matrix results and matrix.copy(...)/matrix.transpose(...)/matrix.submatrix(...) SameAsArg results have a separately fixture-backed namespace-only rows()/columns()/elements_count()/get(row, column)/copy() subset documented under matrix.*, with copy preserving shape, transpose swapping shape, submatrix selecting an independent range, and all three preserving float/int/bool/string/color element kinds, while bound matrix-result call-result helpers, matrix/map templates, other namespace producers, broader postfix helpers, and postfix mutation remain gated; exact supported scalar map.new<K,V> template results support direct size()/get(key)/contains(key)/copy()/keys()/values() plus terminal put(key, value), clear(), remove(key), and put_all(source) with known key/value kinds, fresh empty allocation, independent copy, and copy-only continuation; map mutation other than terminal put/clear/remove/put_all and unsupported templates remain gated; exact namespace map.copy(existing) results support the same direct helpers and terminal put/clear/remove/put_all with retained key/value kinds, retained entries, independent backing storage, and copy-only continuation; non-map inputs and map mutation other than terminal put/clear/remove/put_all remain gated; supported call-result keys and values produce fresh key/value-kind-preserving arrays with size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev plus int/float/string sort_indices with copy/abs/standardize/sort_indices continuation and terminal scalar join; unqualified local-UDF results with one concrete supported scalar map template support the same direct size/get/contains/copy/keys/values helpers plus terminal put/clear/remove/put_all mutation across parameter passthrough, block aliases, nested calls, same-template control flow, constructed and copied results, named/reordered arguments, per-call int/float/bool/string/color key and value kinds, empty maps, independent copy storage, and copy-only continuation; imported pure-function results with one concrete supported scalar map template support the same helpers across alias-qualified, block-return, nested-function, same-template control-flow, constructed-result, scalar-template-interleaving, same-library dual-alias, independent-copy, and copy-only-continuation paths; local and imported user-method results retain their receiver-style, local-type-qualified or alias-qualified, and direct-constructor-receiver coverage; unknown/na, scalar, array, matrix, wrong-template or key/value, broader-helper, map mutation other than terminal put/clear/remove/put_all, array mutation, and terminal key/value-reader continuation boundaries remain gated; every concrete scalar map-result producer exposes the complete scalar map helper set, including terminal put(key, value), clear(), remove(key), and put_all(source), with concrete key/value-kind validation, insertion-order-preserving replacement or append, clear-to-empty behavior, existing/missing-key removal without retained-key reordering, same-template self-safe ordered put-all merging, void returns, no continuation, local UDF/user-method alias mutation, fresh-result isolation for map.new/map.copy/imported function/imported method producers, and UDF-side-effect rejection
matrix.*                               partial      tests/fixtures/runtime/matrix_float.pine;tests/fixtures/runtime/matrix_int.pine;tests/fixtures/runtime/matrix_bool.pine;tests/fixtures/runtime/matrix_string.pine;tests/fixtures/runtime/matrix_color.pine;tests/fixtures/runtime/matrix_zero_dimensions.pine;tests/fixtures/runtime/matrix_shape_loop_read.pine;tests/fixtures/runtime/matrix_shape_while_read.pine;tests/fixtures/runtime/matrix_control_flow.pine;tests/fixtures/runtime/matrix_set_method_control_flow.pine;tests/fixtures/runtime/matrix_set_while_control_flow.pine;tests/fixtures/runtime/matrix_fill_control_flow.pine;tests/fixtures/runtime/matrix_fill_while_control_flow.pine;tests/fixtures/runtime/matrix_sum.pine;tests/fixtures/runtime/matrix_avg.pine;tests/fixtures/runtime/matrix_min_max.pine;tests/fixtures/runtime/matrix_mode.pine;tests/fixtures/runtime/matrix_trace.pine;tests/fixtures/runtime/matrix_det.pine;tests/fixtures/runtime/matrix_eigenvalues.pine;tests/fixtures/runtime/matrix_eigenvectors.pine;tests/fixtures/runtime/matrix_inv.pine;tests/fixtures/runtime/matrix_pinv.pine;tests/fixtures/runtime/matrix_rank.pine;tests/fixtures/runtime/matrix_elements_count.pine;tests/fixtures/runtime/matrix_is_square.pine;tests/fixtures/runtime/matrix_is_binary.pine;tests/fixtures/runtime/matrix_is_diagonal.pine;tests/fixtures/runtime/matrix_is_identity.pine;tests/fixtures/runtime/matrix_is_symmetric.pine;tests/fixtures/runtime/matrix_is_antisymmetric.pine;tests/fixtures/runtime/matrix_is_stochastic.pine;tests/fixtures/runtime/matrix_is_zero.pine;tests/fixtures/runtime/matrix_transpose.pine;tests/fixtures/runtime/matrix_reverse.pine;tests/fixtures/runtime/matrix_udf_read.pine;tests/fixtures/runtime/matrix_udf_row_col.pine;tests/fixtures/runtime/matrix_udf_copy.pine;tests/fixtures/runtime/matrix_copy_loop.pine;tests/fixtures/runtime/matrix_copy_while.pine;tests/fixtures/runtime/while_expression_matrix.pine;tests/fixtures/runtime/while_expression_matrix_kinds.pine;tests/fixtures/runtime/while_expression_matrix_control.pine;tests/fixtures/runtime/while_expression_matrix_history.pine;tests/fixtures/runtime/while_expression_matrix_zero.pine;tests/fixtures/runtime/matrix_copy.pine;tests/fixtures/runtime/matrix_history.pine;tests/fixtures/runtime/matrix_history_shape.pine;tests/fixtures/runtime/matrix_dynamic_history.pine;tests/fixtures/runtime/matrix_typed_declarations.pine;tests/fixtures/runtime/matrix_varip.pine;tests/fixtures/realtime/matrix_varip.pine;tests/fixtures/runtime/matrix_reshape.pine;tests/fixtures/runtime/matrix_kron.pine;tests/fixtures/runtime/matrix_mult.pine;tests/fixtures/runtime/matrix_diff.pine;tests/fixtures/runtime/matrix_pow.pine;tests/fixtures/runtime/matrix_reshape_method.pine;tests/fixtures/runtime/matrix_reshape_control_flow.pine;tests/fixtures/runtime/matrix_reshape_while_control_flow.pine;tests/fixtures/runtime/matrix_row_col_loop_read.pine;tests/fixtures/runtime/matrix_row_col_branch_read.pine;tests/fixtures/runtime/matrix_row_col_while_read.pine;tests/fixtures/runtime/matrix_row.pine;tests/fixtures/runtime/matrix_row_method.pine;tests/fixtures/runtime/matrix_col.pine;tests/fixtures/runtime/matrix_col_method.pine;tests/fixtures/realtime/matrix_rollback.pine;tests/fixtures/realtime/matrix_reshape_rollback.pine;tests/fixtures/regressions/matrix_get_row_bounds.pine;tests/fixtures/regressions/matrix_get_column_bounds.pine;tests/fixtures/regressions/matrix_get_method_row_bounds.pine;tests/fixtures/regressions/matrix_get_method_column_bounds.pine;tests/fixtures/regressions/matrix_get_negative_row_bounds.pine;tests/fixtures/regressions/matrix_get_negative_column_bounds.pine;tests/fixtures/regressions/matrix_get_method_negative_row_bounds.pine;tests/fixtures/regressions/matrix_get_method_negative_column_bounds.pine;tests/fixtures/regressions/matrix_set_row_bounds.pine;tests/fixtures/regressions/matrix_set_column_bounds.pine;tests/fixtures/regressions/matrix_set_method_row_bounds.pine;tests/fixtures/regressions/matrix_set_method_column_bounds.pine;tests/fixtures/regressions/matrix_set_negative_row_bounds.pine;tests/fixtures/regressions/matrix_set_negative_column_bounds.pine;tests/fixtures/regressions/matrix_set_method_negative_row_bounds.pine;tests/fixtures/regressions/matrix_set_method_negative_column_bounds.pine;tests/fixtures/regressions/matrix_get_na_row_index.pine;tests/fixtures/regressions/matrix_get_na_column_index.pine;tests/fixtures/regressions/matrix_get_method_na_row_index.pine;tests/fixtures/regressions/matrix_get_method_na_column_index.pine;tests/fixtures/regressions/matrix_row_bounds.pine;tests/fixtures/regressions/matrix_col_bounds.pine;tests/fixtures/regressions/matrix_row_method_bounds.pine;tests/fixtures/regressions/matrix_col_method_bounds.pine;tests/fixtures/regressions/matrix_row_negative_bounds.pine;tests/fixtures/regressions/matrix_col_negative_bounds.pine;tests/fixtures/regressions/matrix_row_method_negative_bounds.pine;tests/fixtures/regressions/matrix_col_method_negative_bounds.pine;tests/fixtures/regressions/matrix_row_na_index.pine;tests/fixtures/regressions/matrix_row_method_na_index.pine;tests/fixtures/regressions/matrix_col_method_na_index.pine;tests/fixtures/regressions/matrix_col_na_index.pine;tests/fixtures/regressions/matrix_set_na_row_index.pine;tests/fixtures/regressions/matrix_set_method_na_row_index.pine;tests/fixtures/regressions/matrix_set_na_column_index.pine;tests/fixtures/regressions/matrix_set_method_na_column_index.pine;tests/fixtures/regressions/matrix_new_negative_row_count.pine;tests/fixtures/regressions/matrix_new_negative_column_count.pine;tests/fixtures/regressions/matrix_new_na_row_count.pine;tests/fixtures/regressions/matrix_new_na_column_count.pine;tests/fixtures/regressions/matrix_cell_limit.pine;tests/fixtures/regressions/matrix_kron_cell_limit.pine;tests/fixtures/regressions/matrix_call_result_kron_cell_limit.pine;tests/fixtures/regressions/matrix_mult_cell_limit.pine;tests/fixtures/regressions/matrix_call_result_mult_cell_limit.pine;tests/fixtures/regressions/matrix_mult_shape_mismatch.pine;tests/fixtures/regressions/matrix_call_result_mult_shape_mismatch.pine;tests/fixtures/regressions/matrix_call_result_mult_array_size_mismatch.pine;tests/fixtures/regressions/matrix_diff_shape_mismatch.pine;tests/fixtures/regressions/matrix_call_result_diff_shape_mismatch.pine;tests/fixtures/regressions/matrix_pow_non_square.pine;tests/fixtures/regressions/matrix_call_result_pow_non_square.pine;tests/fixtures/regressions/matrix_pow_negative_power.pine;tests/fixtures/regressions/matrix_call_result_pow_negative_power.pine;tests/fixtures/regressions/matrix_call_result_pow_na_power.pine;tests/fixtures/regressions/matrix_reshape_mismatch.pine;tests/fixtures/regressions/matrix_det_non_square.pine;tests/fixtures/regressions/matrix_eigenvalues_non_square.pine;tests/fixtures/regressions/matrix_eigenvectors_non_square.pine;tests/fixtures/regressions/matrix_call_result_eigenvectors_non_square.pine;tests/fixtures/regressions/matrix_inv_non_square.pine;tests/fixtures/regressions/matrix_call_result_inv_non_square.pine;tests/fixtures/regressions/matrix_reshape_method_mismatch.pine;tests/fixtures/regressions/matrix_reshape_negative_row_count.pine;tests/fixtures/regressions/matrix_reshape_method_negative_row_count.pine;tests/fixtures/regressions/matrix_reshape_negative_column_count.pine;tests/fixtures/regressions/matrix_reshape_method_negative_column_count.pine;tests/fixtures/regressions/matrix_reshape_na_row_count.pine;tests/fixtures/regressions/matrix_reshape_method_na_row_count.pine;tests/fixtures/regressions/matrix_reshape_na_column_count.pine;tests/fixtures/regressions/matrix_reshape_method_na_column_count.pine;tests/fixtures/sema/unsupported_matrix.pine;tests/fixtures/sema/unsupported_matrix_sum.pine;tests/fixtures/sema/unsupported_matrix_sum_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_avg.pine;tests/fixtures/sema/unsupported_matrix_avg_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_min.pine;tests/fixtures/sema/unsupported_matrix_min_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_max.pine;tests/fixtures/sema/unsupported_matrix_max_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_mode.pine;tests/fixtures/sema/unsupported_matrix_mode_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_trace.pine;tests/fixtures/sema/unsupported_matrix_trace_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_det.pine;tests/fixtures/sema/unsupported_matrix_det_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_eigenvalues.pine;tests/fixtures/sema/unsupported_matrix_eigenvalues_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_eigenvectors.pine;tests/fixtures/sema/unsupported_matrix_eigenvectors_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_kron.pine;tests/fixtures/sema/unsupported_matrix_kron_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_kron_value.pine;tests/fixtures/sema/unsupported_matrix_kron_method_value.pine;tests/fixtures/sema/unsupported_matrix_mult.pine;tests/fixtures/sema/unsupported_matrix_mult_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_mult_value.pine;tests/fixtures/sema/unsupported_matrix_mult_method_value.pine;tests/fixtures/sema/unsupported_matrix_mult_scalar_pair.pine;tests/fixtures/sema/supported_matrix_mult_array_pair.pine;tests/fixtures/sema/unsupported_matrix_mult_bool_array.pine;tests/fixtures/sema/unsupported_matrix_diff.pine;tests/fixtures/sema/unsupported_matrix_diff_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_diff_value.pine;tests/fixtures/sema/unsupported_matrix_diff_method_value.pine;tests/fixtures/sema/unsupported_matrix_diff_scalar_pair.pine;tests/fixtures/sema/unsupported_matrix_pow.pine;tests/fixtures/sema/unsupported_matrix_pow_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_pow_power.pine;tests/fixtures/sema/unsupported_matrix_pow_method_power.pine;tests/fixtures/sema/unsupported_matrix_inv.pine;tests/fixtures/sema/unsupported_matrix_inv_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_pinv.pine;tests/fixtures/sema/unsupported_matrix_pinv_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_rank.pine;tests/fixtures/sema/unsupported_matrix_rank_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_elements_count.pine;tests/fixtures/sema/unsupported_matrix_elements_count_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_is_square.pine;tests/fixtures/sema/unsupported_matrix_is_square_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_is_binary.pine;tests/fixtures/sema/unsupported_matrix_is_binary_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_is_diagonal.pine;tests/fixtures/sema/unsupported_matrix_is_diagonal_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_is_identity.pine;tests/fixtures/sema/unsupported_matrix_is_identity_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_is_symmetric.pine;tests/fixtures/sema/unsupported_matrix_is_symmetric_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_is_antisymmetric.pine;tests/fixtures/sema/unsupported_matrix_is_antisymmetric_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_is_stochastic.pine;tests/fixtures/sema/unsupported_matrix_is_stochastic_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_is_zero.pine;tests/fixtures/sema/unsupported_matrix_is_zero_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_transpose.pine;tests/fixtures/sema/unsupported_matrix_transpose_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_reverse.pine;tests/fixtures/sema/unsupported_matrix_reverse_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_add_row.pine;tests/fixtures/sema/unsupported_matrix_add_col.pine;tests/fixtures/sema/unsupported_matrix_remove_row.pine;tests/fixtures/sema/unsupported_matrix_remove_col.pine;tests/fixtures/sema/unsupported_matrix_rows.pine;tests/fixtures/sema/unsupported_matrix_rows_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_columns.pine;tests/fixtures/sema/unsupported_matrix_columns_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_row.pine;tests/fixtures/sema/unsupported_matrix_row_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_row_index_type.pine;tests/fixtures/sema/unsupported_matrix_row_method_index_type.pine;tests/fixtures/sema/unsupported_matrix_col.pine;tests/fixtures/sema/unsupported_matrix_col_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_col_index_type.pine;tests/fixtures/sema/unsupported_matrix_col_method_index_type.pine;tests/fixtures/sema/unsupported_matrix_get.pine;tests/fixtures/sema/unsupported_matrix_get_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_get_row_type.pine;tests/fixtures/sema/unsupported_matrix_get_column_type.pine;tests/fixtures/sema/unsupported_matrix_get_method_row_type.pine;tests/fixtures/sema/unsupported_matrix_get_method_column_type.pine;tests/fixtures/sema/unsupported_matrix_copy.pine;tests/fixtures/sema/unsupported_matrix_copy_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_set.pine;tests/fixtures/sema/unsupported_matrix_set_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_set_row_type.pine;tests/fixtures/sema/unsupported_matrix_set_column_type.pine;tests/fixtures/sema/unsupported_matrix_set_value.pine;tests/fixtures/sema/unsupported_matrix_set_method_value.pine;tests/fixtures/sema/unsupported_matrix_set_method_row_type.pine;tests/fixtures/sema/unsupported_matrix_set_method_column_type.pine;tests/fixtures/sema/unsupported_matrix_fill.pine;tests/fixtures/sema/unsupported_matrix_fill_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_fill_value.pine;tests/fixtures/sema/unsupported_matrix_fill_method_value.pine;tests/fixtures/sema/unsupported_matrix_reshape.pine;tests/fixtures/sema/unsupported_matrix_reshape_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_reshape_row_type.pine;tests/fixtures/sema/unsupported_matrix_reshape_column_type.pine;tests/fixtures/sema/unsupported_matrix_reshape_method_row_type.pine;tests/fixtures/sema/unsupported_matrix_reshape_method_column_type.pine;tests/fixtures/sema/unsupported_matrix_new_template.pine;tests/fixtures/sema/unsupported_matrix_new_deferred_template.pine;tests/fixtures/sema/unsupported_matrix_new_initial_value.pine;tests/fixtures/sema/supported_matrix_new_bool.pine;tests/fixtures/sema/supported_matrix_new_string.pine;tests/fixtures/sema/supported_matrix_new_color.pine;tests/fixtures/sema/unsupported_matrix_new_bool_initial_value.pine;tests/fixtures/sema/unsupported_matrix_bool_sum.pine;tests/fixtures/sema/unsupported_matrix_bool_set_float.pine;tests/fixtures/sema/unsupported_matrix_bool_fill_float.pine;tests/fixtures/sema/unsupported_matrix_new_string_initial_value.pine;tests/fixtures/sema/unsupported_matrix_string_sum.pine;tests/fixtures/sema/unsupported_matrix_string_set_float.pine;tests/fixtures/sema/unsupported_matrix_string_fill_float.pine;tests/fixtures/sema/unsupported_matrix_new_color_initial_value.pine;tests/fixtures/sema/unsupported_matrix_color_sum.pine;tests/fixtures/sema/unsupported_matrix_color_set_float.pine;tests/fixtures/sema/unsupported_matrix_color_fill_float.pine;tests/fixtures/sema/supported_matrix_new_int.pine;tests/fixtures/sema/unsupported_matrix_new_int_initial_value.pine;tests/fixtures/sema/unsupported_matrix_int_set_float.pine;tests/fixtures/sema/unsupported_matrix_int_fill_float.pine;tests/fixtures/sema/unsupported_matrix_int_add_row_float_array.pine;tests/fixtures/sema/unsupported_matrix_int_add_col_float_array.pine;tests/fixtures/sema/unsupported_matrix_set_udf.pine;tests/fixtures/sema/unsupported_matrix_set_method_udf.pine;tests/fixtures/sema/unsupported_matrix_fill_udf.pine;tests/fixtures/sema/unsupported_matrix_fill_method_udf.pine;tests/fixtures/sema/unsupported_matrix_reshape_udf.pine;tests/fixtures/sema/unsupported_matrix_reshape_method_udf.pine;tests/fixtures/sema/unsupported_matrix_reverse_udf.pine;tests/fixtures/sema/unsupported_matrix_reverse_method_udf.pine;tests/fixtures/sema/unsupported_matrix_method.pine;tests/fixtures/sema/unsupported_matrix_add_row_method.pine;tests/fixtures/sema/unsupported_matrix_add_col_method.pine;tests/fixtures/sema/unsupported_matrix_remove_row_method.pine;tests/fixtures/sema/unsupported_matrix_remove_col_method.pine;tests/fixtures/sema/unsupported_matrix_typed_decl.pine;tests/fixtures/sema/unsupported_matrix_int_typed_decl.pine;tests/fixtures/sema/unsupported_matrix_label_typed_decl.pine;tests/fixtures/sema/supported_matrix_varip.pine;tests/fixtures/runtime/matrix_add_row.pine;tests/fixtures/regressions/matrix_add_row_bounds.pine;tests/fixtures/regressions/matrix_add_row_size_mismatch.pine;tests/fixtures/sema/supported_matrix_add_row.pine;tests/fixtures/sema/unsupported_matrix_add_row_udf.pine;tests/fixtures/sema/unsupported_matrix_add_row_method_udf.pine;tests/fixtures/runtime/matrix_add_col.pine;tests/fixtures/regressions/matrix_add_col_bounds.pine;tests/fixtures/regressions/matrix_add_col_size_mismatch.pine;tests/fixtures/sema/supported_matrix_add_col.pine;tests/fixtures/sema/unsupported_matrix_add_col_udf.pine;tests/fixtures/sema/unsupported_matrix_add_col_method_udf.pine;tests/fixtures/runtime/matrix_remove_row.pine;tests/fixtures/regressions/matrix_remove_row_bounds.pine;tests/fixtures/regressions/matrix_remove_row_na_index.pine;tests/fixtures/sema/supported_matrix_remove_row.pine;tests/fixtures/sema/unsupported_matrix_remove_row_udf.pine;tests/fixtures/sema/unsupported_matrix_remove_row_method_udf.pine;tests/fixtures/runtime/matrix_remove_col.pine;tests/fixtures/runtime/matrix_swap_rows.pine;tests/fixtures/runtime/matrix_swap_columns.pine;tests/fixtures/runtime/matrix_sort.pine;tests/fixtures/runtime/matrix_submatrix.pine;tests/fixtures/regressions/matrix_remove_col_bounds.pine;tests/fixtures/regressions/matrix_remove_col_na_index.pine;tests/fixtures/regressions/matrix_swap_rows_bounds.pine;tests/fixtures/regressions/matrix_swap_rows_na_index.pine;tests/fixtures/regressions/matrix_swap_columns_bounds.pine;tests/fixtures/regressions/matrix_swap_columns_na_index.pine;tests/fixtures/regressions/matrix_sort_bounds.pine;tests/fixtures/regressions/matrix_sort_na_index.pine;tests/fixtures/regressions/matrix_sort_unsupported_order.pine;tests/fixtures/regressions/matrix_submatrix_bounds.pine;tests/fixtures/regressions/matrix_call_result_submatrix_bounds.pine;tests/fixtures/regressions/matrix_submatrix_na_index.pine;tests/fixtures/regressions/matrix_submatrix_reversed_row_range.pine;tests/fixtures/regressions/matrix_submatrix_reversed_column_range.pine;tests/fixtures/sema/supported_matrix_remove_col.pine;tests/fixtures/sema/supported_matrix_swap_rows.pine;tests/fixtures/sema/supported_matrix_swap_columns.pine;tests/fixtures/sema/supported_matrix_sort.pine;tests/fixtures/sema/supported_matrix_submatrix.pine;tests/fixtures/sema/unsupported_matrix_swap_columns.pine;tests/fixtures/sema/unsupported_matrix_swap_columns_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_swap_columns_column1.pine;tests/fixtures/sema/unsupported_matrix_swap_columns_column2.pine;tests/fixtures/sema/unsupported_matrix_swap_columns_method_column1.pine;tests/fixtures/sema/unsupported_matrix_swap_columns_method_column2.pine;tests/fixtures/sema/unsupported_matrix_sort.pine;tests/fixtures/sema/unsupported_matrix_sort_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_sort_column.pine;tests/fixtures/sema/unsupported_matrix_sort_order.pine;tests/fixtures/sema/unsupported_matrix_sort_method_column.pine;tests/fixtures/sema/unsupported_matrix_sort_method_order.pine;tests/fixtures/sema/unsupported_matrix_submatrix.pine;tests/fixtures/sema/unsupported_matrix_submatrix_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_submatrix_from_row.pine;tests/fixtures/sema/unsupported_matrix_submatrix_to_row.pine;tests/fixtures/sema/unsupported_matrix_submatrix_from_column.pine;tests/fixtures/sema/unsupported_matrix_submatrix_to_column.pine;tests/fixtures/sema/unsupported_matrix_submatrix_method_from_row.pine;tests/fixtures/sema/unsupported_matrix_submatrix_method_to_row.pine;tests/fixtures/sema/unsupported_matrix_submatrix_method_from_column.pine;tests/fixtures/sema/unsupported_matrix_submatrix_method_to_column.pine;tests/fixtures/sema/unsupported_matrix_swap_rows.pine;tests/fixtures/sema/unsupported_matrix_swap_rows_method_receiver.pine;tests/fixtures/sema/unsupported_matrix_swap_rows_row1.pine;tests/fixtures/sema/unsupported_matrix_swap_rows_row2.pine;tests/fixtures/sema/unsupported_matrix_swap_rows_method_row1.pine;tests/fixtures/sema/unsupported_matrix_swap_rows_method_row2.pine;tests/fixtures/sema/unsupported_matrix_remove_col_udf.pine;tests/fixtures/sema/unsupported_matrix_remove_col_method_udf.pine;tests/fixtures/sema/unsupported_matrix_swap_rows_udf.pine;tests/fixtures/sema/unsupported_matrix_swap_rows_method_udf.pine;tests/fixtures/sema/unsupported_matrix_swap_columns_udf.pine;tests/fixtures/sema/unsupported_matrix_swap_columns_method_udf.pine;tests/fixtures/sema/unsupported_matrix_sort_udf.pine;tests/fixtures/sema/unsupported_matrix_sort_method_udf.pine;tests/fixtures/sema/supported_matrix_sum.pine;tests/fixtures/sema/supported_matrix_avg.pine;tests/fixtures/sema/supported_matrix_min_max.pine;tests/fixtures/sema/supported_matrix_mode.pine;tests/fixtures/sema/supported_matrix_trace.pine;tests/fixtures/sema/supported_matrix_det.pine;tests/fixtures/sema/supported_matrix_eigenvalues.pine;tests/fixtures/sema/supported_matrix_eigenvectors.pine;tests/fixtures/sema/supported_matrix_kron.pine;tests/fixtures/sema/supported_matrix_mult.pine;tests/fixtures/sema/supported_matrix_diff.pine;tests/fixtures/sema/supported_matrix_pow.pine;tests/fixtures/sema/supported_matrix_inv.pine;tests/fixtures/sema/supported_matrix_pinv.pine;tests/fixtures/sema/supported_matrix_rank.pine;tests/fixtures/sema/supported_matrix_elements_count.pine;tests/fixtures/sema/supported_matrix_dimension_simple_return_qualifier.pine;tests/fixtures/sema/unsupported_matrix_dimension_const_input_return_qualifier.pine;tests/fixtures/sema/supported_matrix_is_square.pine;tests/fixtures/sema/supported_matrix_is_binary.pine;tests/fixtures/sema/supported_matrix_is_diagonal.pine;tests/fixtures/sema/supported_matrix_is_identity.pine;tests/fixtures/sema/supported_matrix_is_symmetric.pine;tests/fixtures/sema/supported_matrix_is_antisymmetric.pine;tests/fixtures/sema/supported_matrix_is_stochastic.pine;tests/fixtures/sema/supported_matrix_is_zero.pine;tests/fixtures/sema/supported_matrix_predicate_simple_bool_return_qualifier.pine;tests/fixtures/sema/unsupported_matrix_predicate_const_bool_return_qualifier.pine;tests/fixtures/sema/supported_matrix_transpose.pine;tests/fixtures/sema/supported_matrix_reverse.pine;tests/fixtures/runtime/matrix_for_in.pine;tests/fixtures/sema/supported_matrix_for_in.pine;tests/fixtures/sema/supported_matrix_row_col_array_return_qualifier.pine;tests/fixtures/sema/unsupported_matrix_row_col_array_return_qualifier.pine;tests/fixtures/sema/supported_matrix_same_as_arg_return_qualifier.pine;tests/fixtures/sema/unsupported_matrix_same_as_arg_return_qualifier.pine;tests/fixtures/sema/supported_matrix_get_series_element_return_qualifier.pine;tests/fixtures/sema/unsupported_matrix_get_const_input_return_qualifier.pine;tests/fixtures/sema/supported_matrix_fixed_float_collection_return_qualifier.pine;tests/fixtures/sema/unsupported_matrix_fixed_float_collection_return_qualifier.pine;tests/fixtures/sema/supported_matrix_new_fixed_simple_return_qualifier.pine;tests/fixtures/sema/unsupported_matrix_new_fixed_simple_return_qualifier.pine;tests/fixtures/sema/supported_matrix_mult_return_qualifier.pine;tests/fixtures/sema/unsupported_matrix_mult_return_qualifier.pine;tests/fixtures/sema/supported_matrix_aggregate_return_qualifier.pine;tests/fixtures/sema/unsupported_matrix_aggregate_const_input_return_qualifier.pine;tests/fixtures/runtime/builtin_namespace_array_call_result_reads.pine;tests/fixtures/sema/supported_builtin_namespace_array_call_result_reads.pine;tests/fixtures/sema/unsupported_builtin_namespace_array_call_result_reads.pine;tests/fixtures/runtime/builtin_namespace_matrix_call_result_reads.pine;tests/fixtures/sema/supported_builtin_namespace_matrix_call_result_reads.pine;tests/fixtures/sema/unsupported_builtin_namespace_matrix_call_result_reads.pine;tests/fixtures/runtime/bound_matrix_copy_call_result_reads.pine;tests/fixtures/sema/supported_bound_matrix_copy_call_result_reads.pine;tests/fixtures/sema/unsupported_bound_matrix_copy_call_result_reads.pine;tests/fixtures/runtime/bound_matrix_transpose_call_result_reads.pine;tests/fixtures/sema/supported_bound_matrix_transpose_call_result_reads.pine;tests/fixtures/sema/unsupported_bound_matrix_transpose_call_result_reads.pine;tests/fixtures/runtime/bound_matrix_submatrix_call_result_reads.pine;tests/fixtures/sema/supported_bound_matrix_submatrix_call_result_reads.pine;tests/fixtures/sema/unsupported_bound_matrix_submatrix_call_result_reads.pine;tests/fixtures/runtime/bound_matrix_kron_call_result_reads.pine;tests/fixtures/sema/supported_bound_matrix_kron_call_result_reads.pine;tests/fixtures/sema/unsupported_bound_matrix_kron_call_result_reads.pine;tests/fixtures/runtime/bound_matrix_diff_call_result_reads.pine;tests/fixtures/sema/supported_bound_matrix_diff_call_result_reads.pine;tests/fixtures/sema/unsupported_bound_matrix_diff_call_result_reads.pine;tests/fixtures/runtime/bound_matrix_pow_call_result_reads.pine;tests/fixtures/sema/supported_bound_matrix_pow_call_result_reads.pine;tests/fixtures/sema/unsupported_bound_matrix_pow_call_result_reads.pine;tests/fixtures/runtime/bound_matrix_inv_call_result_reads.pine;tests/fixtures/sema/supported_bound_matrix_inv_call_result_reads.pine;tests/fixtures/sema/unsupported_bound_matrix_inv_call_result_reads.pine;tests/fixtures/runtime/bound_matrix_pinv_call_result_reads.pine;tests/fixtures/sema/supported_bound_matrix_pinv_call_result_reads.pine;tests/fixtures/sema/unsupported_bound_matrix_pinv_call_result_reads.pine;tests/fixtures/runtime/bound_matrix_eigenvectors_call_result_reads.pine;tests/fixtures/sema/supported_bound_matrix_eigenvectors_call_result_reads.pine;tests/fixtures/sema/unsupported_bound_matrix_eigenvectors_call_result_reads.pine;tests/fixtures/runtime/bound_matrix_mult_call_result_reads.pine;tests/fixtures/sema/supported_bound_matrix_mult_call_result_reads.pine;tests/fixtures/sema/unsupported_bound_matrix_mult_call_result_reads.pine;tests/fixtures/runtime/local_udf_matrix_call_result_reads.pine;tests/fixtures/sema/supported_local_udf_matrix_call_result_reads.pine;tests/fixtures/sema/unsupported_local_udf_matrix_call_result_reads.pine;tests/fixtures/runtime/user_method_matrix_call_result_reads.pine;tests/fixtures/sema/supported_user_method_matrix_call_result_reads.pine;tests/fixtures/sema/unsupported_user_method_matrix_call_result_reads.pine;tests/fixtures/runtime/import_user_method_matrix_call_result_reads.pine;tests/fixtures/sema/supported_imported_user_method_matrix_call_result_reads.pine;tests/fixtures/sema/unsupported_imported_user_method_matrix_call_result_reads.pine;tests/fixtures/libraries/import_udt_lib.pine;tests/fixtures/runtime/import_function_matrix_call_result_reads.pine;tests/fixtures/sema/supported_imported_function_matrix_call_result_reads.pine;tests/fixtures/sema/unsupported_imported_function_matrix_call_result_reads.pine  matrix.new<float>, matrix.new<int>, matrix.new<bool>, matrix.new<string>, matrix.new<color>, matrix.get, matrix.set, matrix.fill, values.fill(value), values.get(row, column), values.set(row, column, value), matrix.copy, values.copy(), matrix.transpose, values.transpose(), matrix.reverse, values.reverse(), matrix.reshape, values.reshape(rows, columns), matrix.kron, values.kron(other), matrix.mult, values.mult(other), matrix.diff, values.diff(other), matrix.pow, values.pow(power), matrix.add_row, values.add_row(row, array_id), matrix.add_col, values.add_col(column, array_id), matrix.remove_row, values.remove_row(row), matrix.remove_col, values.remove_col(column), matrix.swap_rows, values.swap_rows(row1, row2), matrix.swap_columns, values.swap_columns(column1, column2), matrix.sort, values.sort(column?, order?), matrix.submatrix, values.submatrix(from_row?, to_row?, from_column?, to_column?), matrix.rows, values.rows(), matrix.columns, values.columns(), matrix.elements_count, values.elements_count(), matrix.is_square, values.is_square(), matrix.is_binary, values.is_binary(), matrix.is_diagonal, values.is_diagonal(), matrix.is_identity, values.is_identity(), matrix.is_symmetric, values.is_symmetric(), matrix.is_antisymmetric, values.is_antisymmetric(), matrix.is_stochastic, values.is_stochastic(), matrix.is_zero, values.is_zero(), matrix.sum, values.sum(), matrix.avg, values.avg(), matrix.min, values.min(), matrix.max, values.max(), matrix.mode, values.mode(), matrix.trace, values.trace(), matrix.det, values.det(), matrix.eigenvalues, values.eigenvalues(), matrix.eigenvectors, values.eigenvectors(), matrix.inv, values.inv(), matrix.pinv, values.pinv(), matrix.rank, values.rank(), matrix.row, values.row(row), matrix.col, and values.col(column) are supported for runtime-owned float matrices with rectangular storage, while matrix.new<bool> plus matrix.get, matrix.set, matrix.fill, matrix.copy, matrix.transpose, matrix.reverse, matrix.reshape, matrix.submatrix, matrix.row, matrix.col, matrix.add_row, matrix.add_col, matrix.remove_row, matrix.remove_col, matrix.swap_rows, matrix.swap_columns, matrix.rows, matrix.columns, matrix.elements_count, and matrix.is_square are supported for runtime-owned bool matrices with bool or na cells and matrix<bool> typed declarations, while matrix.new<string> plus matrix.get, matrix.set, matrix.fill, matrix.copy, matrix.transpose, matrix.reverse, matrix.reshape, matrix.submatrix, matrix.row, matrix.col, matrix.add_row, matrix.add_col, matrix.remove_row, matrix.remove_col, matrix.swap_rows, matrix.swap_columns, matrix.rows, matrix.columns, matrix.elements_count, and matrix.is_square are supported for runtime-owned string matrices with string or na cells and matrix<string> typed declarations, while matrix.new<color> plus matrix.get, matrix.set, matrix.fill, matrix.copy, matrix.transpose, matrix.reverse, matrix.reshape, matrix.submatrix, matrix.row, matrix.col, matrix.add_row, matrix.add_col, matrix.remove_row, matrix.remove_col, matrix.swap_rows, matrix.swap_columns, matrix.rows, matrix.columns, matrix.elements_count, and matrix.is_square are supported for runtime-owned color matrices with color or na cells and matrix<color> typed declarations, while matrix.new<int> plus matrix.get, matrix.set, matrix.fill, matrix.copy, matrix.transpose, matrix.reverse, matrix.reshape, matrix.submatrix, matrix.row, matrix.col, matrix.kron, matrix.mult, matrix.diff, matrix.pow, matrix.add_row, matrix.add_col, matrix.remove_row, matrix.remove_col, matrix.swap_rows, matrix.swap_columns, matrix.sort, matrix.rows, matrix.columns, matrix.elements_count, matrix.is_square, matrix.is_binary, matrix.is_diagonal, matrix.is_identity, matrix.is_symmetric, matrix.is_antisymmetric, matrix.is_stochastic, matrix.is_zero, matrix.sum, matrix.avg, matrix.min, matrix.max, matrix.mode, matrix.trace, matrix.det, matrix.eigenvalues, matrix.eigenvectors, matrix.inv, matrix.pinv, matrix.rank, and the corresponding supported method aliases are supported for runtime-owned int matrices with int or na cells, and matrix<float>/matrix<int>/matrix<bool>/matrix<string>/matrix<color> typed declarations, namespace and method-call reshape preserving element order and count, namespace and method-call reshape element-count mismatch errors, namespace and method-call Kronecker products returning independent expanded-shape matrices with na cell propagation and cell-budget errors, namespace and method-call matrix-by-matrix multiplication returning independent matrix results with multiplied shape, scalar namespace multiplication returning same-shape independent matrix results, matrix-array, array-matrix, and numeric array-pair multiplication returning independent array results, na cell propagation, shape-mismatch errors, and cell-budget errors, namespace and method-call matrix-by-matrix subtraction and scalar namespace subtraction returning independent matrix results with matching shape, na cell propagation, and shape-mismatch errors, namespace and method-call matrix powers returning independent identity, copy, and powered matrices with na propagation, non-square errors, and negative-power errors, namespace and method-call row/column insertion from element-kind-matched array snapshots, including array<float> for float matrices, array<int> for int matrices, and array<bool> for bool matrices, array<string> for string matrices, and array<color> for color matrices, namespace and method-call row/column deletion, namespace and method-call row swaps preserving shape, namespace and method-call column swaps preserving shape, namespace and method-call row sorting by a selected column with default column 0, ascending/descending order, stable equal-key row order, and na placement, namespace and method-call submatrix copies returning independent matrix ranges with default full ranges and empty row/column slices, fixture-backed SameAsArg simple-matrix return qualifier coverage for namespace/method matrix.copy, matrix.transpose, and matrix.submatrix, namespace and method-call element-count reads, fixture-backed fixed simple-int return qualifier coverage for namespace matrix.rows/matrix.columns/matrix.elements_count and method-call values.rows()/values.columns()/values.elements_count(), fixture-backed fixed simple-bool return qualifier coverage for namespace matrix.is_square/matrix.is_binary/matrix.is_diagonal/matrix.is_identity/matrix.is_symmetric/matrix.is_antisymmetric/matrix.is_stochastic/matrix.is_zero and method-call predicate aliases, namespace and method-call square-shape predicates, namespace and method-call binary-value predicates over 0/1 cells that return false for `na` cells and true for zero-element matrices, namespace and method-call diagonal-value predicates that allow any main-diagonal value, require zero off-diagonal cells, return false for off-diagonal `na` cells, do not require square shapes, and return true for zero-element matrices, namespace and method-call identity-value predicates that require square shapes, exact one-valued main diagonals, exact zero-valued off-diagonals, return false for `na` cells, and return true for empty `0 x 0` matrices, namespace and method-call symmetric-value predicates that require square shapes, matching transposed numeric cells, return false for `na` cells, and return true for empty `0 x 0` matrices, namespace and method-call antisymmetric-value predicates that require square shapes, exact zero-valued main diagonals, negated transposed off-diagonal numeric cells, return false for `na` cells, and return true for empty `0 x 0` matrices, namespace and method-call stochastic-value predicates over finite non-negative numeric cells where every row or every column sums exactly to one, returning false for `na`, negative, or zero-element matrices, namespace and method-call zero-value predicates that return false for `na` cells and true for zero-element matrices, namespace and method-call transposes returning independent matrix copies with swapped row/column counts, namespace and method-call matrix reversals mutating cells in place while preserving shape, fixture-backed fixed simple-float-array return qualifier coverage for matrix.eigenvalues plus fixed simple-float-matrix return qualifier coverage for matrix.eigenvectors/matrix.kron/matrix.diff/matrix.pow/matrix.inv/matrix.pinv namespace and method forms, namespace and method-call matrix sums, averages, minimums, maximums, modes, traces, determinants, and ranks with fixture-backed fixed series-float return qualifier coverage for sum/avg/min/max/mode/trace/det plus fixed series-int return qualifier coverage for rank, namespace and method-call eigenvalue arrays, eigenvector matrices, inverse matrices, and pseudo-inverse matrices, where aggregate readers ignore na cells and return na for empty or all-na matrices, determinants return na for any na cell and runtime-error on non-square matrices, eigenvalue arrays return independent array<float> results for square matrices with real eigenvalues, return empty arrays for empty matrices, return na for any na cell or non-real eigenvalue result, and runtime-error on non-square matrices, eigenvector matrices return independent matrix<float> results whose columns are real eigenvectors for square matrices, return empty matrices for empty matrices, return na for any na cell or non-real or incomplete eigenvector result, and runtime-error on non-square matrices, inverse matrices return independent matrix results for non-singular square matrices, return na for singular or any na cell, and runtime-error on non-square matrices, pseudo-inverse matrices return independent swapped-shape matrix results for square, singular, and rectangular matrices, return zero-cell swapped-shape results for zero-row or zero-column matrices, and return na for any na cell, ranks support rectangular matrices and return na for any na cell, and modes return na for no repeated numeric cells, numeric/na cell values, int-to-float coercion, zero row/column dimensions, shape reads, shape reads through ordinary for and while loops, fixture-backed MatrixArray simple-array return qualifier coverage for namespace matrix.row/matrix.col and method-call values.row(row)/values.col(column), namespace and method-call row/column extraction returning independent array<float> snapshots for float matrices, array<int> snapshots for int matrices, array<bool> snapshots for bool matrices, array<string> snapshots for string matrices, and array<color> snapshots for color matrices, row/column extraction reads through ordinary branches, for loops, and while loops, read-only UDF cell/shape reads and row/column extraction reads, UDF-returned independent copies, loop-local independent copies, while-loop independent copies, while-expression fresh/alias/zero/break/continue/history matrix results including dynamic na-offset predicates, set/get/fill/reshape mutation, branch/loop set/fill/reshape mutation ordering, while-loop set/fill/reshape mutation ordering, add-row/add-column insertion ordering, row/column deletion ordering, row-swap and column-swap mutation ordering, explicit independent copies, assignment/reference aliasing, ordinary var persistence, committed matrix history snapshots with first-bar na predicate output, shape snapshots with first-bar na predicate output and dynamic na-offset predicate output, and dynamic-offset matrix snapshots returning fresh copies plus na-offset matrix predicate output and repeated same-bar copy independence after sibling historical copy mutation/reshape, realtime forming-bar rollback for matrix mutation and shape changes, runtime profile slot/cell counters, row/column matrix.get runtime bounds errors, fixture-backed MatrixElement series return qualifier coverage for namespace matrix.get and method-call values.get(row, column), values.get(row, column) method row/column runtime bounds errors, namespace matrix.row/matrix.col row/column extraction runtime bounds errors, values.row(row)/values.col(column) method row/column extraction runtime bounds errors, namespace matrix.row/matrix.col negative row/column extraction runtime bounds errors, values.row(row)/values.col(column) method negative row/column extraction runtime bounds errors, namespace matrix.row/matrix.col na row/column extraction runtime bounds errors, values.row(row)/values.col(column) method na row/column extraction runtime bounds errors, negative row/column matrix.get index bounds errors, values.get(row, column) method negative row/column runtime bounds errors, matrix.set row/column bounds errors, values.set(row, column, value) method row/column bounds errors, negative matrix.set row/column bounds errors, values.set(row, column, value) method negative row/column bounds errors, na row/column matrix cell index errors, values.get(row, column) method na row/column index errors, values.set(row, column, value) method na row/column index errors, negative namespace matrix.reshape row/column-count errors, negative values.reshape(rows, columns) method row/column-count errors, na namespace matrix.reshape row/column-count errors, na values.reshape(rows, columns) method row/column-count errors, negative and na constructor-dimension errors, non-square matrix.det runtime errors, non-square matrix.eigenvalues runtime errors, non-square matrix.eigenvectors runtime errors, non-square matrix.inv runtime errors, matrix get/copy/transpose/reverse non-matrix receiver diagnostics including values.get(row, column), values.copy(), values.transpose(), and values.reverse() method receiver diagnostics, matrix sum/average/min/max/mode/trace/det/eigenvalues/eigenvectors/kron/mult/diff/pow/inv/pinv/rank/is_binary/is_diagonal/is_identity/is_symmetric/is_antisymmetric/is_stochastic/is_zero non-matrix receiver diagnostics including values.sum()/values.avg()/values.min()/values.max()/values.mode()/values.trace()/values.det()/values.eigenvalues()/values.eigenvectors()/values.kron(other)/values.mult(other)/values.diff(other)/values.pow(power)/values.inv()/values.pinv()/values.rank()/values.is_binary()/values.is_diagonal()/values.is_identity()/values.is_symmetric()/values.is_antisymmetric()/values.is_stochastic()/values.is_zero() method receiver diagnostics, non-int matrix.get row/column index diagnostics including values.get(row, column) row/column index diagnostics, non-int namespace matrix.set row/column index diagnostics including values.set(row, column, value) row/column index diagnostics, non-int namespace matrix.reshape row/column-count diagnostics and values.reshape(rows, columns) method row/column-count diagnostics, matrix shape-reader non-matrix receiver diagnostics including values.rows()/values.columns()/values.elements_count()/values.is_square() method receiver diagnostics, matrix row/column extraction non-matrix receiver diagnostics including values.row(row)/values.col(column) method receiver diagnostics, non-int namespace matrix.row/matrix.col row/column-index diagnostics and values.row(row)/values.col(column) method row/column-index diagnostics, non-int namespace/method matrix.add_row row-index diagnostics, non-int namespace/method matrix.add_col column-index diagnostics, non-int namespace/method matrix.remove_row row-index diagnostics, non-int namespace/method matrix.remove_col column-index diagnostics, non-int namespace/method matrix.swap_rows row-index diagnostics, non-int namespace/method matrix.swap_columns column-index diagnostics, non-int namespace/method matrix.sort column-index diagnostics, non-const-string namespace/method matrix.sort order diagnostics, matrix row/column insertion data element-kind mismatch diagnostics, matrix mutating-helper non-matrix receiver diagnostics including values.set(row, column, value), values.fill(value), values.reverse(), values.reshape(rows, columns), values.add_row(row, array_id), values.add_col(column, array_id), values.remove_row(row), values.remove_col(column), values.swap_rows(row1, row2), values.swap_columns(column1, column2), and values.sort(column?, order?) method receiver diagnostics, non-numeric matrix.new<float> initial value diagnostics, non-numeric float-matrix matrix.set/fill value diagnostics, non-int int-matrix matrix.set/fill value diagnostics, non-bool bool-matrix matrix.set/fill value diagnostics, and non-string string-matrix matrix.set/fill value diagnostics, and non-color color-matrix matrix.set/fill value diagnostics including values.set(row, column, value) and values.fill(value), the runtime cell-budget guard, matrix.kron cell-budget errors, matrix.mult cell-budget and shape-mismatch errors, matrix.diff shape-mismatch errors, matrix.pow non-square and negative-power errors, matrix.add_row row bounds errors, matrix.add_row row-array size mismatch errors, matrix.add_col column bounds errors, matrix.add_col column-array size mismatch errors, matrix.remove_row row bounds errors, matrix.remove_row na row-index errors, matrix.remove_col column bounds errors, matrix.remove_col na column-index errors, matrix.swap_rows row bounds errors, matrix.swap_rows na row-index errors, matrix.swap_columns column bounds errors, matrix.swap_columns na column-index errors, matrix.sort column bounds errors, matrix.sort na column-index errors, and matrix.sort unsupported-order errors; matrix.set, matrix.fill, matrix.reverse, matrix.reshape, matrix.add_row, matrix.add_col, matrix.remove_row, matrix.remove_col, matrix.swap_rows, matrix.swap_columns, and matrix.sort, including values.set(row, column, value), values.fill(value), values.reverse(), values.reshape(rows, columns), values.add_row(row, array_id), values.add_col(column, array_id), values.remove_row(row), values.remove_col(column), values.swap_rows(row1, row2), values.swap_columns(column1, column2), and values.sort(column?, order?), remain unsupported inside user-defined functions through the collection side-effect gate; deferred matrix.new templates, matrix method syntax beyond values.fill(value), values.get(row, column), values.set(row, column, value), values.copy(), values.transpose(), values.reverse(), values.reshape(rows, columns), values.sum(), values.avg(), values.min(), values.max(), values.mode(), values.trace(), values.det(), values.eigenvalues(), values.eigenvectors(), values.kron(other), values.mult(other), values.diff(other), values.pow(power), values.inv(), values.pinv(), values.rank(), values.is_binary(), values.is_diagonal(), values.is_identity(), values.is_symmetric(), values.is_antisymmetric(), values.is_stochastic(), values.is_zero(), values.elements_count(), values.row(row), values.col(column), values.add_row(row, array_id), values.add_col(column, array_id), values.remove_row(row), values.remove_col(column), values.swap_rows(row1, row2), values.swap_columns(column1, column2), values.sort(column?, order?), values.submatrix(from_row?, to_row?, from_column?, to_column?), and the shape readers, matrix<float>/matrix<int>/matrix<bool>/matrix<string>/matrix<color> varip declarations and matrix-row for...in iteration are fixture-backed; bare matrix or matrix templates beyond float/int/bool/string/color typed declarations, cross-element matrix typed declaration initializers, and combined or broader matrix varip/for...in interactions remain unsupported; fixture-backed fixed simple-matrix return qualifier coverage for matrix.new<float>/matrix.new<int>/matrix.new<bool>/matrix.new<string>/matrix.new<color>, fixture-backed MatrixMult return qualifier coverage for matrix.mult matrix/scalar results as simple matrix<float> and matrix/array results as simple array<float>; the exact non-array-namespace scalar-array producers str.split, ta.pivot_point_levels, matrix.row, matrix.col, matrix.eigenvalues, map.keys, and map.values support direct call-result size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost reads, abs transformations, and min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev statistics plus int/float/string sort_indices transformations and applicable scalar/same-identity scalar-tree UDT join reads, with copy, numeric abs/standardize, and int/float/string sort_indices able to continue allowed array chains; array-returning namespace matrix.mult(...) overloads (matrix-by-array, array-by-matrix, and array-by-array) support the same eight all-kind helpers plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev plus int/float/string sort_indices with copy/abs/standardize/sort_indices continuation and terminal scalar join; namespace matrix.mult(...) matrix-by-matrix, matrix-by-scalar, and scalar-by-matrix direct results plus namespace matrix.copy(...)/matrix.transpose(...)/matrix.submatrix(...) SameAsArg results plus namespace matrix.kron(...)/matrix.diff(...)/matrix.pow(...)/matrix.inv(...)/matrix.pinv(...)/matrix.eigenvectors(...) fixed simple-float-matrix results support rows()/columns()/elements_count()/get(row, column)/copy()/row(index)/col(index), with copy preserving shape, transpose swapping shape, submatrix selecting an independent range, kron expanding both dimensions, diff preserving selected matrix shape and operand direction, pow preserving square shape across identity/copy/positive powers, inv preserving square shape or na for singular inputs, pinv swapping rectangular shape and preserving singular matrix results, eigenvectors preserving square shape or na for non-real or invalid-cell results, copy/transpose/submatrix preserving float/int/bool/string/color element kinds, and copy continuing matrix-helper chains and row switching to fresh element-kind-preserving size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev plus int/float/string sort_indices arrays with copy/abs/standardize/sort_indices continuation; exact matrix.new<float>/matrix.new<int>/matrix.new<bool>/matrix.new<string>/matrix.new<color> template results support rows()/columns()/elements_count()/get(row, column)/copy()/row(index)/col(index) with element-kind preservation, default na cells, zero dimensions, fresh allocation, and copy-only continuation; exact bound matrix-receiver values.copy() results support the same direct reads/copy with preserved element kind and shape, independent storage, and copy-only continuation; exact bound matrix-receiver values.transpose() results support the same direct reads/copy with preserved element kind, swapped shape, independent storage, and copy-only continuation; exact bound matrix-receiver values.submatrix(...) results support the same direct reads/copy with preserved element kind, selected independent ranges, default and empty ranges, and copy-only continuation; exact bound numeric-matrix-receiver values.kron(other) results support the same direct reads/copy with expanded shape, fixed float-matrix results, independent storage, and copy-only continuation; exact bound numeric-matrix-receiver values.diff(other) results support the same direct reads/copy for matrix or scalar operands with selected matrix shape, operand direction, fixed float-matrix results, independent storage, and copy-only continuation; exact bound numeric-square-matrix-receiver values.pow(power) results support the same direct reads/copy across identity, copy, and positive powers with fixed float-matrix results, independent storage, and copy-only continuation; exact bound numeric-square-matrix-receiver values.inv() results support the same direct reads/copy with fixed float-matrix results, preserved invertible square shape, empty 0 x 0 results, na singular/invalid-cell results, independent storage, and copy-only continuation; exact bound numeric-matrix-receiver values.pinv() results support the same direct reads/copy with fixed float-matrix results, swapped rectangular shape, singular matrix results, swapped zero-cell shapes, na invalid-cell results, independent storage, and copy-only continuation; exact bound numeric-square-matrix-receiver values.eigenvectors() results support the same direct reads/copy with fixed float-matrix results, preserved real square shape, empty 0 x 0 results, na invalid-cell/non-real/incomplete results, independent storage, and copy-only continuation; exact bound numeric-matrix-receiver values.mult(other) matrix results support the same direct reads/copy for matrix or scalar operands with multiplied or preserved shape, fixed float-matrix results, na propagation, zero-inner-dimension behavior, independent storage, and copy-only continuation while array-result overloads retain array-helper dispatch; other bound matrix producers, non-matrix receivers, broader helpers, and mutation remain gated; the existing bound-receiver matrix_id.mult(array).size() path is unchanged, unqualified local-UDF results with a concrete supported matrix kind support the same seven direct helpers across parameter passthrough, block aliases, nested calls, same-kind control flow, constructed and matrix-operation results, call-specific float/int/bool/string/color kinds, zero dimensions, independent copy storage, named/reordered arguments, and copy-only continuation; local and imported user-method results with a concrete supported matrix kind support the same seven direct helpers across receiver-style, local-type-qualified or alias-qualified, direct-constructor-receiver, block/nested/same-kind-control-flow, call-specific float/int/bool/string/color, zero-dimension, same-library dual-alias, independent-copy, and copy-only-continuation paths; registered imported pure-function results with a concrete supported matrix kind support the same five helpers across alias-qualified, block-return, nested-function, same-kind-control-flow, constructed-result, call-specific float/int/bool/string/color, zero-dimension, same-library dual-alias, independent-copy, and copy-only-continuation paths; unknown/na, scalar, array, map, unregistered or unresolved user-function matrix results, broader-helper, mutation, and terminal-read continuation cases remain gated; every concrete matrix-result producer additionally exposes row(index) and col(index) as fresh element-kind-preserving arrays with size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev plus int/float/string sort_indices with copy/abs/standardize/sort_indices array continuation and applicable scalar/same-identity scalar-tree UDT join reads; concrete numeric matrix-result producers additionally expose eigenvalues() as a fresh array<float> under the existing numeric type check and square-matrix runtime boundary; every concrete matrix-result producer also exposes terminal is_square() as simple bool; concrete numeric matrix-result producers also expose terminal is_zero(), is_binary(), is_diagonal(), is_identity(), is_symmetric(), is_antisymmetric(), and is_stochastic() as simple bool values under the existing numeric type checks and value-predicate runtime rules, plus terminal sum(), avg(), min(), max(), mode(), trace(), and det() reads as series float values under the existing numeric aggregate runtime rules and terminal rank() reads as a series int under the existing numeric rank runtime rules; every concrete matrix-result producer also exposes transpose() and submatrix(...) as independent element-kind-preserving matrix continuations alongside copy(), with transpose swapping shape and submatrix selecting an optional half-open range; every concrete numeric matrix-result producer additionally exposes inv() as an independent fixed-float matrix continuation with the existing square, singular, invalid-cell, and upstream-na boundaries; the same numeric producer set additionally exposes pinv() as an independent fixed-float continuation that swaps rectangular shape, preserves singular matrix values and swapped zero-cell shapes, and retains invalid-cell/upstream-na propagation; it also exposes eigenvectors() as an independent fixed-float continuation that preserves square shape for complete real eigenvectors, returns empty 0 x 0, retains the non-square runtime error, and yields na for invalid-cell, non-real, incomplete, or upstream-na results; the same numeric producer set exposes pow(power) as an independent fixed-float continuation with the simple-int argument gate, square-matrix runtime boundary, identity/copy/positive-power behavior, empty 0 x 0 results, negative/na-power errors, and upstream-na propagation; the same numeric producer set additionally exposes kron(other) as an independent fixed-float continuation with a numeric-matrix operand gate, product-expanded row/column shape, na-cell and upstream-na propagation, zero-dimension preservation, independent storage, and the existing cell-budget error; the same numeric producer set additionally exposes diff(other) as an independent fixed-float continuation with a numeric-matrix-or-scalar operand gate, receiver-shape preservation, left-to-right subtraction, na-cell, na-scalar, and upstream-na propagation, zero-dimension preservation, independent storage, and the matching-shape runtime error for matrix operands; the same numeric producer set additionally exposes mult(other) with result-type-directed continuation: matrix and scalar operands yield independent fixed-float matrices with multiplied or preserved shape, numeric-array operands yield independent float arrays with one value per receiver row, and the resolved result selects the closed matrix or array helper set while retaining numeric operand gates, na propagation, zero-inner-dimension behavior, multiplication order, matrix cell-budget and dimension errors, and vector-length errors; producer-specific copy/diff/eigenvectors/inv/kron/mult/pinv/pow/submatrix/transpose-only wording applies only to matrix-result continuation, while broader matrix helpers and mutation remain gated
linefill.new         partial      linefill object creation between existing line ids with color snapshots and official same-pair replacement semantics; na or deleted line ids return na; linefill array construction is supported through array.new_linefill and array.from for linefill ids
linefill.set_color   partial      linefill color mutation for existing linefill ids, including namespace-call and method-call dispatch, na id no-op behavior, and no-op behavior after the linefill has been replaced/deleted by a same-pair linefill.new call
linefill.get_line1   partial      returns the first line id referenced by an existing linefill, including namespace-call dispatch; na ids and replaced linefill ids return na
linefill.get_line2   partial      returns the second line id referenced by an existing linefill, including method-call dispatch; na ids and replaced linefill ids return na
linefill.delete      partial      linefill id deletion snapshots, including ordinary and independent while-loop control-flow deletion; deleting replaced, deleted, or na linefills is no-op; ids are not reused
linefill.all         partial      snapshot array of currently existing linefill ids in creation order, including ordinary and while-loop control-flow reads; replaced or deleted linefills are omitted from subsequent reads while linefill array construction is supported through array.new_linefill and array.from for linefill ids
request.security_lower_tf unsupported lower-timeframe array-returning request API is not implemented
request.*            unsupported  request families beyond the narrow request.security subsets
import                                 partial      tests/fixtures/runtime/import.pine;tests/fixtures/runtime/import_state.pine;tests/fixtures/runtime/import_udt_constructor.pine;tests/fixtures/runtime/import_udt_reassignment.pine;tests/fixtures/runtime/import_udt_typed_declaration.pine;tests/fixtures/runtime/import_udt_var.pine;tests/fixtures/runtime/import_udt_varip.pine;tests/fixtures/runtime/import_udt_history.pine;tests/fixtures/runtime/import_udt_private_dependency_history.pine;tests/fixtures/runtime/import_non_scalar_udt_typed_na_history.pine;tests/fixtures/sema/supported_imported_udt_method_param_non_scalar.pine;tests/fixtures/runtime/user_type_non_scalar_typed_na_history.pine;tests/fixtures/runtime/series_history_offset_udt_field.pine;tests/fixtures/runtime/import_udt_array_from.pine;tests/fixtures/runtime/import_udt_array_new.pine;tests/fixtures/runtime/import_udt_array_scalar_tree.pine;tests/fixtures/runtime/import_udt_array_sort_field.pine;tests/fixtures/runtime/import_udt_array_history.pine;tests/fixtures/runtime/import_udt_array_typed_declarations.pine;tests/fixtures/runtime/import_udt_array_varip.pine;tests/fixtures/realtime/import_udt_array_varip.pine;tests/fixtures/runtime/import_udt_field_mutation.pine;tests/fixtures/runtime/import_udt_field_mutation_control_flow.pine;tests/fixtures/runtime/import_udt_ternary.pine;tests/fixtures/runtime/import_udt_if_expression.pine;tests/fixtures/runtime/import_udt_switch_statement_block.pine;tests/fixtures/runtime/import_udt_while_expression.pine;tests/fixtures/runtime/import_udt_for_expression.pine;tests/fixtures/runtime/import_udt_for_in_expression.pine;tests/fixtures/runtime/import_udt_udf_passthrough.pine;tests/fixtures/runtime/import_udt_udf_qualifier_propagation.pine;tests/fixtures/runtime/import_udt_typed_udf_params.pine;tests/fixtures/runtime/import_udt_array_typed_udf_params.pine;tests/fixtures/runtime/import_udt_udf_nested_passthrough.pine;tests/fixtures/runtime/import_udt_udf_constructor_return.pine;tests/fixtures/runtime/import_udt_udf_local_field_mutation.pine;tests/fixtures/runtime/import_udt_method.pine;tests/fixtures/runtime/import_udt_method_qualified.pine;tests/fixtures/runtime/import_udt_method_qualifier_propagation.pine;tests/fixtures/runtime/import_udt_method_return.pine;tests/fixtures/runtime/import_udt_method_param_return.pine;tests/fixtures/runtime/import_udt_method_block_return.pine;tests/fixtures/runtime/import_udt_method_if_return.pine;tests/fixtures/runtime/import_udt_method_for_return.pine;tests/fixtures/runtime/import_udt_method_while_switch_return.pine;tests/fixtures/runtime/import_udt_method_nested_return.pine;tests/fixtures/runtime/import_udt_method_local_field_mutation.pine;tests/fixtures/runtime/import_udt_method_constructor_return.pine;tests/fixtures/runtime/import_udt_udf_nested_constructor_return.pine;tests/fixtures/libraries/import_lib.pine;tests/fixtures/libraries/import_udt_lib.pine;tests/fixtures/libraries/import_private_udt_lib.pine;tests/fixtures/libraries/import_duplicate_udt_lib.pine;tests/fixtures/libraries/import_duplicate_udt_const_lib.pine;tests/fixtures/libraries/import_duplicate_udt_function_lib.pine;tests/fixtures/libraries/import_udt_method_side_effect_lib.pine;tests/fixtures/libraries/import_non_scalar_udt_lib.pine;tests/fixtures/sema/unsupported_import.pine;tests/fixtures/sema/unsupported_imported_udt_constructor.pine;tests/fixtures/sema/unsupported_imported_private_udt_constructor.pine;tests/fixtures/sema/unsupported_import_duplicate_exported_udt.pine;tests/fixtures/sema/unsupported_import_duplicate_exported_udt_const.pine;tests/fixtures/sema/unsupported_import_duplicate_exported_udt_function.pine;tests/fixtures/sema/unsupported_imported_udt_varip.pine;tests/fixtures/sema/unsupported_imported_udt_varip_identity.pine;tests/fixtures/sema/unsupported_imported_udt_field_mutation_type.pine;tests/fixtures/sema/unsupported_imported_udt_parameter_field_mutation.pine;tests/fixtures/sema/unsupported_imported_udt_global_field_mutation.pine;tests/fixtures/sema/unsupported_imported_udt_nested_field_mutation.pine;tests/fixtures/sema/supported_imported_udt_array_decl.pine;tests/fixtures/sema/supported_imported_udt_array_alias_decl.pine;tests/fixtures/sema/supported_imported_udt_array_new.pine;tests/fixtures/sema/unsupported_imported_udt_assignment_identity.pine;tests/fixtures/sema/unsupported_imported_udt_typed_decl_identity.pine;tests/fixtures/sema/unsupported_imported_udt_var_identity.pine;tests/fixtures/sema/unsupported_imported_udt_ternary_identity.pine;tests/fixtures/sema/unsupported_imported_udt_if_expression_identity.pine;tests/fixtures/sema/unsupported_imported_udt_switch_identity.pine;tests/fixtures/sema/unsupported_imported_udt_while_identity.pine;tests/fixtures/sema/unsupported_imported_udt_for_identity.pine;tests/fixtures/sema/unsupported_imported_udt_for_in_identity.pine;tests/fixtures/sema/unsupported_imported_udt_udf_passthrough_identity.pine;tests/fixtures/sema/unsupported_imported_udt_udf_nested_passthrough_identity.pine;tests/fixtures/sema/unsupported_imported_udt_udf_constructor_return_identity.pine;tests/fixtures/sema/unsupported_imported_udt_udf_nested_constructor_return_identity.pine;tests/fixtures/sema/supported_imported_udt_array_typed_udf_params.pine;tests/fixtures/sema/unsupported_imported_udt_array_typed_udf_param_mismatch.pine;tests/fixtures/sema/unsupported_imported_method_qualified_receiver.pine;tests/fixtures/sema/unsupported_imported_method_qualified_receiver_order.pine;tests/fixtures/sema/unsupported_imported_method_field_mutation.pine;tests/fixtures/syntax/imported_method_call_result_receiver.pine;tests/fixtures/runtime/import_user_method_map_call_result_reads.pine;tests/fixtures/sema/supported_imported_user_method_map_call_result_reads.pine;tests/fixtures/sema/unsupported_imported_user_method_map_call_result_reads.pine;tests/fixtures/runtime/import_function_map_call_result_reads.pine;tests/fixtures/sema/supported_imported_function_map_call_result_reads.pine;tests/fixtures/sema/unsupported_imported_function_map_call_result_reads.pine;tests/fixtures/runtime/import_udt_array_typed_method_params.pine;tests/fixtures/sema/supported_imported_udt_array_typed_method_params.pine;tests/fixtures/sema/unsupported_imported_udt_array_typed_method_param_mismatch.pine;tests/fixtures/sema/supported_imported_udt_varip_decl.pine;tests/fixtures/sema/supported_imported_udt_varip_non_scalar_typed_na.pine;tests/fixtures/sema/unsupported_imported_udt_varip_non_scalar_reassign.pine;tests/fixtures/sema/supported_imported_udt_history.pine;tests/fixtures/sema/supported_imported_udt_history_non_scalar_typed_na.pine;tests/fixtures/sema/supported_user_type_history_non_scalar_typed_na.pine;tests/fixtures/sema/supported_user_type_history_non_scalar_constructed.pine;tests/fixtures/sema/supported_imported_udt_history_non_scalar_constructed.pine;tests/fixtures/sema/supported_user_type_field_non_scalar_typed_na.pine;tests/fixtures/sema/unsupported_imported_udt_array_decl_non_scalar.pine;tests/fixtures/sema/unsupported_imported_udt_array_alias_decl_non_scalar.pine;tests/fixtures/sema/unsupported_imported_udt_array_varip_decl_non_scalar.pine;tests/fixtures/sema/unsupported_imported_udt_array_varip_alias_decl_non_scalar.pine;tests/fixtures/sema/unsupported_imported_udt_array_new_non_scalar.pine;tests/fixtures/sema/unsupported_imported_udt_array_from_non_scalar.pine;tests/fixtures/sema/unsupported_imported_udt_array_push_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_push_method_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_push_local_target_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_push_local_target_method_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_set_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_set_method_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_set_local_target_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_set_local_target_method_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_insert_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_insert_method_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_insert_local_target_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_insert_local_target_method_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_unshift_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_unshift_method_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_unshift_local_target_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_unshift_local_target_method_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_fill_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_fill_method_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_fill_local_target_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_fill_local_target_method_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_includes_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_includes_method_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_includes_local_target_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_includes_local_target_method_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_indexof_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_indexof_method_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_indexof_local_target_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_indexof_local_target_method_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_lastindexof_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_lastindexof_method_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_lastindexof_local_target_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_lastindexof_local_target_method_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_concat_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_concat_method_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_concat_local_target_mixed_identity.pine;tests/fixtures/sema/unsupported_imported_udt_array_concat_local_target_method_mixed_identity.pine;tests/fixtures/runtime/user_type_array_scalar_tree.pine;tests/fixtures/sema/supported_user_type_array_control_flow.pine;tests/fixtures/sema/unsupported_user_type_array_control_flow_identity.pine;tests/fixtures/sema/supported_imported_user_type_array_control_flow.pine;tests/fixtures/sema/unsupported_imported_user_type_array_control_flow_identity.pine;tests/fixtures/runtime/import_udt_array_udf_method_returns.pine;tests/fixtures/sema/supported_imported_user_type_array_udf_method_returns.pine;tests/fixtures/sema/unsupported_imported_user_type_array_udf_method_return_identities.pine;tests/fixtures/runtime/import_udt_array_tuple_returns.pine;tests/fixtures/sema/supported_imported_user_type_array_tuple_returns.pine;tests/fixtures/sema/unsupported_imported_user_type_array_tuple_return_identities.pine;tests/fixtures/sema/unsupported_imported_user_type_array_tuple_alias_mutation.pine;tests/fixtures/sema/unsupported_imported_user_type_array_call_result_chaining.pine;tests/fixtures/libraries/import_udt_array_return_lib.pine;tests/fixtures/runtime/builtin_array_call_result_reads.pine;tests/fixtures/sema/supported_builtin_array_call_result_reads.pine;tests/fixtures/sema/unsupported_builtin_array_call_result_reads.pine;tests/fixtures/runtime/import_user_method_matrix_call_result_reads.pine;tests/fixtures/sema/supported_imported_user_method_matrix_call_result_reads.pine;tests/fixtures/sema/unsupported_imported_user_method_matrix_call_result_reads.pine;tests/fixtures/runtime/import_function_matrix_call_result_reads.pine;tests/fixtures/sema/supported_imported_function_matrix_call_result_reads.pine;tests/fixtures/sema/unsupported_imported_function_matrix_call_result_reads.pine  host-provided exact-key imports with aliases, exported const expressions, pure exported functions including scalar/simple-string qualifier passthrough/block-local returns, scalar-tree imported UDT constructors with direct and nested field reads, ordinary same-imported-UDT reassignment, scalar-tree imported UDT typed declarations initialized or reassigned from the same imported identity, ordinary imported UDT var declarations, scalar-tree imported UDT varip declarations including same-imported direct alias and ternary/switch/if/for/for...in/while initialization plus nested same-imported scalar-tree Wrapper control-flow initialization and committed history reads, scalar-tree imported UDT value history, including repeated same-bar copy independence after root-field replacement for direct, if/switch/for/for-in/while flow-result, typed-UDF returned Point/Wrapper, UDF direct/nested passthrough-returned Point/Wrapper, UDF direct/nested constructor-returned Point/Wrapper, and method direct/nested passthrough/constructor-returned Point/Wrapper values and scalar-tree imported UDT varip committed history, with dynamic and na offsets plus typed-na private-dependency value history and local/imported non-scalar typed-na UDT direct, var, varip, ternary, if, switch, for, for-in, while, local/imported exported UDF passthrough, method parameter passthrough, imported method non-receiver parameter passthrough, method receiver/nested receiver passthrough, imported alias-qualified method receiver passthrough identity value history, direct field reads/history with `na()` checks, and local/imported constructed non-scalar UDT label/line/box/chart.point-field value history with direct chart.point field chains, including UDF- and method-returned values plus imported scalar-tree UDT field-produced history offsets, including fields on imported UDF- and method-returned values, scalar-tree imported UDT array<lib.Type>/lib.Type[] declarations with na initialization and same-identity array.from assignment, scalar-tree imported UDT array varip declarations including array.new<lib.Type>() initialization, scalar-tree imported UDT array.new<lib.Type>/array.from construction with array.size, array.get, array.first, and array.last field reads plus array.set/set() replacement field reads, array.push/push() append field reads, array.unshift/unshift() prepend field reads, array.insert/insert() insertion field reads, array.fill/fill() replacement field reads, array.join/join() positional stringification, array.includes/indexof/lastindexof structural equality search, array.sort/sort_indices by int/float/string sort_field, array.pop, array.remove, and array.shift return field reads, and array.clear/clear() size reset, array.copy/copy() independent field reads, array.reverse/reverse() reordered field reads, array.slice/slice() window field reads, array.concat/concat() appended field reads, statement/expression/index-value for-in value-copy field reads, and committed array and slice history snapshots with first-bar and dynamic na-offset predicates, field reads from dynamically selected historical elements, and repeated same-bar copy independence, scalar-tree imported UDT root-field replacement in top-level, branch, for-loop, while-loop, and UDF-local statement contexts, same-imported-identity ternary, if, switch, while, for, and for...in expression results with caller-side history reads, imported UDT array typed method parameters with named same-imported UDT array arguments and caller-side history reads from returned imported UDT array elements, imported UDT array typed UDF parameters with named same-imported UDT array arguments and caller-side history reads from returned imported UDT array elements, imported UDT UDF direct, block-local alias, exported-function typed-parameter, exported-function same-imported UDT array typed-parameter with named same-imported UDT array arguments and caller-side history reads from returned imported UDT array elements, ternary-expression alias, final-if alias, final-for alias, final-for-in alias, final-while alias, switch-expression alias, or nested parameter passthrough over those forms, and direct, nested, ternary, if, for, for-in, while, or switch constructor-return results, plus receiver-style or alias-qualified imported UDT method calls over bound identifiers, direct same-imported receiver expressions, alias-qualified direct constructor receiver expressions, or receiver-style imported constructor/method call-result receiver chains, including the same method name on different scalar-tree receiver types, named/reordered non-receiver arguments, direct constructor nested UDT arguments, scalar/simple-string passthrough/block-local/final-loop qualifier propagation, and direct same-identity, block-local alias, ternary-expression alias, final-if alias, final-for alias, final-for-in alias, final-while alias, switch-expression alias, and nested-method passthrough plus direct, nested scalar-tree, ternary, if, for, for-in, while, or switch constructor returns, caller-side history reads from method-returned values, and method-local scalar-tree root-field replacement; receiver-style imported UDT method calls over imported constructor or imported method call-result receiver chains are parser-normalized to alias-qualified method calls; remote lookup, re-exports, imported UDT flow outside the covered same-identity scalar-tree paths, nested imported field mutation, imported UDT parameter/global field mutation inside UDFs, array.new templates for non-scalar imported UDTs and non-scalar imported UDT array declarations, side-effecting exported functions, and unaliased imports remain unsupported, with private-dependency imported UDT constructor argument failures plus alias-qualified imported method receiver type/order mismatches and imported method receiver/parameter field mutation side effects reported through targeted semantic diagnostics, private imported UDT access remaining private-symbol access, local/imported typed declaration, var declaration, varip declaration, ternary/if/switch/while/for/for-in branch, passthrough, and constructor-return identity mismatches rejected, and duplicate exported UDT names, UDT/const name collisions, or UDT/function name collisions rejected through the shared export table; fixture-backed same-local and same-imported scalar-tree UDT array identity through ternary, if, switch, for, for...in, and while results, including array/na branches, block aliases, typed/inferred declarations, and helper/iteration consumers, with per-call generic UDF lowering isolation; imported UDF and user-method same-imported scalar-tree UDT array returns preserve call-specific identity through direct parameters, block aliases, copy/new/from, private nested calls, final control-flow results, and typed method named/reordered arguments, including source-aware imported type-position rewrites and same-library dual-alias call-site isolation; local and imported UDF/method tuple returns preserve same-local or same-imported scalar-tree UDT-array identity independently for each destructured slot through direct, block, nested, final-flow, typed-na, typed-destination, A-to-B-to-A, same-library dual-alias, tuple-declaration direct/self-alias, control-flow, shadowing, later-destructuring, same-identity control-flow reassignment, and na-reassignment paths; cross-identity direct/control-flow reassignment, unresolved nested tuple consumers, and conflicting identities within one scalar return or tuple slot; qualified imported UDF/user-method call results and root local-UDF wrappers over imported values returning supported array kinds support direct size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost reads, abs transformations, and min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev statistics plus int/float/string sort_indices transformations and applicable scalar/same-identity scalar-tree UDT join reads, including private-library unqualified UDF postfix dispatch after source rewriting; same-imported scalar-tree UDT-array results require concrete per-call identity, with named get indexes, empty/na reads, A-to-B-to-A, and dual-alias isolation; root local-UDF results returning imported scalar UDT values dispatch existing pure user methods; same-local qualified user-defined results are tracked by local UDT/method rows; imported pure-function and user-method results with one concrete supported scalar map template support direct size/get/contains/copy/keys/values plus terminal put/clear/remove/put_all through alias-qualified or receiver-style calls, direct-constructor receivers where applicable, nested/control-flow, same-library dual-alias, and copy-only-continuation paths, with keys and values returning fresh key/value-kind-preserving arrays that admit size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev plus int/float/string sort_indices with copy/abs/standardize/sort_indices array continuation and applicable scalar/same-identity scalar-tree UDT join reads; map mutation other than terminal put/clear/remove/put_all, array mutation, and terminal key/value-reader continuation remain gated; builtin-qualified calls outside the registered static-array producer allowlist, untyped unknown/na or non-array/non-UDT results, mixed/non-scalar imported UDT-array identities, helpers outside size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev plus int/float/string sort_indices and scalar/same-identity scalar-tree UDT join, and UDF/method mutation side effects remain unsupported; registered static-array builtin/template producers (array.new_* and supported array.new<T>, array.from, array.copy, array.slice, array.concat, array.abs, array.standardize, and array.sort_indices) support direct call-result size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost reads, abs transformations, and min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev statistics plus int/float/string sort_indices transformations and applicable scalar/same-identity scalar-tree UDT join reads; array.concat still mutates and returns its first array, array.slice remains a live window, and other array results, other namespaces, map/matrix templates, broader postfix helpers, and postfix mutation remain gated; imported user-method results with a concrete supported matrix kind expose rows/columns/elements_count/get/copy/row/col across receiver-style and alias-qualified calls, direct imported-constructor receivers, block/nested/same-kind control flow, float/int/bool/string/color kinds, zero dimensions, same-library dual aliases, independent copies, and copy-only continuation, while unknown/na, non-matrix, broader-helper, mutation, and terminal-read continuation boundaries remain gated; registered imported pure-function results with a concrete supported matrix kind expose rows/columns/elements_count/get/copy/row/col across alias-qualified calls, block/nested/same-kind control flow, float/int/bool/string/color kinds, zero dimensions, same-library dual aliases, independent copies, and copy-only continuation, while unknown/na, non-matrix, unregistered or unresolved functions, broader-helper, mutation, and terminal-read continuation boundaries remain gated; every concrete matrix-result producer additionally exposes row(index) and col(index) as fresh element-kind-preserving arrays with size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev plus int/float/string sort_indices with copy/abs/standardize/sort_indices array continuation and applicable scalar/same-identity scalar-tree UDT join reads; concrete numeric matrix-result producers additionally expose eigenvalues() as a fresh array<float> under the existing numeric type check and square-matrix runtime boundary; every concrete matrix-result producer also exposes terminal is_square() as simple bool; concrete numeric matrix-result producers also expose terminal is_zero(), is_binary(), is_diagonal(), is_identity(), is_symmetric(), is_antisymmetric(), and is_stochastic() as simple bool values under the existing numeric type checks and value-predicate runtime rules, plus terminal sum(), avg(), min(), max(), mode(), trace(), and det() reads as series float values under the existing numeric aggregate runtime rules and terminal rank() reads as a series int under the existing numeric rank runtime rules; every concrete matrix-result producer also exposes transpose() and submatrix(...) as independent element-kind-preserving matrix continuations alongside copy(), with transpose swapping shape and submatrix selecting an optional half-open range; every concrete numeric matrix-result producer additionally exposes inv() as an independent fixed-float matrix continuation with the existing square, singular, invalid-cell, and upstream-na boundaries; the same numeric producer set additionally exposes pinv() as an independent fixed-float continuation that swaps rectangular shape, preserves singular matrix values and swapped zero-cell shapes, and retains invalid-cell/upstream-na propagation; it also exposes eigenvectors() as an independent fixed-float continuation that preserves square shape for complete real eigenvectors, returns empty 0 x 0, retains the non-square runtime error, and yields na for invalid-cell, non-real, incomplete, or upstream-na results; the same numeric producer set exposes pow(power) as an independent fixed-float continuation with the simple-int argument gate, square-matrix runtime boundary, identity/copy/positive-power behavior, empty 0 x 0 results, negative/na-power errors, and upstream-na propagation; the same numeric producer set additionally exposes kron(other) as an independent fixed-float continuation with a numeric-matrix operand gate, product-expanded row/column shape, na-cell and upstream-na propagation, zero-dimension preservation, independent storage, and the existing cell-budget error; the same numeric producer set additionally exposes diff(other) as an independent fixed-float continuation with a numeric-matrix-or-scalar operand gate, receiver-shape preservation, left-to-right subtraction, na-cell, na-scalar, and upstream-na propagation, zero-dimension preservation, independent storage, and the matching-shape runtime error for matrix operands; the same numeric producer set additionally exposes mult(other) with result-type-directed continuation: matrix and scalar operands yield independent fixed-float matrices with multiplied or preserved shape, numeric-array operands yield independent float arrays with one value per receiver row, and the resolved result selects the closed matrix or array helper set while retaining numeric operand gates, na propagation, zero-inner-dimension behavior, multiplication order, matrix cell-budget and dimension errors, and vector-length errors; producer-specific copy/diff/eigenvectors/inv/kron/mult/pinv/pow/submatrix/transpose-only wording applies only to matrix-result continuation, while broader matrix helpers and mutation remain gated
user-defined types   partial      local scalar-field type declarations, Type.new constructors, field reads, ordinary variables, local for-expression constructor results, top-level/block-local/loop-local same-UDT `for` expression initialization and reassignment, var persistence from na, same-UDT constructors, same-UDT ternary expressions, same-UDT switch expressions, same-UDT `if` expressions, same-UDT `for` expressions, same-UDT `for...in` expressions, or same-UDT `while` expressions, scalar-tree local UDT value history with dynamic and na offsets plus local scalar-tree UDT field-produced history offsets and UDF-returned passthrough/constructor/control-flow values, including nested scalar-tree UDT returns, and same-UDT if, switch, for, for-in, and while expression result history, scalar field mutation in top-level, branch, for-loop, while-loop, UDF-local variables, and method-local variables, top-level/block-local/loop-local same-UDT ternary, switch, or `if` expression initialization, UDF parameter passthrough/returns through positional or named arguments with direct returns, UDT block-local aliases, final if/else, final for, final for-in, final while, or switch-expression local UDT aliases, or nested passthrough calls, and UDF constructor returns, directly, through nested pure constructor-helper UDF calls, or through same-local-UDT ternary, switch, `if` expression, final if/else constructor branches, or final for bodies, final for-in bodies, or final while bodies, from local UDT parameter scalar fields, scalar fields read through block-local UDT aliases of those parameters, block-local scalar aliases of those fields, inferred scalar parameters, or block-local scalar aliases of those scalar parameters using positional or named constructor field arguments only, including UDF-local typed locals initialized or reassigned through same-local-UDT ternary, switch, `if`, `for`, `for...in`, or `while` expressions, explicitly typed same-local scalar-tree UDT varip values initialized from na, same-UDT constructors, same-identity aliases, same-UDT ternary expressions, same-UDT switch expressions, same-UDT if expressions, same-UDT for expressions, same-UDT for...in expressions, or same-UDT while expressions, including nested scalar-tree Wrapper values initialized from those expression forms, plus direct-constructor-inferred or direct-alias-inferred same-local scalar-tree UDT varip values with realtime intrabar persistence, and scalar-tree imported UDT constructor/direct-or-nested field-read/scalar-tree value history plus imported scalar-tree UDT field-produced history offsets from direct values and imported UDF- or method-returned values plus scalar-tree imported ordinary reassignment/typed declaration/ordinary var/scalar-tree varip including same-imported direct alias and ternary/switch/if/for/for...in/while initialization plus scalar-tree array.from size/get/first/last, set replacement field reads, push append field reads, unshift prepend field reads, insert insertion field reads, fill replacement field reads, join positional stringification, includes/indexof/lastindexof structural equality search, sort/sort_indices by int/float/string sort_field, pop/remove/shift return field reads, clear size reset, copy independent field reads, reverse reordered field reads, slice window field reads, concat appended field reads, and statement/expression/index-value for-in value-copy field reads, scalar-tree root-field replacement in top-level, branch, for-loop, while-loop, and UDF-local statement contexts/same-imported-identity ternary, `if`, `switch`, `while`, `for`, direct, block-local alias, ternary-expression alias, final-if alias, final-for alias, final-for-in, final-while, switch-expression alias, or nested UDF passthrough, and direct, nested, ternary, if, for, for-in, while, or switch UDF constructor-return identity subset; imported UDF/method same-scalar-tree UDT array returns preserve call-site identity across direct/alias, copy/new/from, private nested, final-flow, type-position rewrite, and dual-alias paths, with per-slot tuple returns supported; qualified user-defined UDF/method and unqualified plain local UDF results returning supported array kinds, plus the exact allowlisted built-in array producers, support direct size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost chaining, with concrete same-local/same-imported scalar-tree identity required for UDT arrays; only copy may continue a built-in producer chain and terminal producer element readers cannot invoke UDT methods, while mixed scalar-return identities, conflicting tuple-slot identities, non-scalar UDT-array identities, non-array/non-UDT results or unknown/na results without a concrete supported type or identity, built-in-qualified/template call-result receivers outside that exact allowlist, other array helpers, postfix mutation, and concat producer use inside UDFs remain rejected
user-defined methods                   partial      tests/fixtures/runtime/user_methods.pine;tests/fixtures/runtime/local_constructor_method_receiver.pine;tests/fixtures/sema/supported_local_constructor_method_receiver.pine;tests/fixtures/runtime/user_type_array_method_values.pine;tests/fixtures/runtime/import_udt_method.pine;tests/fixtures/runtime/import_udt_method_qualified.pine;tests/fixtures/runtime/import_udt_method_qualifier_propagation.pine;tests/fixtures/runtime/import_udt_method_return.pine;tests/fixtures/runtime/import_udt_method_param_return.pine;tests/fixtures/runtime/import_udt_method_block_return.pine;tests/fixtures/runtime/import_udt_method_if_return.pine;tests/fixtures/runtime/import_udt_method_for_return.pine;tests/fixtures/runtime/import_udt_method_while_switch_return.pine;tests/fixtures/runtime/import_udt_method_nested_return.pine;tests/fixtures/runtime/import_udt_method_local_field_mutation.pine;tests/fixtures/runtime/import_udt_method_constructor_return.pine;tests/fixtures/sema/unsupported_user_method.pine;tests/fixtures/sema/unsupported_user_method_decl_location.pine;tests/fixtures/sema/unsupported_user_method_duplicate.pine;tests/fixtures/sema/unsupported_user_method_duplicate_param.pine;tests/fixtures/sema/unsupported_user_method_receiver_duplicate_param.pine;tests/fixtures/sema/unsupported_user_method_missing_receiver.pine;tests/fixtures/sema/unsupported_user_method_side_effect.pine;tests/fixtures/sema/unsupported_user_method_side_effect_arg.pine;tests/fixtures/sema/unsupported_user_method_field_mutation.pine;tests/fixtures/sema/unsupported_user_method_arg_type.pine;tests/fixtures/sema/unsupported_user_method_missing_arg.pine;tests/fixtures/sema/unsupported_user_method_too_many_args.pine;tests/fixtures/sema/unsupported_user_method_unknown_named_arg.pine;tests/fixtures/sema/unsupported_user_method_duplicate_named_arg.pine;tests/fixtures/sema/unsupported_user_method_pos_after_named_arg.pine;tests/fixtures/sema/unsupported_user_method_param_type.pine;tests/fixtures/sema/unsupported_user_method_recursive.pine;tests/fixtures/sema/unsupported_user_method_call_depth.pine;tests/fixtures/sema/unsupported_user_method_unknown.pine;tests/fixtures/sema/unsupported_non_array_method.pine;tests/fixtures/libraries/import_udt_lib.pine;tests/fixtures/libraries/import_udt_method_side_effect_lib.pine;tests/fixtures/sema/unsupported_imported_method_qualified_receiver.pine;tests/fixtures/sema/unsupported_imported_method_qualified_receiver_order.pine;tests/fixtures/sema/unsupported_imported_method_field_mutation.pine;tests/fixtures/syntax/imported_method_call_result_receiver.pine;tests/fixtures/runtime/import_udt_method_expression_receiver.pine;tests/fixtures/sema/supported_method_final_if_const_reassignment_qualifier.pine;tests/fixtures/sema/unsupported_method_final_if_const_reassignment_qualifier.pine;tests/fixtures/sema/supported_method_final_switch_const_reassignment_qualifier.pine;tests/fixtures/sema/unsupported_method_final_switch_const_reassignment_qualifier.pine;tests/fixtures/sema/supported_method_final_selector_switch_numeric_color_const_reassignment_qualifier.pine;tests/fixtures/sema/unsupported_method_final_selector_switch_numeric_color_const_reassignment_qualifier.pine;tests/fixtures/sema/unsupported_method_final_if_reassignment_series_condition_qualifier.pine;tests/fixtures/sema/unsupported_method_final_switch_reassignment_series_condition_qualifier.pine;tests/fixtures/sema/unsupported_method_final_selector_switch_reassignment_series_selector_qualifier.pine;tests/fixtures/sema/unsupported_method_final_if_branch_for_series_bound_qualifier.pine;tests/fixtures/sema/unsupported_method_switch_block_for_series_bound_qualifier.pine;tests/fixtures/sema/unsupported_method_final_for_series_bound_qualifier.pine;tests/fixtures/sema/unsupported_method_final_for_reassignment_series_bound_qualifier.pine;tests/fixtures/sema/unsupported_method_for_in_series_iterable_qualifier.pine;tests/fixtures/sema/unsupported_method_final_for_in_reassignment_series_iterable_qualifier.pine;tests/fixtures/sema/unsupported_method_while_series_condition_qualifier.pine;tests/fixtures/sema/unsupported_method_final_while_reassignment_series_condition_qualifier.pine;tests/fixtures/runtime/user_type_array_typed_method_params.pine;tests/fixtures/sema/supported_user_type_array_typed_method_params.pine;tests/fixtures/sema/unsupported_user_type_array_typed_method_param_mismatch.pine;tests/fixtures/runtime/import_udt_array_typed_method_params.pine;tests/fixtures/sema/supported_imported_udt_array_typed_method_params.pine;tests/fixtures/sema/unsupported_imported_udt_array_typed_method_param_mismatch.pine;tests/fixtures/runtime/typed_method_params.pine;tests/fixtures/runtime/method_qualifier_propagation.pine;tests/fixtures/sema/supported_typed_method_params.pine;tests/fixtures/sema/unsupported_chart_point_typed_method_param_mismatch.pine;tests/fixtures/sema/unsupported_array_typed_method_param_mismatch.pine;tests/fixtures/sema/unsupported_object_array_typed_method_param_mismatch.pine;tests/fixtures/runtime/chart_point_method_values.pine;tests/fixtures/sema/supported_chart_point_method_values.pine;tests/fixtures/sema/supported_method_qualifier_propagation.pine;tests/fixtures/runtime/map_udf_read.pine;tests/fixtures/sema/supported_map_udf_method_returns.pine;tests/fixtures/sema/unsupported_map_udf_method_return_templates.pine;tests/fixtures/runtime/local_user_method_map_call_result_reads.pine;tests/fixtures/sema/supported_local_user_method_map_call_result_reads.pine;tests/fixtures/sema/unsupported_local_user_method_map_call_result_reads.pine;tests/fixtures/runtime/import_user_method_map_call_result_reads.pine;tests/fixtures/sema/supported_imported_user_method_map_call_result_reads.pine;tests/fixtures/sema/unsupported_imported_user_method_map_call_result_reads.pine;tests/fixtures/runtime/import_function_map_call_result_reads.pine;tests/fixtures/sema/supported_imported_function_map_call_result_reads.pine;tests/fixtures/sema/unsupported_imported_function_map_call_result_reads.pine;tests/fixtures/runtime/user_type_array_scalar_tree.pine;tests/fixtures/sema/supported_user_type_array_udf_method_returns.pine;tests/fixtures/sema/unsupported_user_type_array_udf_method_return_identities.pine;tests/fixtures/runtime/user_type_array_tuple_returns.pine;tests/fixtures/sema/supported_user_type_array_tuple_returns.pine;tests/fixtures/sema/unsupported_user_type_array_tuple_return_identities.pine;tests/fixtures/sema/unsupported_user_type_array_tuple_alias_mutation.pine;tests/fixtures/sema/unsupported_local_user_type_array_call_result_chaining.pine;tests/fixtures/runtime/import_udt_array_udf_method_returns.pine;tests/fixtures/sema/supported_imported_user_type_array_udf_method_returns.pine;tests/fixtures/sema/unsupported_imported_user_type_array_udf_method_return_identities.pine;tests/fixtures/runtime/import_udt_array_tuple_returns.pine;tests/fixtures/sema/supported_imported_user_type_array_tuple_returns.pine;tests/fixtures/sema/unsupported_imported_user_type_array_tuple_return_identities.pine;tests/fixtures/sema/unsupported_imported_user_type_array_tuple_alias_mutation.pine;tests/fixtures/sema/unsupported_imported_user_type_array_call_result_chaining.pine;tests/fixtures/libraries/import_udt_array_return_lib.pine;tests/fixtures/sema/supported_user_type_array_param_for_in.pine;tests/fixtures/runtime/builtin_array_call_result_reads.pine;tests/fixtures/sema/supported_builtin_array_call_result_reads.pine;tests/fixtures/sema/unsupported_builtin_array_call_result_reads.pine;tests/fixtures/runtime/user_method_matrix_call_result_reads.pine;tests/fixtures/sema/supported_user_method_matrix_call_result_reads.pine;tests/fixtures/sema/unsupported_user_method_matrix_call_result_reads.pine;tests/fixtures/runtime/import_user_method_matrix_call_result_reads.pine;tests/fixtures/sema/supported_imported_user_method_matrix_call_result_reads.pine;tests/fixtures/sema/unsupported_imported_user_method_matrix_call_result_reads.pine  pure methods on local UDT receivers with scalar, `chart.point`, scalar array, object-id array, chart.point array, local UDT, same-local scalar-tree UDT array, or same-imported scalar-tree UDT array typed parameters, including receivers read from same-local scalar-tree UDT arrays and bound to local variables, plus local UDT constructor call-result receiver chains with scalar returns, chained UDT returns, named arguments, and caller-side history reads, direct chart.point constructor/passthrough returns with caller-side history reads, direct UDT passthrough returns with caller-side history reads, local and imported method-returned direct/nested passthrough/constructor-returned Point/Wrapper history sibling copy independence, nested scalar-tree UDT method returns with caller-side history reads, block-local or ternary-expression receiver or local UDT parameter alias passthrough returns, final if/else, final for, final for-in, final while, or switch-expression local UDT alias passthrough returns, nested-method UDT parameter passthrough returns, and local and nested scalar-tree UDT constructor returns with caller-side history reads, directly, through nested pure constructor-helper UDF calls, typed method locals initialized with na or same-UDT constructors and later same-UDT reassignment, or initialized or reassigned through same-local-UDT ternary, switch, if, for, for...in, or while expressions, with input/simple qualifier propagation through scalar and simple-string method returns including imported method passthrough/block-local/final-loop returns plus const bool-argument final-if branch reassignments and const bool/int/float/string/color-argument final-switch branch reassignments committing only the selected branch's qualifier effects and final-if/final-switch branch reassignment promotion under series conditions or selectors, and final-loop body reassignment promotion under series bounds, iterables, or conditions fixture-backed for scalar method returns, from receiver or local UDT parameter scalar fields, scalar fields read through block-local receiver or local UDT parameter aliases, block-local scalar aliases of those fields, inferred scalar parameters, or block-local scalar aliases of those parameters using positional or named constructor field arguments, plus receiver-style or alias-qualified scalar-tree imported UDT methods, including the same method name on different scalar-tree receiver types and named/reordered non-receiver arguments and direct constructor nested UDT arguments, over bound identifiers, direct same-imported receiver expressions, alias-qualified direct constructor receiver expressions, or receiver-style imported constructor/method call-result receiver chains, including direct same-identity, block-local alias, ternary-expression alias, final-if alias, final-for alias, final-for-in alias, final-while alias, switch-expression alias, and nested-method passthrough plus direct, nested scalar-tree, ternary, if, for, for-in, while, or switch constructor returns, caller-side history reads from method-returned values, and method-local scalar-tree root-field replacement, plus local methods returning known scalar maps from visible globals, map.new, map.copy, nested UDF calls, and final control-flow results for namespace-helper, history, for-in, or bound map-helper consumption; local and imported pure-function and user-method results with one concrete supported scalar map template directly expose size/get/contains/copy/keys/values plus terminal put/clear/remove/put_all through unqualified or alias-qualified function calls and receiver-style, local-type-qualified or alias-qualified method calls, with direct-constructor receivers where applicable, block/nested returns, same-template control flow, constructed results, scalar-template interleaving, same-library dual-alias, independent-copy, and copy-only-continuation coverage, with keys and values returning fresh key/value-kind-preserving arrays that admit size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev plus int/float/string sort_indices with copy/abs/standardize/sort_indices array continuation and applicable scalar/same-identity scalar-tree UDT join reads; unresolved or mixed templates, broader helpers, map mutation other than terminal put/clear/remove/put_all, array mutation, and terminal key/value-reader continuation remain gated; receiver is passed as the first internal parameter; duplicate method definitions, non-top-level declarations, invalid method parameter lists, invalid method call arguments, receiver/parameter/global field side effects including imported method receiver/parameter field mutation, unknown receivers, recursive methods, deep acyclic method call chains, mismatched UDT parameter identity, series-promoted final-if branch loop, switch-block loop, or final loop returns used as simple-int arguments, and unsupported parameter types remain rejected; local UDF and user-method same-local scalar-tree UDT array returns preserve call-specific identity through direct parameters, block aliases, copy/new/from, nested local calls, named/reordered arguments, and final control flow, including A-to-B-to-A field-order interleaving; imported UDF and user-method same-imported scalar-tree UDT array returns preserve call-specific identity through direct parameters, block aliases, copy/new/from, private nested calls, final control-flow results, and typed method named/reordered arguments, including source-aware imported type-position rewrites and same-library dual-alias call-site isolation; local and imported UDF/method tuple returns preserve same-local or same-imported scalar-tree UDT-array identity independently for each destructured slot through direct, block, nested, final-flow, typed-na, typed-destination, A-to-B-to-A, same-library dual-alias, tuple-declaration direct/self-alias, control-flow, shadowing, later-destructuring, same-identity control-flow reassignment, and na-reassignment paths; cross-identity direct/control-flow reassignment, unresolved nested tuple consumers, and conflicting identities within one scalar return or tuple slot; qualified user-defined call results and unqualified local-UDF call results returning supported array kinds support direct size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost reads, abs transformations, and min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev statistics plus int/float/string sort_indices transformations and applicable scalar/same-identity scalar-tree UDT join reads; same-local or same-imported scalar-tree UDT-array results require concrete per-call identity, including named get indexes, empty/na reads, A-to-B-to-A, and dual-alias isolation; unqualified local-UDF call results returning scalar UDT values dispatch existing pure user methods; builtin-qualified calls outside the registered static-array producer allowlist, untyped unknown/na or non-array/non-UDT results, mixed/non-scalar UDT-array identities, helpers outside size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev plus int/float/string sort_indices and scalar/same-identity scalar-tree UDT join, and UDF/method mutation side effects remain unsupported; local UDF and typed user-method UDT-array parameters preserve call-local element identity for value-only and index/value statement for-in plus final for-in expressions returning a field/scalar result, the UDT element itself, or a same-identity UDT array rebuilt from that element, including block-local array aliases, named method arguments, and A-to-B-to-A calls; registered static-array builtin/template producers (array.new_* and supported array.new<T>, array.from, array.copy, array.slice, array.concat, array.abs, array.standardize, and array.sort_indices) support direct call-result size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost reads, abs transformations, and min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev statistics plus int/float/string sort_indices transformations and applicable scalar/same-identity scalar-tree UDT join reads; array.concat still mutates and returns its first array, array.slice remains a live window, and other array results, other namespaces, map/matrix templates, broader postfix helpers, and postfix mutation remain gated; concrete local and imported user-method matrix results expose rows/columns/elements_count/get/copy/row/col through receiver-style, local-type-qualified or alias-qualified, and direct-constructor-receiver calls across block/nested/same-kind control flow, float/int/bool/string/color kinds, zero dimensions, same-library dual aliases, independent copies, and copy-only continuation, while unknown/na, non-matrix, broader-helper, mutation, and terminal-read continuation boundaries remain gated; every concrete matrix-result producer additionally exposes row(index) and col(index) as fresh element-kind-preserving arrays with size/get/first/last/copy/includes/indexof/lastindexof plus bool/int/float-only every/some and numeric-only binary_search/binary_search_leftmost/binary_search_rightmost/abs/min/max/sum/avg/range/median/mode/percentile_nearest_rank/percentile_linear_interpolation/percentrank/covariance/standardize/variance/stdev plus int/float/string sort_indices with copy/abs/standardize/sort_indices array continuation and applicable scalar/same-identity scalar-tree UDT join reads; concrete numeric matrix-result producers additionally expose eigenvalues() as a fresh array<float> under the existing numeric type check and square-matrix runtime boundary; every concrete matrix-result producer also exposes terminal is_square() as simple bool; concrete numeric matrix-result producers also expose terminal is_zero(), is_binary(), is_diagonal(), is_identity(), is_symmetric(), is_antisymmetric(), and is_stochastic() as simple bool values under the existing numeric type checks and value-predicate runtime rules, plus terminal sum(), avg(), min(), max(), mode(), trace(), and det() reads as series float values under the existing numeric aggregate runtime rules and terminal rank() reads as a series int under the existing numeric rank runtime rules; every concrete matrix-result producer also exposes transpose() and submatrix(...) as independent element-kind-preserving matrix continuations alongside copy(), with transpose swapping shape and submatrix selecting an optional half-open range; every concrete numeric matrix-result producer additionally exposes inv() as an independent fixed-float matrix continuation with the existing square, singular, invalid-cell, and upstream-na boundaries; the same numeric producer set additionally exposes pinv() as an independent fixed-float continuation that swaps rectangular shape, preserves singular matrix values and swapped zero-cell shapes, and retains invalid-cell/upstream-na propagation; it also exposes eigenvectors() as an independent fixed-float continuation that preserves square shape for complete real eigenvectors, returns empty 0 x 0, retains the non-square runtime error, and yields na for invalid-cell, non-real, incomplete, or upstream-na results; the same numeric producer set exposes pow(power) as an independent fixed-float continuation with the simple-int argument gate, square-matrix runtime boundary, identity/copy/positive-power behavior, empty 0 x 0 results, negative/na-power errors, and upstream-na propagation; the same numeric producer set additionally exposes kron(other) as an independent fixed-float continuation with a numeric-matrix operand gate, product-expanded row/column shape, na-cell and upstream-na propagation, zero-dimension preservation, independent storage, and the existing cell-budget error; the same numeric producer set additionally exposes diff(other) as an independent fixed-float continuation with a numeric-matrix-or-scalar operand gate, receiver-shape preservation, left-to-right subtraction, na-cell, na-scalar, and upstream-na propagation, zero-dimension preservation, independent storage, and the matching-shape runtime error for matrix operands; the same numeric producer set additionally exposes mult(other) with result-type-directed continuation: matrix and scalar operands yield independent fixed-float matrices with multiplied or preserved shape, numeric-array operands yield independent float arrays with one value per receiver row, and the resolved result selects the closed matrix or array helper set while retaining numeric operand gates, na propagation, zero-inner-dimension behavior, multiplication order, matrix cell-budget and dimension errors, and vector-length errors; producer-specific copy/diff/eigenvectors/inv/kron/mult/pinv/pow/submatrix/transpose-only wording applies only to matrix-result continuation, while broader matrix helpers and mutation remain gated
```

The matrix should be generated from conformance metadata once the test harness
exists.

Request support must cite request-specific fixtures. The conformance validator
rejects supported or partial `request.*` rows that only point at unrelated
runtime fixtures, so public request claims stay tied to request host-data,
semantic, or runtime coverage. The closed Phase F request boundary and
maintenance tails are summarized in `docs/PHASE_F_AUDIT.md`.

Current CLI output:

```text
pine-compat matrix
pine-compat matrix --format json
```

The generated matrix is derived from `tests/fixtures/conformance.tsv`. Each row
declares a feature, status, notes, and one or more fixture paths that back the
claim. CLI tests verify that every matrix entry references at least one existing
fixture. The text matrix includes the fixture paths, and the JSON matrix exposes
top-level matrix `schemaVersion` plus a `features` array whose entries expose
fixture paths as `fixtures`.

Conformance metadata is validated before matrix output is trusted:

- `feature` must be non-empty and unique.
- `status` must be `supported`, `partial`, or `unsupported`.
- `notes` must be non-empty.
- `fixtures` must contain at least one path and no empty `;` entries.
- Every fixture path must exist in the workspace.
- `supported` and `partial` entries must cite executable, realtime, syntax,
  positive semantic, or regression coverage.
- `unsupported` entries must cite unsupported semantic diagnostic fixtures or
  syntax diagnostic fixtures for parser-level boundaries.
- Every supported built-in registry entry and known unsupported platform family
  must remain represented.

Malformed rows, duplicate feature names, invalid statuses, missing fixture paths,
and status/fixture mismatches are first-class tests. The matrix command is
derived from the same validated metadata used by those tests.

Matrix maintenance rules:

- Edit `tests/fixtures/conformance.tsv` first; do not hand-edit generated
  matrix output.
- Add or update fixture paths in the same change as any new supported,
  partial, or unsupported claim.
- Keep unsupported platform families represented even when they remain outside
  the executable subset.
- If the JSON matrix shape changes, refresh `tests/snapshots/matrix.json` and
  document the public contract change in release notes.
- Use `pine-compat matrix --format json` to inspect the release matrix exposed
  to consumers.

The current typed-array subset is summarized in `docs/ARRAY_STAGE_AUDIT.md`.
Keep `array.*` marked `partial` until the deferred generic, imported/non-scalar
UDT, map, broader matrix, history, and slice-aliasing semantics are designed
and fixture-backed.

The current `varip` subset is summarized in `docs/PHASE_I_AUDIT.md`. Keep
`varip` marked `partial` until drawing object ids, drawing-id arrays, tuples,
non-scalar maps, matrices, non-constructor-inferred or nested-field UDT values,
UDT arrays, imports, object arrays beyond `chart.point`, generic arrays, and
other value families have designed rollback semantics and fixture coverage.
