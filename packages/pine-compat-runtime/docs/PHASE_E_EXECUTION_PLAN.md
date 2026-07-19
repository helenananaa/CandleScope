# Phase E Execution Plan

Status: Phase E is closed for the current fixture-backed drawing object subset.
Use `docs/PHASE_E_AUDIT.md` as the closeout record before adding new drawing
maintenance work.

Phase E adds Pine drawing objects as first-class runtime outputs. Execute it in
small, mergeable slices. Each slice should leave the workspace shippable and
should keep the compatibility matrix, public output schema, Python binding, and
WASM JSON contract in lockstep.

## Original Starting Point

This was the repository state when Phase E started:

- `tests/fixtures/conformance.tsv` marks `label/line/box/table/polyline` as
  `unsupported`.
- `pine-sema` rejects `label.*`, `line.*`, `box.*`, `table.*`, and
  `polyline.*` through the unsupported-feature path.
- `pine-builtins` has output signatures for plot, marker, bar, candle, hline,
  and fill outputs, but no drawing-object signatures.
- `pine-ir::ValueKind` and `pine-runtime::PineValue` have plot, hline, and
  array ids, but no drawing-object id values.
- `RuntimeResult` has series output families, `hlines`, and `fills`, but no
  object snapshot or event stream.
- Realtime rollback currently works by cloning historical runtime state for a
  forming update. Any object store added to `HistoricalRuntime` must therefore
  remain clone-safe and deterministic.

## Rules for Every Slice

- Add fixtures before or alongside behavior changes.
- Keep unsupported object families and methods diagnostic-only until their
  runtime behavior is designed.
- Do not mark a drawing feature `partial` or `supported` unless syntax,
  semantic analysis, runtime behavior, public outputs, docs, and conformance
  metadata agree.
- Keep drawing ids deterministic for a fixed program and bar sequence.
- Preserve historical, incremental append, and realtime forming-bar behavior.
- Update CLI/WASM JSON and Python dictionaries together for any public output
  field.
- Decide whether `PUBLIC_OUTPUT_SCHEMA_VERSION` must be incremented before the
  first public drawing-output field lands, then update snapshots in the same
  change.
- Run the full release verification gate before closing a slice that changes a
  public output schema or compatibility claim.

## Internal Structure Rules

Phase E must preserve the internal restructuring baseline. Drawing objects are
a new runtime subsystem, not permission to grow another crate-level monolith.

- Do not put object storage, snapshot collection, JSON serialization, semantic
  signatures, and runtime evaluation into one large file.
- Add object-owned modules before the first feature slice needs them. Prefer
  narrow modules such as runtime object storage, output snapshot models, output
  serialization, and per-family built-in evaluation.
- Keep existing hot paths small. `runtime/historical.rs` should orchestrate bar
  execution and delegate object behavior; it should not own label, line, box,
  table, or polyline semantics.
- Keep built-in declarations grouped by namespace or object family. Do not turn
  `pine-builtins` back into one registry file with hundreds of unrelated
  parameters.
- Keep Python and WASM bindings thin. They should map the shared runtime output
  contract, not duplicate object lifecycle logic.
- If a production Rust file is moving toward the old hotspot size range, split
  it before adding the next object family. Treat roughly 800 lines as a review
  trigger, not a goal.
- Keep this playbook as an execution index. Put large family-specific design
  notes in focused documents only when they are needed, and link them from the
  relevant slice instead of turning this file into a giant design dump.
- Each slice should have an obvious owner boundary in code review: semantic
  signature changes, runtime object storage, output contract changes, fixtures,
  and docs should be easy to inspect independently.

## Implemented Module Layout

Phase E used the existing crate boundaries. Future drawing maintenance should
not add a new crate unless a later review proves that an object boundary must be
enforced across package dependencies.

Current layout:

```text
crates/pine-ir/src/lib.rs
   ValueKind object id variants only

crates/pine-builtins/src/
   namespaces/drawings.rs       label.*, line.*, box.*, table.*, polyline.* signatures
   constants/strings.rs         xloc.*, yloc.*, label.style_*, line.style_*, position.*

crates/pine-runtime/src/
   value.rs                     PineValue object id variants only
   runtime/historical.rs        object vectors, next ids, profile aggregation
   output/
      model.rs                   RuntimeResult top-level fields and small re-exports
      drawings.rs                public drawing snapshot structs
      json.rs                    drawing JSON helpers with the shared output serializer
   builtins/
      drawings.rs                dispatch for drawing built-ins
      drawings/
         labels.rs                label.new, label.set_*, label.delete evaluation
         lines.rs                 line.new, line.set_*, line.delete evaluation
         boxes.rs                 box.new, box.set_*, box.delete evaluation
         tables.rs                table.new and table.cell evaluation

crates/pine-sema/src/analyzer/
   calls.rs                     drawing signatures, constants, and side-effect gate plumbing
   unsupported.rs               unsupported drawing subset diagnostics
```

Ownership notes:

- `pine-ir` and `pine-runtime::value` should only learn that object ids exist;
  they should not contain object lifecycle rules.
- `pine-builtins` should own signatures and accepted argument shapes, not
  runtime behavior.
- `pine-runtime::output` owns public snapshot structs and serialization, not
   call evaluation.
- `pine-runtime::builtins::drawings` owns family-specific lifecycle behavior.
- `runtime/historical.rs` currently owns the small object vectors and id
   counters. If drawing state grows beyond the current scalar-id stores, split it
   into a dedicated object store module before adding more object families.
- `pine-sema` should continue to be the gate for unsupported object methods,
  unsafe side-effect contexts, and argument/type diagnostics.
- `lib.rs` files should remain facades that declare modules and re-export public
  API names only.

## Output Contract Direction

Use snapshot-style public output for drawing objects unless a later slice records
a better event-stream design before implementation.

Recommended shape for each object family:

```text
labels: [
  {
    id: 1,
    snapshots: [
      { barIndex: 0, exists: true, x: 0, y: 100.0, text: "seed", ... },
      { barIndex: 4, exists: true, x: 4, y: 101.5, text: "moved", ... },
      { barIndex: 6, exists: false }
    ]
  }
]
```

The snapshot list should record creation, mutation, and deletion boundaries. It
does not need to duplicate unchanged object state for every bar. If a later
renderer needs dense per-bar snapshots, derive them outside the core runtime
from the stable sparse snapshot stream.

Keep field values normalized through the existing `PineValue` JSON conversion
rules where possible. Represent deleted objects with `exists: false` and no
other mutable fields unless a fixture proves a renderer needs the final field
values at deletion time.

## How to Use the Acceptance Criteria

The exit criteria under each slice are local merge criteria for that slice.
Phase E should not be marked complete until the closeout checklist is done or a
remaining object family is explicitly moved to a documented Phase E maintenance
tail.

Maintenance tails must be narrow. They may keep advanced options or rare methods
out of scope, but they must not weaken these Phase E acceptance criteria:

- Supported object families have deterministic ids, lifetime rules, rollback,
  deletion, limits, and public snapshots.
- Unsupported object families and methods produce stable diagnostics.
- Public drawing outputs are synchronized across CLI, Python, and WASM.

## Slice 1: Drawing Object Contract Scaffold

Goal: add the shared type and output contract boundaries without claiming a
specific drawing method yet.

Steps:

1. Choose and document the initial public output field names for drawing
   families, starting with `labels`.
2. Decide whether adding top-level drawing fields increments
   `PUBLIC_OUTPUT_SCHEMA_VERSION`. If yes, update every public output version
   test and snapshot in this slice.
3. Add drawing id value kinds needed for the first family:
   - `pine-ir::ValueKind::Label`
   - `pine-runtime::PineValue::Label`
4. Add runtime model structs for label snapshots in `pine-runtime` output
   modules.
5. Add empty `labels` output to `RuntimeResult`, shared JSON serialization,
   profile fields, and Python dictionary conversion.
6. Add or update top-level key tests for CLI, Python, and WASM outputs.
7. Keep `label.*` unsupported until Slice 2 registers the first method.
8. Update `docs/ARCHITECTURE.md` and `docs/CONFORMANCE.md` with the drawing
   output contract.

Exit criteria:

- Public outputs expose a stable empty drawing-output field or an explicitly
  deferred schema decision.
- CLI/WASM JSON and Python dictionaries agree on drawing top-level keys.
- Existing unsupported drawing fixtures still report unsupported diagnostics.
- Golden snapshots are refreshed only if the public output contract changed.

Verification:

```text
cargo test -p pine-runtime
cargo test -p pine-cli golden_snapshot
cargo test -p pine-wasm analysis_outputs_match_golden_snapshots
python3 -m pytest python/tests
cargo test --workspace
```

## Slice 2: Minimal `label.new` Snapshots

Goal: support deterministic label creation with a minimal immutable snapshot.

Initial scope:

- `label.new(x, y, text)` with positional and named arguments.
- `x` accepts bar-index style integer values.
- `y` accepts numeric values.
- `text` accepts string-compatible values.
- Default style/color/size fields may be emitted as `na` or documented default
  strings, but the choice must be fixture-backed.

Steps:

1. Add a `label.new` signature in the built-in registry with a `Label` return
   type.
2. Ensure semantic analysis stops treating `label.new` as unsupported while
   continuing to reject unimplemented `label.*` methods.
3. Lower `label.new` calls like other side-effecting built-ins with stable
   callsite ids.
4. Add a runtime label store with deterministic `next_label_id` allocation.
5. Evaluate `label.new` by creating a label id and appending a creation
   snapshot at the current bar.
6. Return `PineValue::Label(id)` so scripts can store the id in variables.
7. Add runtime fixtures for global-scope creation, creation inside `if`, and a
   stored label id.
8. Add a golden runtime snapshot that includes one label.
9. Change the conformance row for `label/line/box/table/polyline` only if the
   notes clearly say that the current support is limited to `label.new`.

Exit criteria:

- `label.new` works in historical runtime for fixture-covered arguments.
- Unimplemented `label.*` methods still produce precise unsupported diagnostics.
- The compatibility matrix does not imply support for `line`, `box`, `table`,
  or `polyline`.
- Public output snapshots are deterministic and reviewed.

Verification:

```text
cargo test -p pine-builtins label
cargo test -p pine-sema label
cargo test -p pine-runtime label
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test --workspace
```

## Slice 3: Label Options and Constants

Goal: widen `label.new` to common options without adding mutation yet.

Steps:

1. Add common label constants that are needed by fixtures:
   - `xloc.bar_index`
   - `yloc.price`
   - selected `label.style_*` values
   - selected `size.*` values if not already present
2. Extend `label.new` signature for common optional arguments such as `xloc`,
   `yloc`, `color`, `style`, `textcolor`, `size`, and `tooltip`.
3. Keep unsupported coordinate modes diagnostic-only if their semantics are not
   implemented.
4. Evaluate supported options into creation snapshots.
5. Add semantic tests for accepted options and rejected unsupported modes.
6. Add runtime fixtures for defaults and explicit options.
7. Update conformance notes with the exact accepted option subset.

Exit criteria:

- Common label creation scripts can express text, colors, style, size, and
  tooltip metadata.
- Unsupported coordinate modes or options fail during semantic analysis, not at
  rendering time.
- Existing label snapshots remain backward-compatible within the chosen schema
  version.

Verification:

```text
cargo test -p pine-sema label
cargo test -p pine-runtime label
cargo test --workspace
```

## Slice 4: Label Mutation Methods

Goal: support mutable label state through snapshot updates.

Initial method set:

- `label.set_x`
- `label.set_y`
- `label.set_xy`
- `label.set_text`
- `label.set_color`
- `label.set_textcolor`
- `label.set_style`
- `label.set_size`
- `label.set_tooltip`

Steps:

1. Add signatures for the selected `label.set_*` methods.
2. Add semantic acceptance rules for label ids and supported value types.
3. Define `na` label id behavior and cover it with tests.
4. Apply mutations to the runtime label store.
5. Append a sparse snapshot only when a mutation changes observable state.
6. Add fixtures for mutation on the same bar as creation, mutation on later
   bars, mutation in branches, and mutation in loops.
7. Verify full historical execution and incremental append execution produce
   identical label snapshots.
8. Update conformance metadata and docs for the supported method set.

Exit criteria:

- Mutations produce deterministic sparse snapshots.
- Invalid label ids produce stable runtime errors or documented no-op behavior.
- Incremental execution matches full recomputation for label mutation fixtures.

Verification:

```text
cargo test -p pine-runtime label
cargo test -p pine-runtime --test incremental
cargo test --workspace
```

## Slice 5: Label Deletion and Limits

Goal: complete the first label lifecycle pass.

Steps:

1. Add `label.delete` signature and runtime behavior.
2. Append a deletion snapshot with `exists: false`.
3. Define behavior for deleting an already deleted label and for deleting `na`.
4. Add a deterministic runtime object limit for labels.
5. Add profile fields for label slots, snapshots, and capacity.
6. Add fixtures for create-delete, mutate-after-delete, delete-in-branch, and
   limit failure.
7. Keep object ids stable and non-reused unless a later design explicitly
   requires id reuse.
8. Update release notes and conformance notes for label lifecycle support.

Exit criteria:

- Label creation, mutation, deletion, and limits are fixture-backed.
- Runtime profiles expose enough label storage data to catch uncontrolled
  growth.
- Public snapshots clearly represent deleted labels.

Verification:

```text
cargo test -p pine-runtime label
cargo test -p pine-runtime --test profile_fixtures
cargo test --workspace
```

## Slice 6: Label Realtime Rollback and Side-Effect Policy

Goal: make labels safe in realtime and in user-defined functions.

Steps:

1. Add realtime fixtures for label creation, mutation, and deletion on forming
   bars.
2. Confirm forming-bar updates roll back unconfirmed label store changes when a
   new forming update starts from confirmed state.
3. Define whether drawing side effects are allowed inside user-defined
   functions. Prefer matching the existing side-effect policy and reject unsafe
   cases until deliberately supported.
4. Add semantic diagnostics for rejected drawing side effects in UDF contexts if
   needed.
5. Add fixtures for labels inside `if`, `switch`, `for`, `while`, and UDF
   callsites according to the supported policy.
6. Update `docs/REALTIME_MODEL.md` and execution semantics docs.

Exit criteria:

- Historical, incremental, and realtime label behavior agree for supported
  scenarios.
- UDF and control-flow side-effect boundaries are explicit and tested.
- Label support can be treated as a stable Phase E subfeature.

Verification:

```text
cargo test -p pine-runtime --test realtime
cargo test -p pine-sema label
cargo test -p pine-runtime label
cargo test --workspace
```

## Slice 7: Minimal `line.new` Snapshots

Goal: repeat the proven object pattern for line creation.

Initial scope:

- `line.new(x1, y1, x2, y2)` with bar-index and price coordinates.
- Common optional fields such as color, width, style, and extend only when
  fixture-backed.

Steps:

1. Add `Line` value kind and runtime value variant.
2. Add line snapshot structs, JSON serialization, Python conversion, and
   profile fields.
3. Add `line.new` signature and runtime creation behavior.
4. Keep unimplemented `line.*` methods unsupported.
5. Add runtime and golden snapshot fixtures for one line.
6. Update matrix notes so label and line support are described separately.

Exit criteria:

- `line.new` has deterministic ids and public snapshots.
- Label behavior and snapshots remain unchanged.
- Unimplemented line mutation/deletion methods remain diagnostic-only.

Verification:

```text
cargo test -p pine-sema line
cargo test -p pine-runtime line
cargo test -p pine-cli runtime_outputs_match_golden_snapshots
cargo test --workspace
```

## Slice 8: Line Mutation, Deletion, Limits, and Rollback

Goal: bring line lifecycle support up to the label lifecycle standard.

Steps:

1. Add selected `line.set_*` methods for endpoint, color, width, style, and
   extend fields.
2. Add `line.delete`.
3. Add line object limits and profile fields.
4. Add mutation, deletion, branch, loop, incremental, realtime, and limit
   fixtures.
5. Update docs and conformance metadata.

Exit criteria:

- Line creation, mutation, deletion, rollback, and limits are fixture-backed.
- Label and line object stores do not interfere with each other.
- Unsupported advanced line variants stay diagnostic-only.

Verification:

```text
cargo test -p pine-runtime line
cargo test -p pine-runtime --test incremental
cargo test -p pine-runtime --test realtime
cargo test --workspace
```

## Slice 9: Box Object Family

Goal: add boxes after label and line semantics have settled.

Steps:

1. Add `Box` value kind and runtime value variant.
2. Add box snapshot output and profile fields.
3. Implement a narrow `box.new` subset with left/top/right/bottom coordinates.
4. Add common `box.set_*` methods only after creation snapshots are stable.
5. Add `box.delete`, limits, incremental fixtures, and realtime rollback
   fixtures.
6. Keep text-heavy or renderer-specific box options unsupported until the schema
   can represent them cleanly.

Exit criteria:

- Box lifecycle behavior matches the object rules established by labels and
  lines.
- Public snapshots cover geometry, colors, and deletion.
- Unsupported box methods produce stable diagnostics.

Verification:

```text
cargo test -p pine-sema box
cargo test -p pine-runtime box
cargo test --workspace
```

## Slice 10: Table Object Family

Goal: support table ids and a small deterministic table-cell snapshot model.

Steps:

1. Design table snapshots separately from geometric object snapshots.
2. Add `Table` value kind and runtime value variant.
3. Implement a minimal `table.new` subset with deterministic dimensions and
   position constants.
4. Implement `table.cell` or a similarly narrow first cell-writing method.
5. Add cell mutation snapshots, table deletion or clearing behavior only when
   fixture-backed.
6. Add limits for table count and total cells.
7. Add public output, Python, WASM, snapshot, conformance, and realtime tests.

Exit criteria:

- Table output can represent cell values deterministically without host UI
  assumptions.
- Cell limits prevent unbounded memory growth.
- Unsupported table layout and styling variants are rejected precisely.

Verification:

```text
cargo test -p pine-sema table
cargo test -p pine-runtime table
cargo test --workspace
```

## Slice 11: Polyline Design Gate

Goal: decide whether polyline support belongs in Phase E closeout or should be
a documented maintenance tail.

Steps:

1. Review whether supported array semantics can safely carry point lists for
   `polyline.new`.
2. Define point value representation, snapshot size limits, and rollback
   behavior.
3. If the design is small, implement a minimal `polyline.new` subset with
   fixtures.
4. If the design depends on unsupported generic/object arrays, keep
   `polyline.*` unsupported and document the blocker in the Phase E audit.
5. Update conformance metadata either way.

Exit criteria:

- `polyline.*` is either fixture-backed as partial support or remains
  explicitly unsupported with a precise design blocker.
- Phase E closeout does not leave ambiguous polyline claims.

Verification:

```text
cargo test -p pine-sema polyline
cargo test -p pine-runtime polyline
cargo test --workspace
```

## Slice 12: Phase E Closeout

Goal: close the drawing-object platform phase with a clear audit trail.

Steps:

1. Add `docs/PHASE_E_AUDIT.md` summarizing supported object families, known
   gaps, public output schema version, and verification evidence.
2. Confirm `tests/fixtures/conformance.tsv` describes each object family at the
   correct granularity.
3. Refresh matrix and runtime golden snapshots after intentional public output
   changes.
4. Update release notes, architecture, conformance, realtime, and execution
   semantics docs.
5. Run `git diff --check` and `scripts/verify.sh`.
6. Record any maintenance tails without weakening supported-family claims.

Closeout checklist:

- Supported object families have creation, mutation, deletion, rollback, limit,
  incremental, and profile coverage.
- Unsupported object families or methods have stable diagnostics and fixtures.
- CLI JSON, WASM JSON, and Python dictionaries expose the same public drawing
  contract.
- Golden snapshots include at least one representative drawing output for every
  supported family.
- Conformance matrix rows cite fixture paths for every drawing claim.
- Public output schema versioning has been reviewed and documented.
- Object implementation modules remain split by responsibility; no new Phase E
   production file becomes a giant catch-all for object semantics.
- Any family-specific design notes are focused and linked from this playbook,
   not merged into an oversized omnibus document.

Verification:

```text
git diff --check
scripts/verify.sh
```

## Suggested Commit Order

1. `Add drawing output contract scaffold`
2. `Support minimal label creation`
3. `Cover label creation options`
4. `Support label mutation snapshots`
5. `Support label deletion and limits`
6. `Cover label realtime rollback`
7. `Support minimal line creation`
8. `Support line lifecycle snapshots`
9. `Support box lifecycle snapshots`
10. `Support minimal table snapshots`
11. `Resolve polyline compatibility boundary`
12. `Close Phase E audit`
