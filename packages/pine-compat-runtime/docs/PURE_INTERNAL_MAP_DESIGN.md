# Pure Internal Map Design Gate

Status: scalar map helper, typed-declaration, history, and `varip` slices
closed. The interpreter now accepts fixture-backed `map.new<K, V>()` for scalar
key/value templates, `map.size(id)`, namespace-call `map.put`, `map.get`,
`map.contains`, `map.clear`, `map.remove`, `map.copy`, `map.keys`,
`map.values`, and `map.put_all` for runtime-owned map ids, plus scalar
`map<K,V>` typed declarations and bare scalar `map` declarations initialized
from known scalar map expressions. Scalar map history snapshots and ordinary
realtime rollback for map-store mutations are fixture-backed. Scalar map
`varip` handoff keeps map ids and backing stores across repeated realtime
forming updates. Direct scalar-map `for...in` iteration supports key-only and
key/value loop variables in insertion order for statement and expression forms.
Exact supported scalar `map.new<K,V>` call results can be consumed directly by
`.size()`, `.get(key)`, `.contains(key)`, and `.copy()` through the internal
`$builtin_map_result` path; only `.copy()` may continue another admitted map
helper. Direct mutation and `keys()`/`values()` on constructor results stay
gated. Exact namespace `map.copy(existing)` results use the same path, retain
the source scalar template and entries in independent backing storage, and
admit the same read/copy subset. Non-map inputs, mutation, and direct
`keys()`/`values()` stay gated.
Unqualified local-UDF results with one concrete supported scalar map template
share the same four helpers through `$call_result`, preserve call-specific
template/content metadata across parameter passthrough, block aliases, nested
calls, same-template control flow, constructed/copied returns, and named/
reordered arguments, and allow only copy continuation. Local user-method
results retaining one concrete supported scalar map template use the same
helpers across receiver-style, local-type-qualified, direct-constructor-
receiver, block-return, nested-method, same-template control-flow,
constructed-result, scalar-template-interleaving, and independent-copy paths.
Imported user-method results with the same template add receiver-style,
alias-qualified, direct-constructor-receiver, same-library dual-alias, and the
same block/nested/control-flow/copy paths. Registered imported pure-function
results add alias-qualified, block-return, nested-function, same-template
control-flow, constructed-result, scalar-template-interleaving, same-library
dual-alias, and independent-copy paths. Unknown/`na`, scalar, array, matrix,
wrong-template/key, broader-helper, mutation, and terminal-read continuation
cases remain gated.
Equivalent method aliases for the supported namespace subset lower to the same
runtime calls. Scalar `map name = map.new<K, V>()` declarations infer their
template from the initializer; bare `map` declarations without a known scalar
map initializer and non-scalar templates remain unsupported.

This document defines the first internal path for future `map.*` support. It is
scoped to interpreter internals only: parser, semantic analysis, runtime storage,
history, rollback, and conformance. It does not cover remote data, host UI,
rendering, or public JSON/Python/WASM map serialization.

## Current Boundary

`map.*` is partial today.

Current evidence:

- `tests/fixtures/conformance.tsv` records `map.*` as `partial`.
- `tests/fixtures/runtime/map_new_size.pine` and
  `tests/fixtures/sema/supported_map_new_size.pine` cover
  `map.new<int|float|bool|string|color, int|float|bool|string|color>()` empty
  map ids and `map.size(id)` returning `0`.
- `tests/fixtures/runtime/builtin_map_call_result_reads.pine` plus the matching
  supported/unsupported semantic fixtures cover all 25 scalar constructor
  template pairs, direct size/get/contains/copy, nested copies, copy mutation,
  fresh allocation, UDF-contained reads, wrong key/arity diagnostics, and the
  retained mutation, keys/values, and unsupported-template boundaries.
- `tests/fixtures/runtime/builtin_map_copy_call_result_reads.pine` plus the
  matching supported/unsupported semantic fixtures cover namespace
  `map.copy(existing)` result size/get/contains/copy reads, retained populated
  entries and scalar template kinds, independent backing storage, UDF-contained
  reads, wrong receiver/key/arity diagnostics, and the retained mutation and
  keys/values boundaries.
- `tests/fixtures/runtime/local_udf_map_call_result_reads.pine` plus the
  matching supported/unsupported semantic fixtures cover unqualified local-UDF
  map results through size/get/contains/copy for parameter passthrough, block
  aliases, nested calls, same-template control flow, constructed/copied
  returns, named/reordered arguments, per-call scalar template interleaving,
  empty maps, independent copies, and copy-only continuation. Unknown/`na`,
  scalar, array, matrix, wrong templates/keys, broader helpers, mutation, and
  terminal-read continuation remain gated; imported-function and local/
  imported user-method paths are covered separately below.
- `tests/fixtures/runtime/local_user_method_map_call_result_reads.pine` plus
  the matching supported/unsupported local-method semantic fixtures cover
  direct size/get/contains/copy through receiver-style, local-type-qualified,
  direct-constructor-receiver, block-return, nested-method, same-template
  control-flow, constructed-result, scalar-template-interleaving,
  independent-copy, and copy-only-continuation paths. The imported-method
  negative fixture confirms that source provenance remains module-local.
- `tests/fixtures/runtime/import_user_method_map_call_result_reads.pine` plus
  the matching supported/unsupported imported-method semantic fixtures cover
  receiver-style, alias-qualified, direct-constructor-receiver, block-return,
  nested-method, same-template control-flow, scalar-template-interleaving,
  same-library dual-alias, independent-copy, and copy-only-continuation paths.
  The negative fixture retains helper, key, mutation, scalar-return, and
  terminal-reader boundaries.
- `tests/fixtures/runtime/import_function_map_call_result_reads.pine` plus the
  matching supported/unsupported imported-function semantic fixtures cover
  alias-qualified, block-return, nested-function, same-template control-flow,
  constructed-result, scalar-template-interleaving, same-library dual-alias,
  independent-copy, and copy-only-continuation paths. The negative fixture
  retains helper, key, mutation, scalar-return, and terminal-reader boundaries.
- `tests/fixtures/runtime/map_put_get_contains.pine` and
  `tests/fixtures/sema/supported_map_put_get_contains.pine` cover scalar
  `map.put`, `map.get`, and `map.contains` namespace calls, including
  replacement, missing-key `na`, and key-presence reads.
- `tests/fixtures/runtime/map_clear.pine` and
  `tests/fixtures/sema/supported_map_clear.pine` cover scalar `map.clear`
  namespace calls, including clearing all entries and reusing the same map id.
- `tests/fixtures/runtime/map_remove.pine` and
  `tests/fixtures/sema/supported_map_remove.pine` cover scalar `map.remove`
  namespace calls, including deleting a present key and no-op removal of a
  missing key.
- `tests/fixtures/runtime/map_copy.pine` and
  `tests/fixtures/sema/supported_map_copy.pine` cover scalar `map.copy`
  namespace calls, including assignment-as-id-alias behavior and independent
  cloned backing-store behavior.
- `tests/fixtures/runtime/map_keys_values.pine` and
  `tests/fixtures/sema/supported_map_keys_values.pine` cover insertion-order
  `map.keys` / `map.values` array snapshots.
- `tests/fixtures/runtime/map_put_all.pine` and
  `tests/fixtures/sema/supported_map_put_all.pine` cover same-template
  insertion-order `map.put_all` merge behavior.
- `tests/fixtures/runtime/map_history.pine` and
  `tests/fixtures/sema/supported_map_history.pine` cover scalar map history
  snapshots as independent historical copies.
- `tests/fixtures/runtime/map_varip.pine`,
  `tests/fixtures/realtime/map_varip.pine`, and
  `tests/fixtures/sema/supported_map_varip.pine` cover scalar map `varip`
  persistence and intrabar backing-store handoff.
- `tests/fixtures/runtime/map_udf_read.pine` and
  `tests/fixtures/sema/supported_map_udf_read.pine` cover read-only map helper
  calls through user-defined function parameters.
- `tests/fixtures/runtime/map_methods.pine` and
  `tests/fixtures/sema/supported_map_methods.pine` cover equivalent
  `size/get/contains/put/clear/remove/copy/keys/values/put_all` method aliases.
- `tests/fixtures/realtime/map_rollback.pine` covers ordinary realtime rollback
  of map-store mutations, including unconfirmed `map.put` and `map.remove`
  effects not leaking across forming updates.
- `tests/fixtures/sema/unsupported_map_new_template.pine` calls
  `map.new<line, float>()`, and
  `tests/fixtures/sema/unsupported_map_new_dotted_template.pine` calls
  `map.new<chart.point, chart.point>()`.
  `tests/fixtures/sema/unsupported_map.pine`,
  `tests/fixtures/sema/unsupported_map_get.pine`,
  `tests/fixtures/sema/unsupported_map_contains.pine`, and
  `tests/fixtures/sema/unsupported_map_size.pine` cover non-map receivers.
  `tests/fixtures/sema/unsupported_map_put_key_type.pine`,
  `tests/fixtures/sema/unsupported_map_get_key_type.pine`,
  `tests/fixtures/sema/unsupported_map_remove_key_type.pine`, and
  `tests/fixtures/sema/unsupported_map_put_value_type.pine` cover scalar
  template mismatch diagnostics, while
  `tests/fixtures/sema/unsupported_map_put_udf.pine` and
  `tests/fixtures/sema/unsupported_map_put_method_udf.pine` and
  `tests/fixtures/sema/unsupported_map_clear_udf.pine` and
  `tests/fixtures/sema/unsupported_map_remove_udf.pine` cover mutation
  rejection inside user-defined functions.
  `tests/fixtures/sema/unsupported_map_remove.pine` covers non-map
  `map.remove(...)` receivers.
  `tests/fixtures/sema/unsupported_map_clear.pine` covers non-map
  `map.clear(...)` receivers, and
  `tests/fixtures/sema/unsupported_map_copy.pine`,
  `tests/fixtures/sema/unsupported_map_keys.pine`, and
  `tests/fixtures/sema/unsupported_map_values.pine` cover non-map receivers.
  `tests/fixtures/sema/unsupported_map_put_all.pine` covers a non-map source
  receiver, and `tests/fixtures/sema/unsupported_map_put_all_template.pine`
  covers source/target template mismatch.
- `crates/pine-runtime/src/builtins/maps.rs` stores maps as dedicated
  runtime-owned ids with an internal map store.
- `crates/pine-sema/tests/fixtures.rs` asserts both the positive subset and the
  remaining negative boundaries.

Do not widen `map.*` beyond `map.new`, `map.size`, `map.put`, `map.get`,
`map.contains`, `map.clear`, `map.remove`, `map.copy`, `map.keys`,
`map.values`, `map.put_all`, and their equivalent method aliases until a
runtime slice implements the behavior and updates fixtures, conformance,
snapshots, and docs together.

## Target Shape

The first positive map subset should mirror the existing array discipline:

- maps are runtime-owned ids, not host-visible structures;
- assignment passes map ids by reference;
- `map.copy()` is the explicit independent-copy boundary;
- non-`var` declarations allocate when executed;
- `var` declarations preserve the map id and backing storage across bars;
- rollback restores map backing storage to the confirmed snapshot;
- map growth is bounded by a runtime limit and visible in runtime profiles.

The first runtime value is `PineValue::Map(u32)` with a dedicated runtime store.
It does not reuse array ids or array element storage for map entries. Future
map mutation needs key lookup, replacement, deletion, and iteration semantics
that are different from array slot indexing.

## Key And Value Policy

First positive key families:

- `int`
- `float`
- `bool`
- `string`
- `color`

First positive value families:

- `int`
- `float`
- `bool`
- `string`
- `color`
- `na`

Deferred key and value families:

- arrays;
- maps;
- matrices;
- user-defined types;
- tuples;
- object ids;
- chart points;
- strategy/order/trade records.

Rationale:

- scalar keys avoid object identity and lifetime problems in the first slice;
- scalar values avoid nested collection rollback and aliasing problems;
- UDT and collection values should wait for explicit identity and history rules.

## Equality And Ordering

Map key equality must be deterministic and independent of host formatting.

Initial policy:

- `int`, `bool`, `string`, and `color` keys compare by exact value;
- `float` keys compare by exact finite bit/value semantics chosen by the runtime
  design slice;
- `na` keys are rejected in semantic analysis or at runtime before insertion;
- non-finite float keys are rejected.

Iteration order is not a hidden implementation detail. `map.keys()` and
`map.values()` return insertion-order snapshots. Replacement of an existing key
updates the value without moving the key in order. Deleting and reinserting a
key appends it at the new insertion point.

## Type Model

The semantic model should represent map types explicitly, not as generic arrays.

Future type candidates:

- `map<int, float>`
- `map<string, float>`
- `map<string, string>`
- `map<simple-key, scalar-value>` only if the analyzer can keep diagnostics clear.

The initial slices avoid broad generic inference. They accept explicit typed
constructors such as `map.new<string, float>()`, `map.new<int, int>()`,
`map.new<bool, bool>()`, `map.new<color, color>()`, and
`map.new<string, string>()`, and carry scalar key/value templates through
`map.put`, `map.get`, and `map.contains`.

Bare `map` declarations and mixed value maps should stay unsupported until type
identity, `na` value behavior, and assignment compatibility are designed.

## Runtime Operations

Current operation set:

- `map.new<K, V>()`
- `map.size(id)`
- `map.put(id, key, value)`
- `map.get(id, key)`
- `map.contains(id, key)`
- `map.clear(id)`
- `map.remove(id, key)`
- `map.copy(id)`
- `map.keys(id)`
- `map.values(id)`
- `map.put_all(target, source)`
- equivalent `id.size()`, `id.put(key, value)`, `id.get(key)`,
  `id.contains(key)`, `id.clear()`, `id.remove(key)`, `id.copy()`,
  `id.keys()`, `id.values()`, and `id.put_all(source)` aliases.

Candidate later operation set: no additional map helper is currently selected
before history and declaration work.

Method-call aliases should continue to lower to the same fixture-backed
namespace operations after receiver typing is stable.

## History And Realtime

First history policy:

- `previous = m[1]` returns a fresh copy of the committed scalar map snapshot,
  not an alias into past storage;
- dynamic history over map ids uses the same retention guardrails as other
  supported history values;
- scalar map `varip` slots seed from the previous forming update together with
  the referenced map backing store;
- map state must still roll back correctly for ordinary realtime forming updates.

Later history policy:

- nested maps or collection values require a deeper copy policy before support;
- non-scalar map `varip` values require the same deeper copy policy before
  support.

## Function And Method Boundaries

Current policy:

- read-only map helpers can consume map ids passed to user-defined functions
  when the caller argument has known scalar map template metadata;
- map mutation inside user-defined functions stays unsupported, matching the
  current conservative array and matrix mutation boundary;
- method calls on maps lower to the same namespace-call behavior.

## Diagnostics

Before additional positive support lands, keep unsupported diagnostics precise.
The legacy broad diagnostic still applies to unimplemented `map.*` operations:

```text
map collections are not implemented; map.* requires a dedicated key/value storage model
```

Unsupported variants should fail with precise diagnostics:

- unsupported key type;
- unsupported value type;
- `na` key;
- non-finite float key;
- unknown map method;
- map mutation inside an unsupported side-effect context;
- map `varip` use outside the supported subset.

## Slice Order

Recommended future slices:

1. Semantic design lock: add type names, signatures, and negative fixtures.
   Done.
2. Runtime store skeleton: add an internal map store. Done.
3. First positive scalar subset:
   `map.new<int|float|bool|string|color, int|float|bool|string|color>()` and
   `map.size(id)`. Done.
4. First mutation/read subset: `map.put`, `map.get`, and `map.contains`.
   Done.
5. Copy semantics: `map.copy` and assignment/reference fixtures. Done.
6. Realtime rollback fixtures for map mutation. Done.
7. Method-call aliases after namespace calls are stable. Done.
8. `map.keys` / `map.values` array snapshots in insertion order. Done.
9. Scalar map history snapshots using independent committed copies.
   Done.
10. Scalar `map<K,V>` typed declarations, bare scalar `map` declaration
    inference from known scalar map expressions, and `varip` intrabar handoff.
    Done.
11. Same-template `map.put_all` merge behavior. Done.
12. Unqualified local-UDF call results with one concrete supported scalar map
    template share direct size/get/contains/copy with copy-only continuation,
    per-call template isolation, and retained non-local/unresolved/broader/
    mutation boundaries. Done.
13. Local user-method call results with one concrete supported scalar map
    template share direct size/get/contains/copy for receiver-style,
    local-type-qualified, and direct-constructor receivers, with block/nested/
    control-flow/template/copy coverage and retained imported-method,
    unresolved, broader-helper, mutation, and terminal-reader boundaries.
    Done.
14. Imported user-method call results with one concrete supported scalar map
    template share direct size/get/contains/copy for receiver-style,
    alias-qualified, and direct-constructor receivers, with block/nested/
    control-flow/template/dual-alias/copy coverage and retained imported-
    function, unresolved, broader-helper, mutation, and terminal-reader
    boundaries. Done.
15. Imported pure-function call results with one concrete supported scalar map
    template share direct size/get/contains/copy for alias-qualified calls,
    with block/nested/control-flow/template/dual-alias/copy coverage and
    retained scalar-result, unresolved, broader-helper, mutation, and terminal-
    reader boundaries. Done.
16. Fresh `.keys()` and `.values()` arrays from every existing concrete scalar-
    map call-result producer additionally expose terminal `.includes(value)`.
    The helper preserves key/value element-kind checks and insertion-order
    snapshots, returns `series bool`, is false for an empty concrete array,
    propagates upstream `na`, performs no mutation, and creates no array-result
    prefix. Built-in, local/imported function and method, dual-alias isolation,
    copy continuation, invalid types/arity, and terminal-continuation paths are
    fixture-backed. Done.
17. The same fresh key/value arrays additionally expose terminal
    `.indexof(value)`. It preserves key/value kind checks and insertion-order
    snapshots, returns the first zero-based match as `simple int`, returns `-1`
    for missing/empty/upstream-`na` arrays, performs no mutation, and creates no
    array-result prefix. Built-in, local/imported function and method, dual-
    alias isolation, copy continuation, invalid types/arity, and terminal-
    continuation paths are fixture-backed. Done.
18. The same fresh key/value arrays additionally expose terminal
    `.lastindexof(value)`. It preserves key/value kind checks and insertion-
    order snapshots, returns the last zero-based match as `simple int`, returns
    `-1` for missing, empty, and upstream-`na` arrays, performs no mutation, and
    creates no array-result prefix. Built-in, local/imported function and
    method, dual-alias isolation, copy continuation, invalid types/arity, and
    terminal-continuation paths are fixture-backed. Done.
19. Fresh numeric key/value arrays from the same concrete scalar-map call-
    result producers additionally expose terminal `.binary_search(value)`.
    Only int/float map sides pass the ordinary numeric receiver/value gate;
    callers remain responsible for ascending insertion-order snapshots. Exact
    lower-bound search returns the leftmost duplicate match as `simple int` or
    `-1` for missing, empty, and upstream-`na` arrays, performs no mutation,
    and creates no continuation prefix. Bool/string/color map sides, invalid
    types/arity, local/imported function and method provenance, dual aliases,
    copy continuation, and terminal continuation are fixture-backed. Done.
20. The same fresh numeric key/value arrays additionally expose terminal
    `.binary_search_leftmost(value)`. It retains the numeric receiver/value gate
    and caller-owned ascending insertion-order contract. Exact duplicates return
    their first index; misses return the nearest-left index, clamped to `0`
    below the minimum and the last index above the maximum. Empty/upstream-`na`
    arrays return `-1`; the `simple int` result is non-mutating and terminal.
    Bool/string/color sides, local/imported provenance, dual aliases, invalid
    types/arity, copy continuation, and terminal continuation are fixture-
    backed. Done.
21. The same numeric key/value snapshots expose terminal
    `.binary_search_rightmost(value)`. Exact duplicates return their last index;
    misses return the nearest-right index, with the same below-min/above-max
    clamps, numeric/ascending gates, empty/upstream-`na` `-1`, `simple int`,
    non-mutation, and terminal boundaries. Bool/string/color sides, local/
    imported provenance, dual aliases, invalid types/arity, copy continuation,
    and terminal continuation are fixture-backed. Done.
22. Numeric key/value snapshots additionally expose `.abs()` as a fresh
    key/value-kind-preserving array transformation. Int/float values, empty and
    upstream-`na` results, source independence, invalid nonnumeric/arity cases,
    and copy/abs/read continuation are fixture-backed. Map storage and template
    rules are unchanged. Done.
23. Numeric key/value snapshots additionally expose terminal `.min(nth?)`.
    Receiver-derived series int/float results, filtered ascending zero-based
    ranks, dynamic integer ranks, empty/upstream-`na`, invalid type/rank/arity,
    local/imported provenance, and terminal continuation are fixture-backed.
    Map storage and template rules are unchanged. Done.
24. Numeric key/value snapshots additionally expose terminal `.max(nth?)` with
    descending zero-based ranks. Receiver-derived series int/float, dynamic
    ranks, empty/upstream-`na`, invalid type/rank/arity, local/imported
    provenance, and terminal continuation are fixture-backed. Map storage and
    template rules are unchanged. Done.
25. Numeric key/value snapshots additionally expose terminal `.sum()`.
    Receiver-derived series int/float, filtered `na`, empty/all-`na`/upstream-
    `na`, invalid type/arity, local/imported provenance, and terminal
    continuation are fixture-backed. Map storage and template rules are
    unchanged. Done.
26. Numeric key/value snapshots additionally expose terminal `.avg()`.
    Fixed series-float results, filtered `na`, empty/all-`na`/upstream-`na` and
    non-finite behavior, invalid type/arity, local/imported provenance, and
    terminal continuation are fixture-backed. Map storage and template rules
    are unchanged. Done.
27. Numeric key/value snapshots additionally expose terminal `.range()`.
    Receiver-derived series int/float, filtered maximum-minus-minimum, empty/
    all-`na`/upstream-`na` and non-finite behavior, invalid type/arity, local/
    imported provenance, and terminal continuation are fixture-backed. Map
    storage and template rules are unchanged. Done.
28. Numeric key/value snapshots additionally expose terminal `.median()`.
    Filtered sorting, odd-middle and even middle-pair means, receiver-derived
    series int/float, integer truncation toward zero, empty/all-`na`/upstream-
    `na` and non-finite-float behavior, invalid type/arity, local/imported
    provenance, and terminal continuation are fixture-backed. Map storage and
    template rules are unchanged. Done.
29. Numeric key/value snapshots additionally expose terminal `.mode()`.
    Filtered frequency counting, smaller-value tie selection, the repeated-
    value requirement, receiver-derived series int/float, empty/all-`na`/
    upstream-`na` and all-unique behavior, invalid type/arity, local/imported
    provenance, and terminal continuation are fixture-backed. Map storage and
    template rules are unchanged. Done.
30. Numeric key/value snapshots additionally expose terminal
    `.percentile_nearest_rank(percentage)`. Filtered ceiling-based nearest-rank
    selection, 0/100 endpoints, positional or named series/simple numeric
    percentages, receiver-derived series int/float, empty/all-`na`/upstream-
    `na`, runtime typed-`na` and out-of-range behavior, invalid type/arity,
    local/imported provenance, and terminal continuation are fixture-backed.
    Map storage and template rules are unchanged. Done.
31. Numeric key/value snapshots additionally expose terminal
    `.percentile_linear_interpolation(percentage)`. Sorted floor/ceiling
    interpolation, fixed series-float results for int/float and single-element
    inputs, positional or named series/simple numeric percentages, empty/all-
    `na`/upstream-`na`, runtime typed-`na`, out-of-range and non-finite-result
    behavior, invalid type/arity, local/imported provenance, and terminal
    continuation are fixture-backed. Map storage and template rules are
    unchanged. Done.
32. Numeric key/value snapshots additionally expose terminal
    `.percentrank(index)`. Original-index target selection, filtered comparison
    population, duplicate counting, fixed series-float results, positional or
    named simple-int-compatible indexes, empty/all-`na`/upstream-`na`, target-
    `na`, runtime typed-`na`, negative and out-of-range behavior, invalid type/
    arity, local/imported provenance, and terminal continuation are fixture-
    backed. Map storage and template rules are unchanged. Done.
33. Numeric key/value snapshots additionally expose terminal
    `.covariance(id2, biased?)`. Same-length numeric second-array checks,
    original-index pairing, paired-`na` filtering, population/sample bias,
    fixed series-float results, empty/all-`na`/upstream-`na`, mismatched-length,
    insufficient-sample and non-finite-result behavior, invalid type/arity,
    local/imported provenance, and terminal continuation are fixture-backed.
    Map storage and template rules are unchanged. Done.
34. Numeric key/value snapshots additionally expose transforming
    `.standardize()`. It returns an independent fixed float array, computes
    mean and population standard deviation over non-`na` values, preserves
    `na` positions, maps numeric positions to `na` for zero or non-finite
    deviation, returns empty for empty/all-`na`, and propagates upstream `na`.
    Invalid type/arity, local/imported provenance, source independence, and
    copy/abs/standardize/sort_indices continuation are fixture-backed. Map storage and
    template rules are unchanged. Done.
35. Numeric key/value snapshots additionally expose terminal
    `.variance(biased?)`. Filtered non-`na` values, population default/`true`
    bias, sample `false`/`na` bias, single-value population zero, fixed series-
    float results, empty/all-`na`/upstream-`na`, insufficient-sample and non-
    finite behavior, invalid type/arity, local/imported provenance, non-
    mutation, and terminal continuation are fixture-backed. Map storage and
    template rules are unchanged. Done.
36. Numeric key/value snapshots additionally expose terminal
    `.stdev(biased?)`. It takes the square root of the same filtered population
    or sample variance and retains default/`true` population and `false`/`na`
    sample bias, single-value population zero, fixed series-float results,
    empty/all-`na`/upstream-`na`, insufficient-sample and non-finite behavior,
    invalid type/arity, provenance, non-mutation, and terminal continuation.
    Map storage and template rules are unchanged. Done.
37. Int, float, or string key/value snapshots additionally expose transforming
    `.sort_indices(order?)`. The fresh index array preserves stable source
    positions, default ascending or explicit descending order, float-`na` and
    string-empty placement, empty and upstream-`na` behavior, source-map and
    snapshot independence, and nested array-result continuation. Bool/color
    snapshots, invalid order/arity, and direct result mutation remain closed.
    Map storage and template rules are unchanged. Done.
38. Bool, int, or float key/value snapshots additionally expose terminal
    `.every()`. Nonzero numerics and `true` are truthy; zero, `false`, and
    element `na` are false. Empty snapshots return true, typed-`na` maps
    propagate `na`, and both the source map and snapshot remain unchanged.
    String/color, extra-arity, and terminal-continuation boundaries remain
    closed. Map storage and template rules are unchanged. Done.
39. The same bool/int/float key/value snapshots additionally expose terminal
    `.some()`. It returns true when any nonzero numeric or `true` element
    exists, treats zero, `false`, and element `na` as nonsatisfying, returns
    false for empty snapshots, propagates typed-`na` maps, leaves the map and
    snapshot unchanged, and retains string/color, extra-arity, and terminal-
    continuation boundaries. Map storage and template rules are unchanged.
    Done.
40. Every scalar key/value snapshot additionally exposes terminal
    `.join(separator?)`. It preserves insertion-order snapshot values, ordinary
    default/explicit/`na` separator and scalar/color stringification rules,
    empty-string and typed-`na` map results, source-map and snapshot
    independence, and the 40960-character limit. Invalid separator/arity and
    terminal-continuation boundaries remain closed. Map storage and template
    rules are unchanged. Done.
41. Every concrete scalar key/value snapshot additionally exposes transforming
    `.slice(index_from, index_to)`. It preserves the key/value element kind and
    insertion order, returns a live shallow window over the fresh snapshot,
    and may continue through the closed array-result helper set. The slice is
    independent of the source map but retains bidirectional aliasing with its
    own snapshot parent. Empty and typed-`na` maps, invalid range type/arity,
    negative/reversed/out-of-range bounds, scalar-template interleaving, and
    terminal or mutation boundaries remain fixture-backed. Map storage and
    template rules are unchanged. Done.
42. Every concrete scalar key/value snapshot additionally exposes terminal
    top-level `.clear()`. The call mutates only the fresh keys/values snapshot,
    returns `void`, accepts no explicit arguments, tolerates empty or typed-
    `na` map results, and cannot continue; the source map and insertion order
    remain unchanged. Direct call-result mutation inside UDFs and all other
    postfix mutations stay rejected. Map storage, templates, and public
    schemas are unchanged. Done.
43. Every concrete scalar key/value snapshot additionally exposes terminal
    top-level `.reverse()`. It reverses only the fresh snapshot, returns
    `void`, accepts no explicit arguments, tolerates empty or typed-`na` map
    results, and cannot continue; source map entries and insertion order remain
    unchanged. Direct call-result mutation inside UDFs and all remaining
    postfix mutations stay rejected. Map storage, templates, and public
    schemas are unchanged. Done.
44. Every concrete scalar key/value snapshot additionally exposes terminal
    top-level `.pop()`. It removes and returns only the fresh snapshot's final
    insertion-order key or value with the resolved scalar kind, returns `na`
    for empty or typed-`na` maps, and cannot continue; source map entries and
    insertion order remain unchanged. Direct call-result mutation inside UDFs
    and all remaining postfix mutations stay rejected. Map storage, templates,
    and public schemas are unchanged. Done.
45. Every concrete scalar key/value snapshot additionally exposes terminal
    top-level `.shift()`. It removes and returns only the fresh snapshot's first
    insertion-order key or value with the resolved scalar kind, preserves the
    remaining snapshot order, returns `na` for empty or typed-`na` maps, and
    cannot continue; source map entries and insertion order remain unchanged.
    Direct call-result mutation inside UDFs and all remaining postfix mutations
    stay rejected. Map storage, templates, and public schemas are unchanged.
    Done.
46. Every concrete scalar key/value snapshot additionally exposes terminal
    top-level `.remove(index)`. It removes and returns the selected positive or
    in-range negative insertion-order key/value from only the fresh snapshot,
    preserving its scalar kind and remaining order. Explicit `na` indexes and
    typed-`na` map results return `na` without mutation; out-of-range indexes
    retain runtime errors. The source map and insertion order remain unchanged.
    Direct call-result mutation inside UDFs and all remaining postfix mutations
    stay rejected. Map storage, templates, and public schemas are unchanged.
    Done.
47. Every concrete scalar key/value snapshot additionally exposes terminal
    top-level `.push(value)`, including keys/values reached through supported
    built-in, copied, local/imported function, and local/imported method map
    results. It validates the resolved key/value scalar kind, appends only to
    the fresh snapshot, returns `void`, and cannot continue; source map entries
    and insertion order remain unchanged. Invalid kind/arity, typed-`na` map,
    capacity, and UDF-side-effect boundaries retain ordinary behavior. Map
    storage, templates, and public schemas are unchanged. Done.
48. Every concrete scalar key/value snapshot additionally exposes terminal
    top-level `.unshift(value)`, including keys/values reached through supported
    built-in, copied, local/imported function, and local/imported method map
    results. It validates the resolved key/value scalar kind, prepends only to
    the fresh snapshot, returns `void`, and cannot continue; source map entries
    and insertion order remain unchanged. Invalid kind/arity, typed-`na` map,
    capacity, and UDF-side-effect boundaries retain ordinary behavior. Map
    storage, templates, and public schemas are unchanged. Done.
49. Every concrete scalar key/value snapshot additionally exposes terminal
    top-level `.insert(index, value)`, including keys/values reached through
    supported built-in, copied, local/imported function, and local/imported
    method map results. It validates the simple-int-compatible index and
    resolved key/value scalar kind, inserts only into the fresh snapshot,
    returns `void`, and cannot continue; source map entries and insertion order
    remain unchanged. Negative/end/`na` index, bounds, kind/arity, typed-`na`
    map, capacity, and UDF-side-effect boundaries retain ordinary behavior.
    Map storage, templates, and public schemas are unchanged. Done.
50. Every concrete scalar key/value snapshot additionally exposes terminal
    top-level `.set(index, value)`, including keys/values reached through
    supported built-in, copied, local/imported function, and local/imported
    method map results. It validates the simple-int-compatible index and
    resolved key/value scalar kind, replaces one fresh-snapshot slot without
    changing length, returns `void`, and cannot continue; source map entries
    and insertion order remain unchanged. Negative/`na`/empty/out-of-range,
    kind/arity, typed-`na` map, and UDF-side-effect boundaries retain ordinary
    behavior. Map storage, templates, and public schemas are unchanged. Done.
51. Every concrete scalar key/value snapshot additionally exposes terminal
    top-level `.fill(value, index_from?, index_to?)`, including keys/values
    reached through supported built-in, copied, local/imported function, and
    local/imported method map results. It validates the resolved scalar kind
    plus optional simple-int-compatible half-open bounds; omitted bounds fill
    the full fresh snapshot while source map entries and insertion order remain
    unchanged. Explicit `na`, negative, reversed, oversized, empty, typed-`na`,
    and upstream-`na` cases no-op after all supplied arguments are evaluated.
    It returns `void`, cannot continue, remains rejected inside UDFs, and leaves
    map storage, templates, and public schemas unchanged. Done.
52. Every concrete int/float/string key/value snapshot additionally exposes
    terminal top-level `.sort(order?)`, including keys/values reached through
    supported built-in, copied, local/imported function, and local/imported
    method map results. It preserves ordinary stable ascending/default or
    descending ordering on the fresh snapshot; source map entries and insertion
    order remain unchanged. Empty, typed-`na`, and upstream-`na` results no-op
    after order evaluation, while bool/color kinds, invalid order/arity,
    continuation, and UDF-side-effect boundaries stay closed. Map storage,
    templates, and public schemas remain unchanged. Done.
53. Every concrete scalar key/value snapshot additionally exposes mutating,
    array-returning `.concat(id2)`, including keys/values reached through
    supported built-in, copied, local/imported function, and local/imported
    method map results. It validates a same-kind scalar-array source, appends
    only to the fresh snapshot, returns that snapshot id, and may continue
    through the closed array-result chain; source map entries and insertion
    order remain unchanged. Empty/upstream-`na`, capacity, kind/arity, and UDF-
    side-effect boundaries retain ordinary `array.concat` behavior. Map
    storage, templates, and public schemas remain unchanged. Done.
54. Every concrete scalar map call-result producer additionally exposes
    terminal `.put(key, value)`: supported `map.new<K,V>`, `map.copy(existing)`,
    local/imported pure functions, and local/imported user methods. It validates
    the resolved scalar key/value kinds, replaces an existing value without
    moving its key or appends a new insertion-order entry, returns `void`, and
    cannot continue. Local UDF and local user-method alias results update shared
    storage; fresh built-in and imported producers isolate the write. Invalid
    key/value/arity, UDF-side-effect, remaining map-mutation, template, and
    public-schema boundaries retain ordinary `map.put` behavior. Done.
55. Every concrete scalar map call-result producer additionally exposes
    terminal `.clear()`. It empties the resolved backing entry list, returns
    `void`, and cannot continue. Local UDF and local user-method alias results
    update shared storage; fresh `map.new`, `map.copy`, imported-function, and
    imported-method results isolate the clear. Arity, UDF-side-effect,
    remaining map-mutation, template, and public-schema boundaries retain
    ordinary `map.clear` behavior. Done.
56. Every concrete scalar map call-result producer additionally exposes
    terminal `.remove(key)`. It validates the resolved scalar key kind,
    removes a matching entry without reordering retained keys, no-ops for a
    missing key, returns `void`, and cannot continue. Local UDF and local user-
    method alias results update shared storage; fresh constructor, copy,
    imported-function, and imported-method results isolate the removal.
    Invalid key/arity, UDF-side-effect, remaining map-mutation, template, and
    public-schema boundaries retain ordinary `map.remove` behavior. Done.
57. Every concrete scalar map call-result producer additionally exposes
    terminal `.put_all(source)`, completing the registered scalar map helper
    set on those receivers. It requires an identical source template, clones
    source entries before merging for self-merge safety, replaces values
    without moving retained keys, appends new keys in source order, returns
    `void`, and cannot continue. Local aliases update shared storage; fresh
    constructor, copy, imported-function, and imported-method targets isolate
    the merge. Invalid source/template/arity, UDF-side-effect, and public-
    schema boundaries retain ordinary `map.put_all` behavior. Done.

## Completion Gate For Future Widening

Any wider map support must include:

- semantic fixtures for accepted and rejected key/value forms;
- runtime fixtures and golden snapshots;
- realtime rollback tests when mutation is supported;
- incremental-vs-historical parity tests when history or state timing matters;
- profile or guardrail tests for map storage growth;
- synchronized `tests/fixtures/conformance.tsv`, `docs/CONFORMANCE.md`, matrix
  snapshot, release notes, and this design document;
- `git diff --check`;
- `scripts/verify.sh`.

## Closed Slice Result

The first map slice added fixture-backed syntax, analysis, runtime behavior,
conformance, and snapshot coverage for `map.new<K, V>()` empty map construction
over scalar key/value templates and `map.size(id)`. The runtime stores maps as
dedicated ids and serializes map values as `null`/`None` at public output
boundaries.

The second map slice added scalar namespace-call `map.put`, `map.get`, and
`map.contains`. Map entries are stored in insertion order; `map.put` replaces
the value for an equal existing key, `map.get` returns `na` for missing keys,
and `map.contains` returns a series bool.

The third map slice added scalar namespace-call `map.clear`. Clearing empties
the entry list without changing the map id, so later `map.put` calls reuse the
same backing map.

The fourth map slice added scalar namespace-call `map.remove`. Removing deletes
the matching key when present and leaves the map unchanged for missing keys.

Later scalar map slices added `map.copy`, `map.keys`, `map.values`,
`map.put_all`, equivalent method aliases, scalar `map<K,V>` typed declarations,
bare scalar `map` declaration inference from known scalar map expressions,
read-only UDF parameter use, independent history snapshots, ordinary realtime
rollback, scalar map `varip` intrabar handoff, and direct scalar-map `for...in`
iteration where a single loop variable receives the key and `[key, value]`
receives both entries. Template-less bare map declarations, non-scalar key/value
templates, nested collection values, and map mutation inside user-defined
functions remain unsupported until a later slice designs and fixtures those
semantics. Unqualified local-UDF results with a concrete supported scalar map
template now share the complete size/put/clear/remove/put_all/get/contains/
copy/keys/values helper set with terminal put/clear/remove/put_all,
copy-only map continuation, derived-array transitions, and per-call template
isolation. Local and imported user-function and user-method results with a
concrete supported scalar map template now share the same helpers, including
the complete helper set and same-library dual-alias isolation;
unresolved or mixed-template direct result receivers remain gated.
