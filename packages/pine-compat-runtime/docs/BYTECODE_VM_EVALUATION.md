# Bytecode VM Evaluation

Status: deferred.

Phase 6 evaluated whether the project should add a bytecode VM now. The answer
is no for the current codebase.

## Current Execution Model

The runtime executes HIR directly through `HistoricalRuntime`.

Current performance work already added:

- compile result caching in `pine-sema`
- runtime storage profiling
- per-callsite rolling windows for `ta.sma`, `ta.bb`, `ta.highest`, and
  `ta.lowest`
- append-bar execution through `HistoricalRuntime`
- fixture-level verification that append execution matches full historical
  execution

This gives the project a single runtime semantics path with measurable storage
behavior.

## Why Not Add Bytecode Now

Adding bytecode now would introduce another semantic representation before the
language surface is stable.

Specific blockers:

- no MIR layer exists yet
- control-flow semantics are still intentionally narrow
- user-defined function and loop lowering now have enough semantics that a MIR
  layer should precede any bytecode implementation
- input override semantics are not finalized
- realtime `varip` semantics are not implemented
- profiling currently identifies storage shape, not instruction dispatch as a
  bottleneck

The likely cost is duplicated behavior between HIR execution and bytecode
execution. That would increase compatibility risk without a measured payoff.

## Re-Evaluation Triggers

Revisit bytecode after at least one of these is true:

- MIR exists and is used as the only runtime-facing representation.
- Profiling on large fixtures shows expression dispatch is a meaningful
  bottleneck after rolling-window and allocation work.
- User-defined functions or loops make repeated HIR tree walking expensive.
- Host integrations need a compact serialized program format.
- Incremental execution needs faster cold-start or lower per-bar latency than
  direct HIR execution can provide.

## Recommended Future Shape

If bytecode becomes justified, it should be introduced behind a parity test
suite:

```text
source -> AST -> HIR -> MIR -> HIR runtime
                         -> bytecode runtime
```

The bytecode runtime should not define new semantics. It should execute MIR
semantics with a smaller dispatch representation.

Minimum acceptance criteria:

- all runtime fixtures pass on both HIR and bytecode paths
- append-bar parity passes on both paths
- diagnostics remain produced before bytecode lowering
- a benchmark shows a clear win on large historical runs or repeated append
  workloads

Until those criteria are met, direct HIR execution remains the reference
runtime.
