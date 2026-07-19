# Phase E Drawing Object Platform Audit

Phase E is closed for the current fixture-backed drawing object subset. Future
drawing work should be treated as targeted drawing maintenance or as part of a
later platform phase unless it widens an already claimed object method in a
small, fixture-backed way.

## Completed Slices

- Slice 1, drawing output contract scaffold:
  `a10432f Add drawing output contract scaffold`.
  Runtime public outputs moved to `schemaVersion: 2` and reserved top-level
  `labels`, `lines`, `boxes`, and `tables` fields across CLI JSON, WASM JSON,
  and Python dictionaries.
- Slices 2-6, label lifecycle:
  `f2d88d5`, `349e21a`, `225b9f1`, `939c2df`, and `58ca786`.
  Labels now cover creation, selected options, selected mutators, deletion,
  runtime limits, profile fields, control-flow fixtures, UDF side-effect
  rejection, incremental append, and realtime rollback.
- Slices 7-8, line lifecycle:
  `7448945 Support minimal line creation` and
  `6dfcd3d Support line lifecycle snapshots`.
  Lines now cover creation, selected endpoint/color/width/style/extend
  mutators, deletion, limits, profiles, control flow, incremental append, and
  realtime rollback.
- Slice 9, box lifecycle:
  `a2c7b08 Support box lifecycle snapshots`.
  Boxes now cover creation, selected geometry/background/border mutators,
  deletion, limits, profiles, control flow, incremental append, and realtime
  rollback.
- Slice 10, table cell snapshots:
  `d23a83e Support table cell snapshots`.
  Tables now cover deterministic `table.new` dimensions and position constants,
  `table.cell` text/background/text-color writes, limits, profiles, control
  flow, incremental append, and realtime rollback.
- Slice 11, polyline design gate:
  `fd35d7a Document polyline design gate`.
  `polyline.*` remains explicitly unsupported because executable support needs
  `chart.point` values and point-list arrays. A later slice added
  fixture-backed `chart.point` constructor/copy and top-level field access, but
  point-list arrays and polyline runtime state remain unsupported.
- Slice 12, structure closeout:
  `a64dd12 Split drawing runtime builtins by family`.
  Runtime drawing dispatch is separated from family-specific label, line, box,
  and table evaluation modules.

## Supported Surface

The compatibility matrix in `tests/fixtures/conformance.tsv` is the source of
truth for supported drawing claims.

- `label.new` is partial: bar-index `x`, numeric `y`, string-compatible text,
  `xloc.bar_index`, `yloc.price`, color-compatible fields, selected
  `label.style_*`, selected `size.*`, and tooltip snapshots.
- `label.set_x`, `label.set_y`, `label.set_xy`, `label.set_text`,
  `label.set_color`, `label.set_textcolor`, `label.set_style`,
  `label.set_size`, `label.set_tooltip`, and `label.delete` are partial and
  snapshot-backed.
- `line.new` is partial: bar-index endpoint x values, numeric endpoint y
  values, optional initialization for existing extend/color/style/width snapshot
  fields, selected endpoint/color/width/style/extend mutators, and
  `line.set_xloc` for `xloc.bar_index`, and `line.delete`. `line.get_x1`,
  `line.get_y1`, `line.get_x2`, and `line.get_y2` read the latest existing
  line snapshot. `line.get_price` derives a bar-index price from that latest
  snapshot by interpolation or extrapolation.
- `box.new` is partial: bar-index left/right coordinates, numeric top/bottom
  coordinates, optional initialization for existing background/border/extend/
  text/text-color/text-size/alignment/wrap/font-family/text-formatting snapshot
  fields, selected geometry/background/border/text mutators,
  `box.set_xloc` for `xloc.bar_index`, and `box.delete`.
- `table.new` is partial: supported `position.*` constants plus positive column
  and row dimensions, with `table.cell` text/background/text-color writes.
- Supported label, line, box, and table id-first functions also accept Pine
  method-call syntax as aliases for their namespace-call forms.
- `linefill.new` is partial: it creates runtime-owned linefill ids over
  supported line ids, emits sparse color snapshots, and replaces the previous
  linefill for the same line pair. `linefill.set_color` is partial for sparse
  color mutation snapshots. `linefill.get_line1` and `linefill.get_line2`
  return referenced line ids. `linefill.delete` appends deletion snapshots, and
  `linefill.all` returns currently existing linefill ids in creation order.
  `array.new_linefill` and `array.from` support linefill id arrays for generic
  object-array storage, mutation, reads, and search while numeric/truth/sort/join
  helpers reject linefill arrays with type diagnostics.
- `polyline.*` is unsupported and has a dedicated design note in
  `docs/PHASE_E_POLYLINE_GATE.md`.

## Public Output Contract

The drawing output contract is `schemaVersion: 2`. Runtime public outputs expose
these top-level drawing keys:

```text
labels
lines
boxes
tables
```

Labels, lines, and boxes use sparse object snapshots with deterministic ids and
non-reused ids. Deletion-capable families append an `exists: false` snapshot;
deleting `na`, mutating `na`, or mutating an already deleted object is a no-op.
Invalid non-`na` ids are runtime errors.

Tables use sparse table snapshots. A table entry carries `position`, `columns`,
`rows`, and cell snapshots; each cell snapshot records `column`, `row`, `text`,
`bgColor`, and `textColor`. Table clearing, deletion, layout details, and
advanced styling are not claimed.

Runtime limits are deterministic:

- Labels: 500 objects.
- Lines: 500 objects.
- Boxes: 500 objects.
- Tables: 50 objects.
- Table cells: 1000 cells per table.

## Coverage Evidence

- Golden snapshots cover representative outputs for every supported drawing
  family:
  `runtime_label_new.json`, `runtime_label_options.json`,
  `runtime_label_mutation.json`, `runtime_label_delete.json`,
  `runtime_line_new.json`, `runtime_line_mutation.json`,
  `runtime_line_delete.json`, `runtime_box_new.json`,
  `runtime_box_mutation.json`, `runtime_box_delete.json`,
  `runtime_table_new.json`, and `runtime_table_cell.json`.
- Runtime fixtures cover creation, mutation or cell writes, control flow,
  deletion where supported, and limit failures.
- `crates/pine-runtime/tests/incremental.rs` checks every runtime fixture
  against incremental append execution, so the drawing fixtures participate in
  full-vs-append equivalence.
- Realtime fixtures cover forming-bar rollback for labels, lines, boxes,
  tables, and the supported polyline lifecycle subset.
- Python binding tests assert representative `labels`, `lines`, `boxes`, and
  `tables` dictionary output. WASM tests assert the top-level drawing keys.
- The matrix JSON snapshot includes separate rows for every supported drawing
  method group, `linefill.new`/`linefill.set_color` partial support, remaining
  unsupported linefill collections/methods, and `polyline.*`.

## Verification Results

The Phase E closeout verification command is:

```text
scripts/verify.sh
```

It passed on the closeout workspace. This command includes:

- `cargo fmt --check`
- `cargo clippy --workspace --all-targets -- -D warnings`
- `cargo test --workspace`
- `python3 scripts/check_structure.py`
- `cargo check -p pine-wasm --target wasm32-unknown-unknown`
- `maturin build --manifest-path crates/pine-python/Cargo.toml --out dist`
- `python3 -m pip install --force-reinstall dist/*.whl`
- `python3 -m pytest python/tests`

The final structure check also keeps new runtime drawing files small: the
dispatch module is 58 lines, and family modules are 164-280 lines.

## Remaining Maintenance Tails

These are not blockers for closing Phase E:

- Remaining drawing collection support is now concentrated on polyline general
  array and limit behavior; the current linefill object lifecycle,
  object-array construction/read/mutation/search subset, partial `chart.point`
  constructor/copy/field/point-array subset, and `polyline.new`,
  `polyline.delete`, and `polyline.all` snapshots are fixture-backed for the
  historical and realtime rollback runtime subset.
- General polyline arrays plus runtime use of parsed polyline max-count settings
  and eviction parity remain unsupported until dedicated slices implement and
  verify them.
- Advanced label, line, box, and table methods remain diagnostic-only until
  they have semantic signatures, runtime behavior, public snapshots, fixtures,
  and conformance rows.
- Unsupported coordinate modes such as non-bar-index drawing coordinates remain
  diagnostic-only.
- Table deletion and clearing are not part of the current table claim; add them
  only with host-neutral snapshot semantics and rollback fixtures.
- Python still maps runtime outputs through explicit dictionary conversion
  instead of generated JSON conversion. Keep binding key tests synchronized with
  runtime output fields.

## Recommended Next Stage

Start Phase F next only after accepting that Phase E's drawing claim is a
stable partial platform, not exhaustive TradingView drawing compatibility. The
next large platform gap is `request.*` and multi-timeframe data. Drawing work
before Phase F should be limited to narrow maintenance fixes backed by fixtures
and matrix rows.
