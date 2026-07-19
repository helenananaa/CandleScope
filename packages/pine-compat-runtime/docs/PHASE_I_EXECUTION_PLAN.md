# Phase I Execution Plan

Phase I adds `varip` and intrabar persistence after the realtime rollback model
is already fixture-backed for ordinary `var`, arrays, drawing outputs, callsite
state, and request provider data. Execute it in small, mergeable slices. Each
slice should leave the workspace shippable and should keep semantic claims,
runtime behavior, realtime fixtures, conformance metadata, and documentation in
lockstep.

`varip` is a runtime-state phase, not a public-output schema phase. It should
not add new JSON fields unless a later slice deliberately exposes new profile or
diagnostic metadata and updates snapshots in the same change.

## Current Starting Point

This is the repository state before Phase I starts:

- `tests/fixtures/conformance.tsv` marks `varip` as `unsupported` with the
  fixture `tests/fixtures/sema/unsupported_varip.pine`.
- `pine-syntax` already lexes and parses `varip` declarations as
  `DeclMode::Varip`.
- `pine-sema` rejects every `varip` declaration with
  `E_UNSUPPORTED_FEATURE` and the reason that intrabar persistence is not
  implemented.
- `pine-ir::HirSymbol` stores an optional `VarSlotId`, but it does not
  distinguish ordinary `var` persistence from `varip` persistence.
- `pine-runtime::HistoricalRuntime` stores ordinary `var` values in
  `var_store`, arrays in `array_store`, drawing objects in family output
  vectors, and stateful calls in separate callsite maps.
- `pine-runtime::RealtimeRuntime` handles rollback by cloning the confirmed
  `HistoricalRuntime` for each forming update. This is correct for rollback,
  but it does not preserve a separate intrabar store across repeated forming
  updates.
- CLI, Python, and WASM run historical chart data only. The Rust runtime owns
  the realtime update API that will show the first `varip`-specific behavior.

## Rules for Every Slice

- Add fixtures before or alongside behavior changes.
- Keep `varip` unsupported for any value family until its analysis, runtime
  persistence, realtime behavior, incremental behavior, docs, and conformance
  row all agree.
- Do not silently approximate intrabar behavior. If a subset behaves like
  ordinary `var` only in historical execution, document that exact boundary in
  conformance notes.
- Preserve ordinary rollback semantics for `var`, arrays, drawing objects,
  outputs, request caches, and callsite state while adding the `varip` escape
  path.
- Keep historical execution deterministic. Historical-only execution should have
  an explicit `varip` policy rather than a host-dependent behavior.
- Keep incremental append execution equivalent to full historical execution for
  historical fixtures.
- Keep runtime errors stable for unsupported `varip` value families, invalid
  object ids, or any intrabar storage limit failures.
- Update `tests/fixtures/conformance.tsv` only after a claimed subset has
  positive fixtures and the previous unsupported fixture no longer describes the
  whole feature.
- Run the full release verification gate before closing a slice that changes a
  compatibility claim.

## Internal Structure Rules

Phase I must preserve the internal restructuring baseline. Intrabar persistence
is a cross-cutting runtime concern, but it should still live behind small,
clear modules.

- Do not put persistence metadata, semantic checks, realtime handoff, array
  snapshotting, object-id policy, and fixture helpers into one large file.
- Keep `runtime/realtime.rs` focused on confirmed/forming state selection and
  intrabar handoff orchestration. It should not own declaration semantics or
  array cloning rules.
- Keep `runtime/historical.rs` as the bar execution orchestrator. If new fields
  or helper methods start to make it grow, move persistence behavior into a
  dedicated runtime module before adding another `varip` value family.
- Add a small runtime persistence module before the first behavior slice needs
  it. It should own persistent-slot reads/writes, confirmed versus intrabar
  store selection, and any cloning/checkpoint helpers.
- Keep semantic rules in `pine-sema` analyzer modules. Do not make the runtime
  discover unsupported `varip` declaration shapes that semantic analysis can
  reject earlier.
- Keep `pine-ir` limited to storage metadata. It should not contain runtime
  rollback rules.
- Keep Python and WASM bindings unchanged unless Phase I deliberately exposes a
  realtime host API later. Historical binding behavior should continue through
  the existing runtime helpers.
- Treat roughly 800 lines in a production Rust file as a review trigger. Split
  by responsibility before landing the next slice instead of letting one file
  become the new state-management monolith.
- Each slice should have an obvious review boundary: syntax/semantic metadata,
  runtime persistence, realtime handoff, array/object policies, fixtures, docs,
  and conformance metadata should be inspectable independently.

## Intended Module Layout

Use existing crate boundaries. Do not add a new crate for `varip`; it is part of
the core execution model.

Recommended layout:

```text
crates/pine-ir/src/lib.rs
   PersistenceKind or equivalent storage metadata on HIR symbols

crates/pine-sema/src/analyzer/
   statements.rs              varip declaration acceptance/rejection rules
   scopes.rs                  local declaration escape and side-effect policy reuse
   unsupported.rs             precise unsupported varip subset reasons

crates/pine-sema/src/lowering/
   mod.rs                     lower var/varip persistence metadata without runtime rules

crates/pine-runtime/src/runtime/
   persistence.rs             persistent slot reads/writes and varip store helpers
   historical.rs              owns stores and delegates persistence behavior
   statements.rs              declaration/reassignment dispatch through persistence helpers
   realtime.rs                confirmed/forming handoff and intrabar store carryover

crates/pine-runtime/src/builtins/
   arrays.rs                  array value-family integration only when Slice 4 starts
   drawings/                  object-id policy only when a later slice explicitly selects it
```

Ownership notes:

- `pine-ir` should expose whether a symbol is ordinary, `var`, or `varip` and
  which slot it uses. It should not know whether an update is historical,
  forming, or confirmed.
- `pine-sema` should allocate storage metadata and reject unsupported `varip`
  forms before lowering.
- `pine-runtime::runtime::persistence` should provide the one path for
  declaration initialization, reassignment persistence, and symbol reads that
  need persistent storage.
- `HistoricalRuntime` may own the concrete maps for confirmed and intrabar
  stores, but its statement evaluator should call helper methods rather than
  reaching into maps directly in many places.
- `RealtimeRuntime` should carry only the minimal intrabar state needed to seed
  the next forming update and commit the confirmed update.
- Array and drawing modules should own family-specific cloning or id-lifetime
  rules once those value families are selected. Do not hide those rules in
  generic scalar persistence helpers.

## Semantics Direction

Phase I should start with a narrow scalar subset and widen only after realtime
fixtures prove the handoff model.

Initial target behavior:

- A `varip` declaration initializes once when its declaration site is first
  reached, following the same declaration-site lifetime rules as local `var`.
- Historical execution treats `varip` like `var` because each bar has one
  committed evaluation and no repeated intrabar updates.
- Realtime forming updates seed ordinary runtime state from the last confirmed
  runtime, but seed `varip` values from the previous forming update for the
  same bar when one exists.
- A confirmed update commits the final `varip` values into the confirmed runtime
  so the next bar starts from the confirmed intrabar result.
- Ordinary `var`, output, array, drawing, request, and callsite rollback should
  continue to use the confirmed baseline unless a later slice explicitly widens
  the `varip` value family.

Initial value-family scope:

- Start with scalar `int`, `float`, `bool`, `string`, `color`, and `na` values.
- Keep scalar-array values out until Slice 4 defines how array ids and backing
  stores escape forming-bar rollback.
- Keep drawing object ids out until a later slice defines whether the object
  lifecycle itself is intrabar-persistent or only the id value is retained.
- Keep maps, matrices, UDTs, and imports out of Phase I unless a later phase
  implements those type systems first.

## How to Use the Acceptance Criteria

The exit criteria under each slice are local merge criteria for that slice.
Phase I should not be marked complete until the closeout checklist is done or a
remaining value family is explicitly moved to a documented Phase I maintenance
tail.

Maintenance tails must be narrow. They may keep object ids, future UDTs, maps,
or matrices out of scope, but they must not weaken these Phase I acceptance
criteria:

- Claimed `varip` subsets preserve values across repeated forming updates.
- Ordinary rollback behavior remains unchanged for non-`varip` state.
- Historical, incremental, and realtime fixtures describe the exact supported
  boundary.
- Unsupported `varip` value families produce stable diagnostics before runtime.

## Slice 1: Persistence Metadata Scaffold

Goal: add the internal metadata needed to distinguish `var` and `varip` without
changing the public compatibility claim yet.

Steps:

1. Add a small persistence metadata model in `pine-ir`, such as
   `PersistenceKind::{None, Var, Varip}` or an equivalent storage descriptor.
2. Thread that metadata through semantic symbol information and HIR lowering.
3. Keep `varip` declarations rejected in semantic analysis during this slice.
4. Add tests that prove ordinary `var` lowering and runtime behavior are
   unchanged.
5. Add or prepare a focused runtime persistence module, but do not move broad
   runtime behavior into it yet.
6. Keep the existing unsupported `varip` fixture and conformance row unchanged.

Exit criteria:

- `var` still allocates and lowers to the same persistent storage behavior.
- `varip` still reports the existing unsupported diagnostic.
- No public output, matrix, Python, or WASM behavior changes.
- The new metadata has an obvious owner and does not increase large-file
  pressure in runtime or semantic modules.

Verification:

```text
cargo test -p pine-sema var
cargo test -p pine-runtime var
cargo test --workspace
```

## Slice 2: Scalar Global `varip` Runtime

Goal: support the first useful `varip` subset: scalar global declarations with
historical behavior and realtime intrabar persistence.

Initial scope:

- Global `varip` declarations.
- Scalar values: `int`, `float`, `bool`, `string`, `color`, and `na`.
- Reassignment through the existing `:=` path.
- Historical, incremental append, and realtime forming updates.

Steps:

1. Stop rejecting global scalar `varip` declarations in semantic analysis.
2. Continue rejecting arrays, drawing ids, tuple declarations, and unsupported
   value families with a precise unsupported reason.
3. Lower accepted `varip` declarations with persistence metadata and a stable
   slot id.
4. Move declaration initialization and reassignment persistence through runtime
   helper methods so `var` and `varip` do not duplicate map logic.
5. Add an intrabar scalar store handoff in `RealtimeRuntime`:
   - first forming update for a bar seeds from confirmed runtime state
   - later forming updates for the same bar seed from previous forming `varip`
     state
   - confirmed update commits the resulting `varip` state into confirmed runtime
6. Add runtime tests where repeated forming updates increment a `varip` counter
   while ordinary `var` rolls back to the confirmed value.
7. Add historical fixtures showing that scalar `varip` behaves like `var` when
   there is only one committed evaluation per bar.
8. Update `tests/fixtures/conformance.tsv` from `unsupported` to `partial` with
   notes that name the scalar global subset and realtime persistence boundary.
9. Update `docs/EXECUTION_SEMANTICS.md`, `docs/LANGUAGE_SCOPE.md`, and release
   notes with the accepted subset.

Exit criteria:

- Repeated realtime forming updates preserve scalar `varip` state and continue
  rolling back ordinary `var` state.
- Historical and incremental execution agree for new scalar `varip` fixtures.
- Unsupported `varip` value families still fail during semantic analysis.
- The matrix claim is narrow and fixture-backed.

Verification:

```text
cargo test -p pine-sema varip
cargo test -p pine-runtime varip
cargo test -p pine-runtime --test realtime varip
cargo test -p pine-cli matrix
cargo test --workspace
```

## Slice 3: Local Scopes, Loops, and UDF Callsites

Goal: extend scalar `varip` from global declarations to the existing local
declaration-site model.

Initial scope:

- Block-local scalar `varip` declarations inside `if`, `for`, and `while`.
- Scalar `varip` declarations inside user-defined function bodies.
- Independent storage per lowered declaration site and UDF callsite, matching
  the existing local `var` behavior.

Steps:

1. Reuse the existing local declaration escape checks for `varip` symbols.
2. Ensure local `varip` declarations allocate declaration-site storage that is
   independent across loop bodies, block scopes, and UDF callsites.
3. Preserve parameter shadowing, tuple declaration shadowing, and loop counter
   shadowing behavior already covered for local declarations.
4. Add realtime fixtures for local scalar `varip` inside an executed branch, a
   skipped branch, a loop body, and two independent UDF callsites.
5. Add tests proving skipped branches do not initialize a `varip` declaration
   before its first executed reach.
6. Update conformance notes to mention local scalar declarations only after the
   fixtures exist.

Exit criteria:

- Local scalar `varip` follows declaration-site initialization rules.
- Repeated forming updates preserve local scalar `varip` state only for
  declaration sites that execute.
- UDF callsites do not share `varip` storage accidentally.
- Existing local `var`, loop, and UDF fixtures remain unchanged.

Verification:

```text
cargo test -p pine-sema varip
cargo test -p pine-runtime varip
cargo test -p pine-runtime runtime_control_flow
cargo test -p pine-runtime --test realtime
cargo test --workspace
```

## Slice 4: Scalar Array `varip` Values

Goal: support `varip` variables that hold current scalar typed-array ids only
after the backing store behavior is explicit.

Initial scope:

- Existing scalar typed-array families: float, int, bool, string, and color.
- `array.new_*`, `array.from`, `array.copy`, mutation helpers, and method calls
  already supported by the current array subset.
- Realtime persistence of both the array id value and the backing array contents
  referenced by accepted `varip` variables.

Steps:

1. Design the intrabar array-store boundary before changing semantic support.
   Decide whether `varip` arrays use a dedicated intrabar array store overlay or
   an explicit set of retained array ids copied between forming updates.
2. Keep non-`varip` arrays on the existing rollback path.
3. Accept scalar array value kinds in `varip` declarations only after the store
   handoff can preserve referenced backing arrays deterministically.
4. Add fixtures where repeated forming updates push into a `varip` array and an
   ordinary `var` array rolls back.
5. Cover `array.copy` boundaries so copied arrays do not accidentally alias
   retained intrabar state.
6. Cover local `varip` arrays in a branch and in a UDF callsite if those shapes
   are accepted.
7. Add runtime profile fields or profile tests only if the array handoff can
   grow storage in a new way.
8. Update the matrix notes from scalar-only to scalar plus scalar-array subset.

Exit criteria:

- `varip` array ids and backing contents persist across repeated forming
  updates for the claimed scalar array subset.
- Ordinary arrays still roll back between forming updates unless retained by a
  claimed `varip` path.
- Historical, incremental, and realtime fixtures cover array creation,
  mutation, copy, and local declaration behavior.
- Array storage limits remain deterministic.

Verification:

```text
cargo test -p pine-sema varip
cargo test -p pine-runtime arrays
cargo test -p pine-runtime --test realtime array
cargo test -p pine-runtime --test profile_fixtures
cargo test --workspace
```

## Slice 5: Drawing Id Boundary

Goal: decide and enforce the `varip` policy for drawing object ids without
creating dangling ids or hidden object-store persistence.

Recommended initial policy:

- Keep `varip` drawing id values unsupported until a focused design proves how
  label, line, box, and table lifecycles interact with intrabar persistence.
- Reject `varip` declarations whose inferred value kind is `Label`, `Line`,
  `Box`, or `Table` with a precise diagnostic.
- Keep `polyline.*` unsupported until polyline object state, snapshots, and
  lifecycle behavior are fixture-backed.

Steps:

1. Add semantic tests for `varip` declarations initialized from drawing object
   ids and from `na` values later reassigned to drawing ids if that flow can be
   detected.
2. Add runtime regression tests only if a drawing id can reach runtime through a
   supported scalar path.
3. Document why retaining only an id is insufficient if the referenced object
   store rolls back between forming updates.
4. If the project chooses to support object ids in this phase, split the work
   into one object family at a time and add object-store handoff tests before
   changing conformance metadata.
5. Keep conformance notes explicit: drawing ids unsupported, or named family
   subset supported with fixtures.

Exit criteria:

- No supported `varip` path can retain a dangling drawing object id.
- Unsupported drawing-id cases fail during semantic analysis when possible.
- Existing drawing rollback fixtures remain unchanged.
- Any future object-id support has family-specific realtime fixtures before it
  is claimed.

Verification:

```text
cargo test -p pine-sema varip
cargo test -p pine-runtime outputs
cargo test -p pine-runtime --test realtime
cargo test --workspace
```

## Slice 6: Host Surfaces, Docs, and Closeout

Goal: close Phase I for the claimed subset and record any remaining maintenance
tails.

Steps:

1. Review CLI, Python, and WASM behavior. Historical runs should accept the
   claimed `varip` subset through the existing compile/run paths without adding
   host-specific realtime APIs.
2. If a host binding exposes analysis output for `varip`, ensure diagnostics and
   compatibility reports match Rust analysis.
3. Update `docs/CONFORMANCE.md`, `docs/EXECUTION_SEMANTICS.md`,
   `docs/LANGUAGE_SCOPE.md`, `docs/REALTIME_MODEL.md`, and
   `docs/RELEASE_NOTES.md` for the final Phase I boundary.
4. Refresh `tests/snapshots/matrix.json` if the conformance matrix changes.
5. Add `docs/PHASE_I_AUDIT.md` summarizing completed slices, verification
   results, supported surface, and maintenance tails.
6. Keep object ids, maps, matrices, UDTs, imports, or other unimplemented value
   families as explicit maintenance tails rather than broadening the Phase I
   claim.
7. Run the canonical release gate before marking Phase I closed.

Exit criteria:

- The compatibility matrix describes the exact `varip` subset and cites fixture
  paths.
- Runtime tests cover historical, incremental, and realtime behavior for every
  claimed value family.
- Docs and release notes agree on unsupported tails.
- No public JSON output shape changed unintentionally.
- Phase I has a closeout audit with verification evidence.

Verification:

```text
git diff --check
cargo fmt --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cargo check -p pine-wasm --target wasm32-unknown-unknown
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/*.whl
python3 -m pytest python/tests
```

or, once prerequisites are installed:

```text
scripts/verify.sh
```

## Closeout Checklist

Phase I can be marked closed for its claimed subset when all of the following
are true:

- `varip` has semantic diagnostics for accepted and rejected value families.
- HIR storage metadata distinguishes ordinary `var` from `varip` without runtime
  modules guessing from syntax.
- Historical execution has a documented `varip` behavior.
- Realtime repeated forming updates preserve claimed `varip` state while
  ordinary rollback continues to work.
- Incremental append execution matches full historical execution for historical
  `varip` fixtures.
- Scalar and any claimed array/object-id subsets have runtime fixtures,
  realtime fixtures, conformance rows, and docs.
- Unsupported tails remain explicit in docs and diagnostics.
- No production Rust file grew into a new hotspot without being split by
  responsibility.
- `scripts/verify.sh` passes on the closeout workspace.
