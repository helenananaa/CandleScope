# Phase J Execution Plan

Status: archived. Phase J is closed for the fixture-backed claimed subset; see
`docs/PHASE_J_AUDIT.md` for the authoritative current support boundary,
verification evidence, and maintenance tails.

This document is the historical execution playbook that guided Phase J. Do not
use it as the next implementation plan. The repository has already advanced
past the original starting point: `import`, local user-defined types, and local
user-defined methods are now partial fixture-backed claims in
`tests/fixtures/conformance.tsv`.

Phase J adds libraries, imports, user-defined types, and non-array methods after
the indicator runtime has stable execution, public output contracts, drawing
snapshots, request-provider behavior, alert events, and intrabar persistence.
It was executed in small, mergeable slices. Each slice left the workspace
shippable and kept syntax, semantic analysis, source graph behavior, runtime
execution, fixtures, host APIs, conformance metadata, docs, and snapshots in
lockstep.

Phase J is a source-graph and type-system phase. It must not become a package
manager, network registry, or TradingView library mirror. Core crates remain
deterministic: hosts provide all source text, and the compiler/runtime only
parses, resolves, analyzes, lowers, caches, and executes that fixed source set.

The original execution started with Slice 0 only. Source graph plumbing,
host library-source inputs, and executable imports were intentionally delayed
until the unsupported Phase J families had stable diagnostics, negative
fixtures, conformance rows, and documentation.

## Original Starting Point

This was the repository state before Phase J started. It is preserved for audit
context and is not the current repository state:

- `tests/fixtures/conformance.tsv` marks `import` as `unsupported` with the
  fixture `tests/fixtures/sema/unsupported_import.pine`.
- `pine-syntax` lexes `import` and parses import lines as
  `StmtKind::Unsupported { feature: "import" }`.
- `pine-sema` reports `E_UNSUPPORTED_FEATURE` for unsupported import statements
  with the current "library imports" reason.
- `library`, `export`, user-defined `type`, and user-defined `method`
  declarations are not executable language constructs.
- User-defined functions exist for local source only. Expression-body and
  multi-statement block-body functions are supported, with recursive functions
  and side effects rejected.
- Method-call syntax exists only as a receiver rewrite for supported array
  methods. There is no general method declaration, receiver typing, or method
  dispatch table.
- The runtime has no module/source graph, no dependency cache key, and no
  cross-file diagnostic source mapping.
- CLI, Python, and WASM compile one script source at a time. They do not accept
  host-provided library sources.
- Public output schemas are not expected to change for the first Phase J
  slices. Any new diagnostic fields or host input shapes must be deliberately
  documented and tested.

## Rules for Every Slice

- Add fixtures before or alongside behavior changes.
- Keep unsupported Phase J variants diagnostic-only until syntax, semantic
  analysis, lowering, runtime behavior, host APIs, fixtures, conformance
  metadata, and docs agree.
- Do not mark `import`, `library`, user-defined types, or user-defined methods
  `partial` unless the exact claimed subset is fixture-backed.
- Core crates must not read arbitrary files, download sources, resolve remote
  libraries, or depend on a live clock. Hosts inject all library source text
  explicitly.
- Source identity must be deterministic. Every imported unit needs a stable
  source id, library key, or cache key that participates in diagnostics and
  analysis caching.
- Cross-file diagnostics must identify the originating source and span. Do not
  collapse imported-code failures into the main script span.
- Imported code must follow the same compatibility policy as local code:
  unsupported features remain rejected, side-effect rules remain explicit, and
  runtime behavior remains deterministic.
- Preserve existing UDF semantics while widening functions across files. Do not
  weaken recursive-function detection or function side-effect rejection.
- Keep public CLI, Python, and WASM host contracts synchronized for any new
  library-source injection shape. If one host remains unsupported for a slice,
  document it as a temporary diagnostic-only gap.
- Update `tests/fixtures/conformance.tsv` only after positive and negative
  fixtures exist for the claimed subset.
- Run the full release verification gate before closing a slice that changes a
  compatibility claim, public host contract, or public diagnostic shape.

## Internal Structure Rules

Phase J touches parser, semantic analysis, lowering, host APIs, and runtime
call dispatch. It should not turn existing hot files into catch-all source graph
or type-system modules.

- Add source-graph and library-owned modules before accepting imports. Do not
  bury dependency resolution in the CLI or ordinary analyzer entry point.
- Keep `pine-syntax` responsible for AST shape and source spans only. It should
  not resolve imports or validate host library availability.
- Keep `pine-sema` responsible for source graph analysis, export visibility,
  symbol binding, type declaration checks, method dispatch checks, side-effect
  policy, and cycle diagnostics.
- Keep `pine-ir` responsible for stable representation of imported functions,
  UDT field metadata, and method call targets if existing HIR cannot represent
  them.
- Keep `pine-runtime` responsible only for executing already-lowered programs.
  It should not perform import resolution or source lookup at runtime.
- Keep CLI, Python, and WASM bindings thin. They should map host-provided
  source dictionaries into a shared compile/analyze contract, not duplicate
  resolution or type logic.
- Treat roughly 800 lines in a production Rust file as a review trigger. Split
  by responsibility before landing another Phase J slice.
- Treat parser and call-analyzer growth as an immediate design constraint.
  Before adding structured Phase J declarations, review whether parser
  declaration/function/block parsing or parser tests should be split into
  focused modules. Before widening method dispatch, keep
  `pine-sema` call-analysis helpers small enough that array methods, UDT
  methods, and imported calls have separate ownership.
- Each slice should have an obvious review boundary: syntax, source graph,
  semantic binding, HIR/lowering, runtime dispatch, host APIs, fixtures, docs,
  and conformance metadata should be inspectable independently.

## Intended Module Layout

Use existing crate boundaries. Do not add a new crate unless a later review
proves source graph contracts must be shared without depending on `pine-sema`.

Recommended layout:

```text
crates/pine-syntax/src/
   ast.rs                     ImportDecl, LibraryDecl, ExportDecl, TypeDecl,
                                MethodDecl if/when each syntax is accepted
   lexer.rs                   library/export/type/method tokens as needed
   parser.rs                  parse accepted declarations and recover rejected
                                Phase J forms with stable spans

crates/pine-sema/src/
   source_graph.rs            source ids, library keys, dependency graph, cycle
                                and duplicate diagnostics
   modules.rs                 import aliases, export visibility, namespace
                                binding, cross-file symbol lookup
   user_types.rs              UDT declaration, constructors, field access, and
                                field mutation checks
   methods.rs                 user method registration, receiver binding, and
                                method call resolution
   analyzer/
      unsupported.rs          unsupported Phase J variants and precise reasons
      functions.rs            imported function and method side-effect policy
      calls.rs                delegate method/import-aware calls before generic
                                built-in handling

crates/pine-ir/src/
   lib.rs                     optional source/function ids, UDT metadata,
                                method target ids, and field access nodes

crates/pine-runtime/src/
   runtime/
      calls.rs                imported function and method call dispatch only
      expressions.rs          UDT construction/field access if lowered as
                                runtime expressions
   value.rs                   UDT value representation only after Slice 6

crates/pine-cli/src/commands/
   analyze.rs                 host library source injection for analysis
   run.rs                     host library source injection for runtime

crates/pine-python/src/
   lib.rs                     library source dictionary host injection

crates/pine-wasm/src/
   lib.rs                     deterministic JSON library source input or a
                                documented temporary diagnostic gap
```

Ownership notes:

- Source graph modules own dependency ordering and cycle detection. They should
  not execute or lower functions.
- Module/export modules own import aliases and exported symbol visibility. They
  should not know runtime storage layout.
- UDT modules own field names, field types, constructors, and field mutation
  rules. They should not own import resolution.
- Method modules own receiver binding and method target resolution. Array
  method rewrites should keep working through the existing array path until a
  deliberate unification slice replaces it.
- Runtime value and call modules should receive resolved/lowered targets. They
  should not search source graphs by name during execution.

## Source and Host Contract Direction

Start with explicit host-provided library sources and widen only after fixtures
prove deterministic analysis and execution.

Initial host contract direction:

- The main script is still the root program.
- Hosts provide zero or more library sources keyed by an import key string.
- No network fetching, filesystem search path, package registry, automatic
  version discovery, or current-user library lookup is allowed in core crates.
- Missing libraries, duplicate keys, invalid keys, import cycles, and duplicate
  aliases are stable analysis errors.
- Imported source diagnostics preserve imported source identity and spans.
- The first executable import subset should use pure exported functions and
  constants only.

Initial source identity rules:

- A source id must be stable for a fixed host input set.
- Import keys should be normalized before graph resolution.
- Cache keys must include the root source and every imported source that can
  affect analysis or runtime output.
- Repeated imports of the same library key should share one analyzed library
  unit for a compilation.

Out of initial scope unless a later slice explicitly adds it:

- Remote library discovery or authentication.
- TradingView account/library namespaces beyond a deterministic key parser.
- Semantic version solving beyond exact host-provided keys.
- Re-export chains.
- Partial compilation against missing libraries.
- Mutable global state shared across imported libraries unless a slice designs
  lifetime, rollback, and side-effect semantics.
- Strategy libraries; strategy runtime belongs to Phase G.

## Semantics Direction

Phase J should start with imports that do not change runtime state rules.

Initial import subset:

- `import key as alias` or the smallest syntax-compatible alias form selected
  by Slice 2.
- A library unit may export pure constants and pure functions.
- Imported functions are called through an alias-qualified name such as
  `alias.fn(...)`.
- Exported functions follow existing UDF rules: no recursion, no unsupported
  side effects, no output/drawing/alert/input declarations in function bodies,
  and no array mutation in UDF bodies until a later side-effect design changes
  that policy.
- Imported functions execute with independent callsite state per callsite in
  the root program, matching existing local UDF callsite behavior.
- Exported constants must be immutable and analyzable before runtime.

Initial UDT subset:

- Prefer UDT declarations without imports first.
- Start with record-like scalar fields and a constructor expression.
- Field access is read-only until field mutation semantics are designed.
- Keep UDT arrays, UDT history references, object fields, recursive UDTs,
  methods with side effects, maps, matrices, and imported UDT identity out of
  the first UDT slice unless explicitly selected.

Initial method subset:

- Start with user-defined methods on the first supported UDT value family.
- Treat the receiver as an explicit first parameter in semantic analysis and
  lowering, but preserve method-call syntax in spans and diagnostics.
- Do not unify user-defined methods with drawing object methods or array method
  internals until receiver typing and method dispatch are stable.

## How to Use the Acceptance Criteria

The exit criteria under each slice are local merge criteria for that slice.
Phase J should not be marked complete until the closeout checklist is done or a
remaining Phase J feature is explicitly moved to a documented maintenance tail.

Maintenance tails must be narrow. They may keep remote registries, re-exports,
advanced UDTs, imported UDT identity, side-effecting library functions, or
strategy libraries out of scope, but they must not weaken these Phase J
acceptance criteria:

- Claimed import/library surfaces have deterministic source graph behavior.
- Imported diagnostics preserve source identity and stable spans.
- Imported functions and methods obey the same runtime, rollback, and
  side-effect rules as local code.
- UDT values have explicit construction, field access, persistence, history,
  and rollback boundaries before support is claimed.
- Unsupported Phase J variants produce stable diagnostics before runtime when
  possible.

## Slice 0: Phase J Boundary and Diagnostic Inventory

Status: completed by `614cd37 Document Phase J unsupported boundaries`.

Goal: document and fixture the unsupported Phase J boundary before accepting
new syntax, source graph behavior, host-source inputs, or executable imports.

Steps:

1. Inventory the existing parser, analyzer, conformance, and docs entries for
   imports, libraries, UDTs, and non-array methods.
2. Add or update negative fixtures for unsupported forms that Phase J will
   eventually widen:
   - `import`
   - `library`
   - `export`
   - user-defined `type`
   - user-defined `method`
   - non-array method calls on unsupported receivers
3. Normalize `library`, `export`, user-defined `type`, and user-defined
   `method` failures to `E_UNSUPPORTED_FEATURE` through either parser recovery
   or semantic analysis. A full AST design is not required in Slice 0, but the
   diagnostic code, message, feature id, and span must be stable.
4. Decide the non-array method boundary explicitly:
   - If non-array method calls are treated as Phase J unsupported features, add
     a compatibility unsupported entry and fixture.
   - If they remain ordinary receiver/type diagnostics for now, document that
     they are not yet a matrix feature row and keep the diagnostic stable.
5. Add or update `tests/fixtures/conformance.tsv` rows for these Phase J
   families as `unsupported`, each backed by sema negative fixtures:
   - `library`
   - `export`
   - `user-defined types`
   - `user-defined methods`
   - `non-array methods`, if selected in Step 4
6. Keep `import` unsupported and backed by the existing or updated
   `unsupported_import` fixture.
7. Add semantic tests that assert stable diagnostics for unsupported Phase J
   forms.
8. Update `docs/LANGUAGE_SCOPE.md`, `docs/SEMANTIC_MODEL.md`, and release notes
   with the selected Phase J starting boundary.
9. Confirm README and the long-term plan link to this execution plan and agreed
   that the next implementation target was Slice 0 at the original Phase J
   start.

Exit criteria:

- The repository has explicit unsupported fixtures for every major Phase J
  family.
- The compatibility matrix has unsupported rows for selected Phase J families,
  and every row cites an existing sema fixture.
- `library`, `export`, user-defined `type`, and user-defined `method` no
  longer fall through to unrelated unknown-function, unknown-symbol, or parser
  diagnostics.
- Existing import unsupported behavior remains stable or improves only by
  tightening the same unsupported-feature boundary.
- No executable import, library, UDT, or user-defined method support is claimed.
- README and long-term planning docs linked to this playbook and did not imply
  that Slice 1 or executable imports should start before Slice 0 closed.
- The next implementation slice could safely change one boundary without
  accidentally widening another.

Verification:

```text
cargo test -p pine-syntax import
cargo test -p pine-sema unsupported
cargo test -p pine-cli matrix
cargo run -p pine-cli -- matrix
cargo test --workspace
```

## Slice 1: Source Graph and Library Host Contract Scaffold

Status: completed by `d2c7321 Add Phase J source graph scaffold`.

Goal: add deterministic source graph data structures and host-source contracts
without accepting imports.

Steps:

1. Add a small source identity model: root source id, library source id, import
   key, and display name for diagnostics.
2. Add a shared analysis input model, such as `AnalysisInput`, that carries the
   root source plus an optional host-provided library source map. Route CLI,
   Python, and WASM through this shared shape before adding host-specific
   parsing logic.
3. Add a source graph builder that accepts a root source and a host-provided
   map of library sources, but returns an empty graph while imports remain
   unsupported.
4. Add stable diagnostics for duplicate library keys, invalid import keys, and
   missing host-provided sources once import syntax starts using the graph.
5. Decide the first host input shape:
   - CLI: repeated `--library-source KEY=path.pine` or an equivalent explicit
     option.
   - Python: `library_sources={"KEY": "source text"}`.
   - WASM: deterministic JSON object input or a documented temporary gap.
6. Add host-surface parsing tests without enabling imported execution.
7. Ensure cache keys or analysis inputs include library source text once the
   source graph is used.
8. Keep `tests/fixtures/conformance.tsv` unchanged.
9. Document the source graph contract in `docs/ARCHITECTURE.md` and
   `docs/CONFORMANCE.md`.

Exit criteria:

- Hosts can pass library source text into analysis/run entry points or have a
  documented temporary diagnostic gap.
- CLI, Python, and WASM share one analysis input/source-map contract instead of
  duplicating library-source map semantics in each host.
- Core crates still perform no filesystem, network, or clock I/O for library
  resolution.
- Import statements still report unsupported diagnostics.
- The source graph model has stable source ids and room for cross-file spans.

Verification:

```text
cargo test -p pine-sema source_graph
cargo test -p pine-cli library
cargo test -p pine-wasm
python3 -m pytest python/tests
cargo test --workspace
```

## Slice 2: Parse Library, Export, and Import Declarations

Status: completed by `5d5d7ed Parse Phase J declarations structurally`.

Goal: represent Phase J declarations in the AST with stable spans while keeping
them diagnostic-only.

Steps:

1. Add tokens for the selected `library`, `export`, `type`, and `method`
   syntax only when a parser slice needs them.
2. Replace `import` unsupported-line parsing with a structured import AST node
   that records the import key and alias.
3. Parse `library(...)` declarations as a top-level program declaration or as a
   statement shape consistent with existing `indicator(...)` handling.
4. Parse `export` modifiers on functions and constants without exposing them to
   root scripts yet.
5. Keep unsupported or ambiguous declaration forms as stable syntax or semantic
   diagnostics rather than parser panics.
6. Add parser fixtures for valid import/library/export shapes and malformed
   recovery.
7. Keep semantic analysis rejecting all Phase J declarations during this slice.
8. Keep conformance metadata unchanged.

Exit criteria:

- The parser can preserve spans for import keys, aliases, library declarations,
  and export modifiers.
- Unsupported Phase J declarations report stable diagnostics after parsing.
- Existing scripts and unsupported import fixtures behave the same externally.
- No runtime behavior changes.

Verification:

```text
cargo test -p pine-syntax import
cargo test -p pine-syntax library
cargo test -p pine-syntax export
cargo test -p pine-sema unsupported
cargo test --workspace
```

## Slice 3: Module Resolution and Export Visibility

Status: completed by `d088977 Validate Phase J module graph`.

Goal: resolve imports against host-provided source graph data while keeping
imported execution disabled.

Steps:

1. Use the source graph builder from Slice 1 to load imported library units from
   explicit host-provided sources.
2. Detect missing libraries, duplicate aliases, duplicate exports, invalid
   library declarations, and dependency cycles.
3. Analyze imported libraries in dependency order without adding their symbols
   to the root scope unless imported through an alias.
4. Add an alias namespace model so `alias.name` can refer to exported library
   symbols without colliding with built-in namespaces or root symbols.
5. Preserve cross-file diagnostic source ids and spans.
6. Keep imported symbols unusable at runtime until Slice 4 selects the first
   executable subset.
7. Add tests for missing library source, duplicate alias, import cycle, unknown
   export, and private symbol access.
8. Keep `import` conformance unsupported until a positive executable subset
   exists.

Exit criteria:

- The analyzer can build and validate a deterministic source graph.
- Unsupported imported execution still fails before runtime.
- Diagnostics point at the root import span or imported source span as
  appropriate.
- Built-in namespace resolution and array method calls remain unchanged.

Verification:

```text
cargo test -p pine-sema source_graph
cargo test -p pine-sema import
cargo test -p pine-sema scopes
cargo test --workspace
```

## Slice 4: Exported Constants and Pure Imported Functions

Status: completed by `7417bb1 Support pure Phase J imports`.

Goal: support the first executable import subset without introducing new
runtime state semantics.

Initial scope:

- Host-provided library source.
- Exact-key import with alias.
- Exported immutable constants.
- Exported pure functions using the existing UDF expression/block-body subset.
- Alias-qualified calls from the root script.

Steps:

1. Accept import declarations only when the target library source is provided by
   the host and passes module validation.
2. Accept exported constants whose values are compatible with existing const or
   simple expression rules.
3. Accept exported functions that satisfy existing UDF restrictions.
4. Reject exported functions with output, drawing, alert, input declaration,
   array mutation, request side effects, or other unsupported side effects.
5. Reject recursive calls across the source graph, including mutual recursion
   between root and imported functions.
6. Lower imported functions with stable source/function ids and alias-qualified
   call targets.
7. Preserve independent callsite state for imported function calls in the root
   script.
8. Add runtime fixtures for imported constants, imported pure functions,
   imported functions with stateful built-ins, branch-skipped imported calls,
   and repeated imports of the same source.
9. Add negative fixtures for private symbol access, missing export, recursion,
   and side effects in exported functions.
10. Update `tests/fixtures/conformance.tsv` for `import` from `unsupported` to
    `partial` only after positive runtime fixtures and negative semantic
    fixtures exist.
11. Update docs and release notes with the exact imported-function subset.

Exit criteria:

- Root scripts can call fixture-backed pure imported functions through an alias.
- Imported calls participate in historical and incremental execution with the
  same result as full historical execution.
- Imported stateful callsites do not share state accidentally across callsites
  or aliases.
- Unsupported imported side effects and recursion fail during analysis.
- CLI, Python, and WASM host contracts are synchronized or documented with a
  temporary gap.
- Matrix notes name the exact import subset and cite library fixtures.

Verification:

```text
cargo test -p pine-sema import
cargo test -p pine-runtime import
cargo test -p pine-runtime --test incremental
cargo test -p pine-cli matrix
cargo test --workspace
```

## Slice 5: Cross-Host Library Source Injection

Status: completed by `56d7284 Expose Phase J import host inputs`.

Goal: make the imported-function subset usable through CLI, Python, and WASM
without duplicating source graph logic.

Steps:

1. Finalize CLI host input for library sources and add integration fixtures.
2. Add Python compile/analyze/run inputs for library source dictionaries.
3. Add WASM compile/analyze/run inputs for deterministic library source JSON,
   or keep WASM provider injection diagnostic-only with a documented reason.
4. Ensure all hosts pass the same root source and library map into the shared
   analysis path.
5. Add public tests that assert equivalent imported-function results across
   supported hosts.
6. Add diagnostic tests for missing libraries and malformed library input at
   each supported host boundary.
7. Document host contract examples in README and `docs/ARCHITECTURE.md`.
8. Refresh snapshots only if public analysis or runtime output shape changes.

Exit criteria:

- Supported hosts expose the same imported-function behavior and diagnostics.
- Any host gap is explicit, tested, and documented as temporary.
- Source graph logic remains in shared crates, not host bindings.
- No public output field changes occur unless snapshot-backed.

Verification:

```text
cargo test -p pine-cli library
cargo test -p pine-wasm library
maturin build --manifest-path crates/pine-python/Cargo.toml --out dist
python3 -m pip install --force-reinstall dist/*.whl
python3 -m pytest python/tests
cargo test --workspace
```

## Slice 6: User-Defined Type Syntax and Scalar Constructors

Status: completed by `1850dda Support local scalar UDTs`.

Goal: add the first local UDT subset without imports or methods.

Initial scope:

- Local top-level `type` declarations.
- Record-like scalar fields.
- Constructor calls for UDT values.
- Field reads.
- No field mutation, history references, arrays of UDTs, object fields,
  recursive UDTs, imported UDTs, or methods yet.

Steps:

1. Parse top-level UDT declarations with field names, field types, defaults if
   selected, and stable spans.
2. Add semantic validation for duplicate fields, unknown field types,
   recursive type definitions, unsupported field families, and invalid
   declaration locations.
3. Add a UDT type identity model in semantic analysis.
4. Add HIR/runtime representation for scalar-field UDT values or a lowering
   strategy that keeps field values explicit.
5. Add constructor call analysis and runtime construction.
6. Add field read analysis and runtime evaluation.
7. Keep field mutation rejected with a precise diagnostic.
8. Add runtime fixtures for construction, field reads, branch-local values,
   UDF parameters/returns if selected, and `na` boundaries if selected.
9. Add negative fixtures for recursive UDTs, unsupported field kinds, unknown
   fields, duplicate fields, and invalid constructors.
10. Add a `user-defined types` conformance row as `partial` only after fixtures
    exist.
11. Update docs and release notes with the exact local UDT subset.

Exit criteria:

- Local scalar-field UDT values can be constructed and read deterministically.
- Unsupported UDT forms fail during semantic analysis.
- UDT values do not accidentally bypass existing side-effect or persistence
  rules.
- Runtime, incremental, and docs agree on the claimed local UDT subset.

Verification:

```text
cargo test -p pine-syntax type
cargo test -p pine-sema user_types
cargo test -p pine-runtime user_types
cargo test -p pine-runtime --test incremental
cargo test --workspace
```

## Slice 7: UDT Persistence, History, and Field Mutation Boundary

Status: completed by `1bcf60d Define UDT persistence boundary`.

Goal: decide how UDT values interact with existing series, `var`, `varip`, and
rollback semantics before broadening UDT claims.

Steps:

1. Audit the Slice 6 implementation against existing `Value`, `SeriesStore`,
   `var_store`, `varip`, incremental append, and realtime rollback behavior.
2. Decide whether UDT values may be stored in ordinary variables only, `var`,
   `varip`, history references, arrays, or UDF callsite state.
3. Add fixtures for every accepted storage/persistence form.
4. Keep unaccepted forms rejected with precise diagnostics.
5. If field mutation is accepted, define whether it mutates a value copy or a
   reference-like object, then add rollback and incremental fixtures before
   claiming it.
6. If field mutation is deferred, document UDTs as immutable values for the
   current subset.
7. Update conformance notes and docs with the exact storage boundary.

Exit criteria:

- UDT storage semantics are explicit and fixture-backed.
- Realtime rollback and `varip` behavior for accepted UDT forms is tested or
  explicitly unsupported.
- Field mutation is either supported with deterministic copy/reference
  semantics or rejected with stable diagnostics.
- Existing scalar, array, drawing, alert, and request behavior remains
  unchanged.

Verification:

```text
cargo test -p pine-runtime user_types
cargo test -p pine-runtime --test realtime user_types
cargo test -p pine-runtime --test incremental
cargo test --workspace
```

## Slice 8: User-Defined Methods on Local UDTs

Status: completed by `4e870cf Support UDT methods`.

Goal: support the first non-array user-defined method subset after UDT receiver
typing is stable.

Initial scope:

- Methods declared for the supported local UDT subset.
- Receiver passed as an explicit first parameter internally.
- Method calls on local UDT values.
- Pure method bodies following existing UDF restrictions.

Steps:

1. Parse the selected method declaration syntax and preserve receiver spans.
2. Register methods in a method table keyed by receiver type and method name.
3. Reject duplicate methods, unknown receiver types, unsupported receiver
   qualifiers, and ambiguous method names.
4. Resolve `value.method(args...)` for UDT receivers before falling back to
   existing array method handling.
5. Lower method calls to a stable function/method target with receiver as the
   first argument.
6. Reuse existing UDF side-effect and recursion checks for method bodies,
   including mutual recursion between functions and methods.
7. Add runtime fixtures for pure methods, methods called in branches/loops,
   stateful built-ins inside method bodies if accepted, and skipped branch
   behavior.
8. Add negative fixtures for side-effecting methods, unknown methods, duplicate
   methods, wrong receiver types, and recursion.
9. Add or update conformance rows for `user-defined methods` and keep `array
   method calls` notes unchanged unless deliberately modified.
10. Update docs and release notes.

Exit criteria:

- UDT method calls are resolved by receiver type, not by stringly namespace
  guessing.
- Existing array method calls still work and retain their conformance notes.
- Method callsite state is deterministic and does not accidentally share state
  across receivers or callsites.
- Unsupported method forms fail during semantic analysis.

Verification:

```text
cargo test -p pine-syntax method
cargo test -p pine-sema methods
cargo test -p pine-runtime methods
cargo test -p pine-runtime --test incremental
cargo test --workspace
```

## Slice 9: Imported UDTs and Methods

Status: completed by `5b8aa1d Lock imported UDT method boundary`.
Imported UDT identity and imported methods were kept as explicit maintenance
tails rather than added to the Phase J support claim.

Goal: combine the imported-function and local-UDT subsets only after both are
stable independently.

Steps:

1. Decide whether exported UDTs are part of the Phase J claim or remain a
   maintenance tail.
2. If accepted, give exported UDTs stable type identity across the source graph
   and aliases.
3. Allow imported constructors, field reads, and pure methods only for the UDT
   subset already supported locally.
4. Reject private UDTs, private methods, type identity mismatches, cycles, and
   unsupported field/method forms.
5. Add fixtures for imported UDT construction, imported methods, alias-qualified
   type names, duplicate imported names, and cross-file diagnostics.
6. Add host-surface tests for imported UDTs in every supported host.
7. Update conformance notes only after fixtures cover cross-file type identity
   and method dispatch.

Exit criteria:

- Imported UDT identity is deterministic and source-graph scoped.
- Imported methods obey the same side-effect, recursion, and callsite-state
  rules as local methods.
- Cross-file UDT diagnostics preserve source identity.
- Unsupported imported UDT variants are diagnostic-only.

Verification:

```text
cargo test -p pine-sema import
cargo test -p pine-sema user_types
cargo test -p pine-sema methods
cargo test -p pine-runtime import
cargo test -p pine-runtime user_types
cargo test --workspace
```

## Slice 10: Closeout Audit and Roadmap Alignment

Status: completed by `a7e7d81 Close Phase J audit`.

Goal: close Phase J for the claimed subset and record remaining maintenance
tails.

Steps:

1. Review `tests/fixtures/conformance.tsv` against the actual implemented
   Phase J surface.
2. Run `cargo run -p pine-cli -- matrix` and confirm matrix notes describe only
   fixture-backed claims.
3. Review CLI, Python, and WASM host contracts for library source injection and
   documented gaps.
4. Review cross-file diagnostics for source ids, spans, and stable error codes.
5. Update `docs/CONFORMANCE.md`, `docs/LANGUAGE_SCOPE.md`,
   `docs/SEMANTIC_MODEL.md`, `docs/EXECUTION_SEMANTICS.md`,
   `docs/ARCHITECTURE.md`, `docs/RELEASE_NOTES.md`, and README.
6. Add `docs/PHASE_J_AUDIT.md` summarizing completed slices, supported surface,
   host contracts, diagnostic behavior, verification results, and maintenance
   tails.
7. Move any unfinished remote registry, re-export, advanced UDT, method,
   library side-effect, or strategy-library work into explicit maintenance
   tails.
8. Update `docs/LONG_TERM_EXECUTION_PLAN.md` so the next recommended phase is
   no longer stale.
9. Run the canonical release gate before marking Phase J closed.

Exit criteria:

- Compatibility matrix, README, long-term plan, conformance docs, and release
  notes agree on Phase J support and unsupported tails.
- Every supported Phase J feature has syntax/semantic/runtime/host fixtures
  appropriate to the claim.
- Unsupported Phase J variants have stable diagnostics and fixture coverage.
- Phase J has a closeout audit with verification evidence.
- No production Rust file crosses the structural guardrail because of Phase J
  work.

Verification:

```text
git diff --check
scripts/verify.sh
```

## Closeout Checklist

- Source graph behavior is deterministic and host-provided only.
- Import/library support has positive runtime fixtures and negative diagnostic
  fixtures for its exact claimed subset.
- Cross-file diagnostics preserve source identity and spans.
- CLI, Python, and WASM host contracts are synchronized or documented with
  tested temporary gaps.
- Imported functions obey local UDF side-effect, recursion, and callsite-state
  rules.
- UDT construction, field access, persistence, history, rollback, and mutation
  boundaries are explicit and fixture-backed.
- User-defined method resolution is receiver-typed and does not regress array
  method syntax.
- Matrix rows prevent accidental widening of import, UDT, or method claims.
- Docs and release notes record unsupported tails.
- Phase J audit records completed slices, verification command results,
  supported surface, and maintenance tails.

## Actual Commit Order

1. `Document Phase J unsupported boundaries`
2. `Add source graph contract scaffold`
3. `Parse Phase J declarations`
4. `Validate Phase J module graph`
5. `Support pure Phase J imports`
6. `Expose library source host inputs`
7. `Support local scalar UDTs`
8. `Define UDT persistence boundary`
9. `Support UDT methods`
10. `Lock imported UDT method boundary`
11. `Close Phase J audit`
