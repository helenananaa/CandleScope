# Phase E Polyline Gate

Phase E originally kept `polyline.*` unsupported. Post-gate slices now support
the historical runtime lifecycle subset: `polyline.new`, `polyline.delete`, and
`polyline.all`. Official Pine polylines are object ids created from an
`array<chart.point>` input, so support started with the point-list creation path
rather than ad hoc scalar overloads.

The supported drawing families now have runtime-owned scalar ids and
host-neutral snapshots:

- `label.*`
- `line.*`
- `box.*`
- `table.*`
- `polyline.new`, `polyline.delete`, and `polyline.all`

`polyline.new` needs a point-list input model. Pine expresses that through
`chart.point` objects and arrays of points. The official creation form is:

```pine
polyline.new(points, curved, closed, xloc, line_color, fill_color, line_style, line_width, force_overlay)
```

The `points` argument is an array of `chart.point` values. Each point carries
`index`, `time`, and `price` information, and `xloc` decides whether the
polyline uses the point `index` or `time` fields for x coordinates. The
creation call copies a point list into a runtime-owned drawing. Official
polylines also expose only creation, deletion, and the read-only `polyline.all`
collection; they do not have setter or getter methods, so redraws happen by
deleting and creating a new polyline.

This runtime now has fixture-backed `chart.point` constructor, field read,
top-level field mutation, and `array.new<chart.point>()` plus
`array.from(chart.point, ...)` point-array storage/read/mutation support.
`polyline.new` now copies those point arrays into host-neutral `polylines`
snapshots in runtime `schemaVersion: 7`. `polyline.delete` appends deletion
snapshots and `polyline.all` returns currently existing ids. Realtime rollback
is fixture-backed for creation, deletion, copied point lists, and `polyline.all`
reads. `polyline.new` also has fixture-backed runtime max-count eviction:
omitted declarations use the runtime's default polyline count, while named
`max_polylines_count` declaration values from 1 through 100 are consumed by the
historical runtime and evict the oldest active polyline snapshots before new
creation. General polyline arrays remain outside this lifecycle slice.

Adding a narrow `polyline.new(na)` or ad hoc tuple-based point list would create
a different language surface from Pine and would bypass the array/type model
that conformance relies on. The implementation order is therefore:

1. `polyline.new` slice: done.
   add runtime-owned polyline ids and host-neutral snapshots containing the
   copied point list, `curved`, `closed`, `xloc`, `line_color`, `fill_color`,
   `line_style`, `line_width`, and `force_overlay`.
2. Lifecycle slice: done.
   add `polyline.delete` and `polyline.all`, including deletion snapshots,
   active-object filtering, and namespace/method-call deletion behavior.
3. Release-contract slice: done for creation snapshots.
   expose the same snapshot shape through CLI, Python, and WASM hosts, then add
   conformance rows and matrix gates for the partial polyline claim.
4. Realtime rollback slice: done.
   add forming-bar creation/deletion rollback and `polyline.all` evidence.
5. Runtime max-count eviction slice: done.
   add fixture-backed oldest-active-object eviction for the runtime's default
   polyline limit and declaration-driven `max_polylines_count` values.

Polyline id arrays now have a fixture-backed storage and mutation model through
`array.new_polyline`, official `array.new<polyline>` template syntax,
typed `array<polyline>`/`polyline[]` declarations, `array.from(polyline, ...)`,
and the generic object-array helper subset.

`polyline.new` is backed by `tests/fixtures/runtime/polyline_new.pine`.
`polyline.delete`, method-call deletion, and `polyline.all` collection reads are
backed by `tests/fixtures/runtime/polyline_lifecycle.pine`, with forming-bar
rollback backed by `tests/fixtures/realtime/polyline_rollback.pine`. The
polyline max-count eviction path is backed by
`tests/fixtures/runtime/polyline_limit_eviction.pine`. Polyline id array
construction and generic object-array helpers are backed by
`tests/fixtures/runtime/polyline_array.pine`.
