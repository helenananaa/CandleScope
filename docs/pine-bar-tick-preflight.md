# BAR/tick preflight after Workbench controls

The subsequent [explicit schedule foundation](pine-external-schedule-foundation.md)
implements the core observation/state separation below. CandleScope transport,
BAR matching and history-tick scheduling remain unfinished. This preflight
retains the original installed-core evidence rather than rewriting its results.

Verified against the installed core candidate from `1b506560a` on 2026-10-19.
This is a requirements/ownership audit, not implementation or official output
qualification. The actual probe is retained at
`output/pine-host/phase3/bar-history-tick-preflight.json`.

## Current official requirements

The current [strategy documentation](https://www.tradingview.com/pine-script-docs/concepts/strategies/#calc_on_every_history_tick)
distinguishes historical-tick execution from fill-triggered recalculation.
Historical fill recalculation can see final OHLCV. Historical-tick mode instead
reveals evolving values while historical `barstate.isconfirmed` remains true.
Standard detail uses four price vertices with cumulative quarter-volume steps;
their order depends on the open's distance from the extrema. Lower-timeframe
detail changes the available intrabar path.

The [execution model](https://www.tradingview.com/pine-script-docs/language/execution-model/)
also distinguishes executions caused by fills from executions on every historical
tick, including ticks with no fill. These are separate scheduling requirements.

## Verified local classification

| Requirement | Current evidence | Work required |
| --- | --- | --- |
| `calc_on_every_history_tick` | Compile fails with `E_CALL_ARG_NAME`; declaration and Host-requirements metadata have no setting | Core language/settings/runtime support and a neutral external execution contract, then Host scheduling |
| `calc_on_every_tick` | Declaration compiles and metadata exposes it; external-account construction explicitly rejects it | External execution contract and Host tick scheduling; this is not a missing declaration |
| `calc_on_order_fills` | Declaration and execution-pass contract exist; omitting required passes rejects as expected | Host BAR intrabar matching/callback clock, with core contract extensions where history states cannot be represented |
| Historical BAR fill path | Current Host BAR contract is a declared worst-case approximation | A separately identified deterministic historical path; do not relabel previous BAR results |

Relevant sources are core `crates/pine-sema/src/analyzer/strategy/declaration.rs`,
`crates/pine-runtime/src/host_requirements.rs` and
`crates/pine-runtime/src/external.rs`, plus Host
`backend/app/backtest/pine_callbacks.py` and `backend/app/simulation/kernel.py`.

## Next implementation boundary

The current causal trade callback uses an unconfirmed forming pass. External
passes currently couple confirmation with immutable-bar/commit restrictions.
That is insufficient to express historical intrabar observations whose script
bar state stays confirmed while their visible prices evolve. Reusing that
forming pass unchanged would preserve a different execution model.
An installed-core probe confirms that two confirmed passes with evolving market
values reject, including with the existing closing-tick opt-in. That opt-in only
permits repeated immutable close observations; it is not a historical-tick API.

The next phase must represent execution trigger, historical/realtime bar state,
observed market values and final commit separately. It must retain rollback,
`varip`, resource budgets, actual Host account feedback and replay identity.
Native account evaluation remains independent of concrete CandleScope services.

Acceptance must distinguish default four-vertex history, lower-timeframe paths,
fill-only passes and physical trade ticks. Tests must compare full and restored
execution, position/fill order, visible values and committed series. Documentation
alignment alone cannot establish TradingView output parity. Other remaining
requirements in `pine-host-completion-goal.md` remain active.
