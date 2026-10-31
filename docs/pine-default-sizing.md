# Pine defaults from Host accounts

This document preserves the default-sizing checkpoint's source/artifact identity.
The later [annotation worker](pine-order-metadata.md) retains this sizing contract
and passed the final 392-case historical profile on 2026-10-21. Its core/SDK/bridge
hashes are separate from the earlier wheels named below.

The development worker exposes `external_sizing: 1`, with chart adapter
`pine-chart/6` and external adapter `pine-external/10`. It requires a core
exporting `EXTERNAL_SIZING_SCHEMA_VERSION == 1`; package version alone cannot
identify this capability.

The core evaluates explicit quantities, fixed/cash/equity defaults and
`strategy.default_entry_qty`. CandleScope supplies the authoritative account
frame for each execution pass. A declared Pine `initial_capital` does not
replace the Host account. Entry/order defaults use placement close, following
the core's existing native broker formula. The default-quantity query uses its
explicit price. Neither path predicts a future fill price.

The additive core inventory `account.defaultQuantity` contains a kind and a
decimal-string value. Chart compilation and Workbench control admission freeze
it into their execution input. Reports retain the declaration and the exact
worker identity. Host validation rejects missing/malformed declarations for a
worker advertising schema 1. Older workers cannot admit chart cash/equity
defaults or the default-quantity query through the new capability gate.

The shared core formula applies chart quantity precision and supplied currency
rates. This checkpoint uses unit point values. CandleScope continues to own
fees, slippage, margin, admission, fills and callbacks. Nonunit multipliers,
broader currency-profile admission and external order metadata remain separate
work; no TradingView broker-output equivalence is asserted.

## Reproduction and evidence

- `test_pine_sizing_contract.py` exercises strict schema/declaration admission,
  structural chart gating and Workbench freezing. Together with the existing
  Workbench-contract module, 40 checks passed.
- `test_pine_default_sizing.py` passed all 12 installed-worker cases: chart and
  Workbench, cash and percent-of-equity, spot and V1/V2 perpetual accounts.
  Each uses a script declaring 1,000,000 initial capital while the Host has
  10,000, with cash 70 or equity 0.7%. Both size the entry to 7. Synthetic BAR
  capacity produces fills `[5, 2, 3, 4]`; cost baselines are independently
  reexecuted. The V2 equity Workbench case also restores a saved replay prefix
  and verifies the complete endpoint against the original report.
- The production editor/panel fixture was operated in a real browser for both
  defaults. Retained API configurations exactly match the pasted scripts;
  fills are `[5, 2, 3, 4]`, final position is zero and final equity is
  `9996.3635`. Editing the source displayed the expired-result disclosure.
  Evidence, screenshots, API runs and a verification script are under
  `output/playwright/pine-default-sizing-20261020/`.

The first automated editor insertion added Monaco indentation and produced a
parse error. The source was corrected through a normal paste event and checked
against each retained API configuration. The initial HTTP 400 remains in browser
console evidence; successful execution is established by the later durable runs,
not a claim of an error-free session. The fixture uses actual production
components with isolated synthetic data, rather than the complete packaged app.

Core source is `f5c2f227ef5163c25c2bad5346700c29397536fb`.
The freshly built core wheel has SHA256
`b1e0cac313b461874d702583948809f5c3fb0c72e086841ed1ecd341f3db49a4`.
The development worker registry and bridge wheel are retained under
`output/pine-host/completion-goal/default-sizing-candidate/`. Global activation,
released catalogs and default desktop build pins were not changed. Its own full
profile attempt was interrupted and retained; final complete qualification uses
the later annotation worker's matching sources and 392-case receipt. Older
313-case evidence belongs to the preceding fixed-default worker.
