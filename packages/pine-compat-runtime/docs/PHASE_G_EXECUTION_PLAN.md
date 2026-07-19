# Phase G Execution Plan

Phase G adds strategy runtime support as a separate execution mode. Execute it
in small, mergeable slices. Each slice should leave the workspace shippable and
should keep semantic claims, broker behavior, public output contracts, fixtures,
snapshots, host APIs, and conformance metadata in lockstep.

Strategy support is not a built-in-only phase. `strategy.*` calls place orders
against a deterministic broker emulator, and strategy scripts produce a distinct
runtime result family. Indicator execution must remain unchanged unless a slice
explicitly updates a shared public contract and refreshes the corresponding
tests and snapshots.

## Current Starting Point

This is the repository state before Phase G starts:

- `tests/fixtures/conformance.tsv` marks `strategy.*` as `unsupported` with the
  fixture `tests/fixtures/sema/unsupported_strategy.pine`.
- At Phase G start, `pine-sema` rejected `strategy.*` calls through the
  unsupported-feature path. Slice 0 normalizes the bare `strategy(...)`
  declaration to the same diagnostic family before Slice 1 promotes the
  declaration itself to a narrow partial feature.
- `pine-builtins` registers `indicator(...)` as the supported script declaration
  builtin. It does not register `strategy(...)` or strategy order functions.
- Syntax fixtures overwhelmingly use `indicator(...)`; the existing strategy
  fixture calls `strategy.close("L")` from an indicator script only to preserve
  the unsupported diagnostic.
- `pine-runtime` executes indicator-style historical and realtime bar streams.
  It has no broker state, order book, position model, trade ledger, equity
  curve, or strategy-specific runtime mode.
- CLI, Python, and WASM public run entry points return indicator runtime output
  with plots, alerts, drawing snapshots, diagnostics, and no strategy result
  family.
- Golden runtime snapshots cover the current public output schema. Adding
  strategy output is a consumer-visible contract change and must be deliberate.

## Rules for Every Slice

- Add fixtures before or alongside behavior changes.
- Keep unsupported strategy variants diagnostic-only until declaration syntax,
  semantic analysis, broker behavior, public output shape, host APIs,
  conformance metadata, and docs agree.
- Do not mark `strategy.*` `partial` or `supported` unless the exact claimed
  subset is backed by positive runtime fixtures and negative semantic fixtures.
- Preserve indicator execution. Indicator scripts must not see strategy output
  fields or broker side effects unless a slice intentionally changes the shared
  runtime contract.
- Treat broker emulation as deterministic runtime behavior. Core crates must
  not depend on wall-clock time, network services, account state, or host-side
  mutable callbacks.
- Keep order fill rules explicit and narrow. Do not approximate TradingView
  behavior silently when a fill, pyramiding, commission, slippage, margin, or
  quantity rule has not been designed.
- Separate strategy declaration support from order function support. Accepting
  `strategy(...)` should not imply that `strategy.entry`, `strategy.exit`,
  `strategy.order`, `strategy.close`, or reporting variables are executable.
- Keep CLI, Python, and WASM host contracts synchronized for any new strategy
  output fields or strategy run mode. If one host remains diagnostic-only for a
  slice, document that temporary gap and add a test.
- Update public schema constants and golden snapshots in the same change as any
  new machine-readable strategy output shape.
- Preserve historical, incremental append, and realtime rollback guarantees for
  indicator scripts. Strategy realtime behavior should remain unsupported until
  a slice defines broker handoff semantics for forming bars.
- Update `tests/fixtures/conformance.tsv` only after the claimed strategy subset
  has fixture coverage.
- Run the full release verification gate before closing a slice that changes a
  compatibility claim, public output contract, or public host contract.

## Internal Structure Rules

Phase G adds a broker subsystem. It should not turn existing runtime, output, or
semantic files into strategy catch-all modules.

- Add strategy-owned modules before accepting executable order functions.
- Keep `pine-builtins` responsible for strategy declaration and order-function
  signatures, not broker state or fill rules.
- Keep `pine-sema` responsible for strategy-mode gating, unsupported strategy
  variants, argument checks, and side-effect restrictions.
- Keep `pine-runtime::strategy` responsible for broker state, orders,
  positions, trades, equity accounting, and deterministic fill policy.
- Keep `pine-runtime::output` responsible for public strategy result structs and
  JSON serialization.
- Keep `runtime/historical.rs` as orchestration. It may choose indicator versus
  strategy execution, but broker mutation should be delegated.
- Keep Python and WASM bindings thin. They should map the shared strategy result
  model rather than duplicating broker semantics.
- Treat roughly 800 lines in a production Rust file as a review trigger. Split
  by responsibility before adding another order function or accounting rule.
- Each slice should have an obvious review boundary: signatures, semantic mode
  checks, broker state, runtime dispatch, output serialization, host APIs,
  fixtures, docs, and conformance metadata should be inspectable independently.

## Intended Module Layout

Use existing crate boundaries. Do not add a new crate unless a later review
proves that broker contracts must be shared outside `pine-runtime` without
pulling runtime dependencies.

Recommended layout:

```text
crates/pine-builtins/src/
   namespaces/strategy.rs       strategy declaration and supported strategy.* signatures
   namespaces/mod.rs            strategy namespace export once accepted
   registry.rs                  include strategy signatures only for accepted slices

crates/pine-sema/src/analyzer/
   strategy.rs                  strategy declaration checks, mode gating,
                                  order-call argument validation
   calls.rs                     delegate strategy calls before generic built-in handling
   unsupported.rs               unsupported strategy variants and precise diagnostics

crates/pine-ir/src/
   lib.rs                       optional script mode metadata and strategy call markers

crates/pine-runtime/src/
   strategy/
      mod.rs                    broker subsystem facade and re-exports
      model.rs                  orders, fills, positions, trades, equity snapshots
      broker.rs                 deterministic broker state transitions
      fills.rs                  bar-close or OHLC fill policy helpers
      limits.rs                 pyramiding and quantity guard helpers
      report.rs                 strategy result assembly
   output/
      strategy.rs               public strategy output model
      json.rs                   shared public runtime JSON output
   builtins/
      strategy.rs               runtime dispatch for accepted strategy calls
   runtime/
      historical.rs             strategy runtime mode orchestration only

crates/pine-cli/src/commands/
   run.rs                       strategy-capable run path or explicit diagnostic gap

crates/pine-python/src/
   lib.rs                       map shared strategy results into dictionaries

crates/pine-wasm/src/
   lib.rs                       return shared strategy JSON or documented diagnostic gap
```

Ownership notes:

- `pine-ir` should know whether a program is an indicator or strategy only if
  runtime dispatch needs that metadata after lowering. It should not contain
  broker rules.
- `pine-sema` should reject strategy order calls in indicator scripts before
  runtime.
- `pine-runtime::strategy` should own accounting and fill rules. Output modules
  should only serialize the resulting public model.
- Strategy execution may reuse expression, statement, series, request, drawing,
  alert, and `varip` machinery, but broker side effects must remain strategy
  mode only.

## Public Output Contract Direction

Strategy output should be a distinct result family instead of overloading
indicator plots. Start with a narrow shape and widen only after fixtures prove
the accounting behavior.

Initial public runtime shape candidate:

```text
strategy: {
  orders: [ ... ],
  trades: [ ... ],
  position: [ ... ],
  equity: [ ... ],
  diagnostics: [ ... ]
}
```

Initial field direction:

- `orders`: deterministic order events accepted by the broker emulator.
- `trades`: closed-trade records once exits are implemented.
- `position`: sparse or per-bar position snapshots, chosen before the first
  public strategy output lands.
- `equity`: deterministic equity curve or final equity only, chosen before the
  first public strategy output lands.
- `diagnostics`: runtime strategy errors such as invalid quantity, unsupported
  order state, or broker-limit failures if they cannot be semantic diagnostics.

Schema rule:

- Review runtime schema constants before adding the top-level `strategy` field.
- Adding strategy output is a runtime public contract change and should refresh
  CLI/WASM golden snapshots and Python key-contract tests in the same slice.
- Do not expose host-specific strategy fields on only one public surface.

## Broker Semantics Direction

Start with a deliberately small broker model:

- One account currency and one chart symbol.
- Long-only market entries at first, filled by a documented bar-close policy.
- Fixed quantity first; percent-of-equity, default quantity settings,
  commission, slippage, pyramiding, and margin come later.
- A single net position before supporting multiple entries, reversal behavior,
  OCA groups, stop/limit orders, or partial exits.
- Historical execution first. Realtime strategy execution stays unsupported
  until broker state handoff across forming updates is explicitly designed.

Do not claim parity with TradingView strategy behavior until each rule is
represented by fixtures, conformance metadata, and docs.

## How to Use the Acceptance Criteria

The exit criteria under each slice are local merge criteria for that slice.
Phase G should not be marked complete until a closeout audit records the
supported surface, public output contract, host behavior, verification results,
and remaining maintenance tails.

Maintenance tails must be narrow. They may keep advanced order types, realtime
strategy updates, commissions, slippage, margin, pyramiding, or strategy
reporting variables out of scope, but they must not weaken these Phase G
acceptance criteria:

- Indicator and strategy modes are clearly separated.
- Accepted strategy calls produce deterministic broker state transitions.
- Public strategy results are synchronized across CLI, Python, and WASM, or any
  temporary host gap is diagnostic-only and tested.
- Unsupported strategy variants produce stable diagnostics.
- Compatibility claims remain fixture-backed.

## Slice 0: Strategy Design Gate and Diagnostics

Goal: prepare Phase G without changing the public compatibility claim.

Steps:

1. Keep `strategy.*` unsupported in conformance metadata.
2. Add or update semantic fixtures so unsupported diagnostics cover:
   - `strategy(...)` declaration while it is still unsupported.
   - `strategy.entry(...)`.
   - `strategy.exit(...)`.
   - `strategy.close(...)`.
   - strategy calls from indicator scripts.
3. Replace broad unsupported reasons with Phase G-specific reasons where useful,
   while preserving stable `E_UNSUPPORTED_FEATURE` behavior and avoiding
   follow-on `E_UNKNOWN_FUNCTION` diagnostics for the reserved strategy surface.
4. Add this execution plan to the roadmap and document the intended first
   supported subset.
5. Confirm no public output schema or host API changes occur in this slice.

Exit criteria:

- Existing unsupported strategy behavior remains stable.
- Negative fixtures describe the current unsupported boundary before any
  positive strategy feature is accepted.
- Documentation names the first executable strategy subset.
- `strategy(...)`, `strategy.entry(...)`, `strategy.exit(...)`, and
  `strategy.close(...)` all produce stable unsupported diagnostics without
  changing the conformance status.

Verification:

```text
cargo test -p pine-sema strategy
cargo test --workspace
```

## Slice 1: Strategy Declaration Scaffold

Goal: accept `strategy(...)` as a declaration that selects strategy mode without
accepting order functions yet.

Initial scope:

- `strategy(title)` and selected declaration metadata that can be safely ignored
  or stored without affecting broker behavior.
- Reject strategy order calls until broker output and fill rules exist.
- Reject `strategy(...)` inside functions and local blocks like other
  declarations.

Steps:

1. Register a `strategy` declaration signature in `pine-builtins` with a narrow
   parameter list.
2. Add script-mode metadata to semantic analysis and lowering if runtime needs
   it after analysis.
3. Validate that a script has at most one top-level declaration and that
   `indicator(...)` and `strategy(...)` are mutually exclusive.
4. Keep `strategy.entry`, `strategy.exit`, `strategy.order`, `strategy.close`,
   and reporting variables unsupported with precise diagnostics.
5. Add positive semantic fixtures for strategy declaration acceptance.
6. Add negative fixtures for duplicate declarations and strategy calls in
   unsupported contexts.
7. Keep `tests/fixtures/conformance.tsv` conservative. Add a separate
   `strategy declaration` partial row only if positive fixtures and docs fully
   describe the accepted declaration subset.
8. Update `docs/LANGUAGE_SCOPE.md` and `docs/SEMANTIC_MODEL.md` with the
   strategy-mode boundary.

Exit criteria:

- `strategy(...)` can be analyzed without implying broker support.
- Indicator scripts continue to behave exactly as before.
- Order functions remain rejected with stable diagnostics.
- No public runtime output changes are introduced.

Verification:

```text
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
cargo test --workspace
```

## Slice 2: Strategy Output and Broker State Scaffold

Goal: add the runtime and public result boundaries before accepting executable
orders.

Implementation decision: this slice exposes a strategy-mode-only empty
`strategy` result with `orders`, `trades`, `position`, `equity`, and
`diagnostics` arrays. Indicator-mode outputs keep their existing top-level key
set, so `PUBLIC_RUNTIME_SCHEMA_VERSION` remains unchanged.

Steps:

1. Add a `pine-runtime::strategy` subsystem with empty broker state and public
   strategy result structs.
2. Decide the first public `strategy` output shape and whether the runtime
   schema version must change.
3. Add empty strategy output for strategy-mode scripts only, or document why the
   field remains deferred until the first order slice.
4. Wire CLI and WASM JSON through the shared runtime output serializer.
5. Add Python dictionary conversion and key-contract tests for the strategy
   result if the public field lands in this slice.
6. Add golden snapshots for a no-order strategy fixture if the public output
   shape changes.
7. Keep order functions unsupported.

Exit criteria:

- Strategy-mode runtime output has a stable empty contract, or a documented
  deferred contract decision.
- Indicator runtime snapshots remain stable except for intentional schema
  changes.
- CLI, Python, and WASM agree on strategy top-level keys when exposed.

Verification:

```text
cargo test -p pine-runtime strategy
cargo test -p pine-cli golden_snapshot
cargo test -p pine-wasm
python3 -m pytest python/tests
cargo test --workspace
```

## Slice 3: Minimal `strategy.entry` Market Long

Goal: support the first deterministic order path: a long market entry with a
fixed quantity and documented fill timing.

Initial scope:

- Strategy-mode scripts only.
- `strategy.entry(id, strategy.long, qty=...)` with const/string-compatible id
  and numeric fixed quantity.
- One net long position.
- Fill at the current bar close unless a design note chooses a different first
  policy before implementation.
- No pyramiding, reversal, commission, slippage, stop, limit, or short entries.

Implementation decision: Slice 3 fills the accepted long entry immediately at
the current bar close and treats repeated entries while a position is open as a
no-op under the first no-pyramiding rule.

Steps:

1. Add `strategy.long` constant support.
2. Add a `strategy.entry` signature for the accepted argument subset.
3. Reject `strategy.entry` in indicator scripts and side-effect-restricted
   contexts.
4. Add broker state for pending or immediate market entry events according to
   the chosen fill policy.
5. Record deterministic order events and position snapshots in the public
   strategy result.
6. Add runtime fixtures for one entry, repeated entry under no-pyramiding rules,
   conditional entry, and unsupported short/stop/limit parameters.
7. Add incremental append coverage through the existing runtime fixture harness.
8. Update conformance metadata with a narrow `strategy.entry` partial row.
9. Update execution and language docs with the accepted fill policy.

Exit criteria:

- A fixture-backed strategy script can open one long position deterministically.
- Unsupported entry variants are rejected before runtime where possible.
- Public output snapshots make order and position changes visible in review.
- Indicator output and behavior remain unchanged.

Verification:

```text
cargo test -p pine-builtins strategy
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-cli golden_snapshot
cargo test --workspace
```

## Slice 4: Minimal `strategy.close` and Closed Trades

Goal: close the first supported position type and expose deterministic realized
trade records.

Initial scope:

- `strategy.close(id)` for an existing long entry id.
- Full-position close only.
- Same fill policy as Slice 3 unless a fixture-backed design change says
  otherwise.
- Closed-trade records with entry/exit bar, prices, quantity, and profit.

Implementation decision: Slice 4 closes the full matching long position at the
current bar close. Missing ids, mismatched ids, and repeated closes are no-op
events, not runtime errors.

Steps:

1. Add the `strategy.close` signature for the accepted subset.
2. Validate id argument compatibility and side-effect context restrictions.
3. Add broker transition logic from open long position to closed trade.
4. Add public `trades` output fields and refresh snapshots.
5. Add fixtures for ordinary close, close without position, repeated close, and
   conditional close.
6. Update conformance metadata with a narrow `strategy.close` partial row.
7. Document realized profit calculation and no-op/error policy for missing
   positions.

Exit criteria:

- Supported scripts can open and close a deterministic long trade.
- Closed trade output is synchronized across CLI, Python, and WASM.
- Runtime errors or no-op behavior for missing positions are documented and
  fixture-backed.

Verification:

```text
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-cli golden_snapshot
python3 -m pytest python/tests
cargo test --workspace
```

## Slice 5: Equity Curve and Basic Settings

Goal: make the minimal strategy result useful without broadening order types.

Initial scope:

- Initial capital from `strategy(...)` if const numeric and documented.
- Fixed quantity or default quantity only if the declaration semantics are
  fixture-backed.
- Per-bar equity snapshots based on open position mark-to-market and realized
  trades.
- No commission, slippage, margin, percent sizing, pyramiding, or currency
  conversion unless selected by a later slice.

Implementation decision: Slice 5 accepts only positive const numeric
`initial_capital` on `strategy(...)`. The broker tracks cash for the supported
long-only entry/close subset and appends one equity snapshot per historical bar
with `cash`, `marketValue`, `equity`, and `netProfit`, using the current bar
close for mark-to-market. It does not add default quantity settings or any
other broker setting.

Steps:

1. Add declaration argument validation for accepted capital/quantity settings.
2. Store strategy settings in analysis or HIR metadata.
3. Extend broker accounting with cash, market value, net profit, and equity.
4. Add public equity snapshots and golden fixtures.
5. Add runtime fixtures for deterministic equity across rising, falling, and
   flat prices.
6. Update docs and conformance notes for the exact settings subset.

Exit criteria:

- Equity output is deterministic and reviewable.
- Unsupported strategy declaration settings remain diagnostic-only.
- Public host outputs remain synchronized.

Verification:

```text
cargo test -p pine-sema strategy
cargo test -p pine-runtime strategy
cargo test -p pine-cli golden_snapshot
cargo test --workspace
```

## Slice 6: Strategy Runtime Boundary Closeout

Goal: close the first Phase G subset and record maintenance tails before adding
more order types.

Steps:

1. Run the full release verification gate.
2. Add `docs/PHASE_G_AUDIT.md` with completed slices, supported surface, public
   output contract, host behavior, fixture evidence, verification results, and
   maintenance tails.
3. Update `docs/LONG_TERM_EXECUTION_PLAN.md`, `docs/CONFORMANCE.md`,
   `docs/LANGUAGE_SCOPE.md`, `docs/EXECUTION_SEMANTICS.md`, and
   `docs/RELEASE_NOTES.md` to agree on the supported strategy subset.
4. Ensure conformance rows are narrow. Prefer `strategy declaration`,
   `strategy.entry`, `strategy.close`, and `strategy equity` rows over a broad
   `strategy.*` partial claim.
5. Keep unsupported strategy variants explicit in conformance metadata and
   semantic fixtures.

Exit criteria:

- The first strategy subset is documented as partial and fixture-backed.
- Unsupported order types and broker settings remain explicit.
- `scripts/verify.sh` passes.

Verification:

```text
git diff --check
scripts/verify.sh
```

## Later Strategy Maintenance Tails

Do not start these until the minimal long-entry/close subset is stable:

- `strategy.exit` stop/limit exits.
- Short entries and reversal behavior.
- `strategy.order` and richer order modification semantics.
- Pyramiding and multiple simultaneous entries.
- Commission, slippage, margin, currency conversion, and percent-of-equity
  sizing.
- Strategy performance metrics beyond the initial public result fields.
- Strategy variables and reporting helpers such as position size, average
  price, net profit, open trades, and closed trades.
- Strategy alerts and alert placeholders.
- Realtime strategy execution and forming-bar broker rollback.
