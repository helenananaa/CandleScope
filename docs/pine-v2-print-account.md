# Workbench V2 historical account over physical print/book data

Phase 4 development, 2026-10-22. The ordered Goal remains active. This is the
Workbench profile, not a claim that chart book execution or every-tick schedules
are qualified. The complete installed-worker gate passes all 664 selected cases
across 50 modules, with zero failures/errors/skips, in 1,251.156 seconds. Source,
runtime and registry fingerprints remain unchanged during that run.

`account_model="LINEAR_PERP_ONE_WAY_V2"` now combines with `TRADE_TAPE`,
`BOOK_ASSISTED`, `BOOK_DEPTH` and `BOOK_SAMPLED`. Frozen `account_data` supplies
actual historical INSTRUMENT_RULES, MARK_INDEX and optional required FUNDING.
The opening rules bind Pine contract metadata; point value and price tick stay
fixed within a run. Observed account admission rules remain causal. Source data
quantities use the supplied linear contract units; this is not acceptance of
an arbitrary exchange dataset or inverse contract.

The Host merges account events before physical market events on timestamp ties,
while preserving each source order and original trade/book coordinates. Each
closed-bar checkpoint binds the complete merged source horizon and the physical
trade count. Legacy replay keeps its original source coordinates and does not
construct this V2 merged index. The shared account owns all money: trade prices
and bar closes never overwrite the historical mark. Funding and actual
liquidation settlements pass through its existing ledger, order allocations,
margin repricing and receipts. Settlements consume no extra physical liquidity.

With explicit fill recalculation, account settlements trigger script feedback.
If settlement occurs before the new bar's first print, feedback waits for that
first observed print. It does not invent an opening quote from MARK_INDEX or
future frozen OHLCV. Ordinary account changes do not introduce extra strategy
evaluations. Every-tick scheduling remains subsequent work.

Workers receive only observed market/account evaluation frames. Future account
and execution tapes, account provenance and Host-only V2 configuration stay in
the Host. Full and restored execution rebuild the evaluator transcript without
rematching earlier trades, funding or settlements. Invalid combinations reject
at the API schema boundary before automatic market-data acquisition.

Physical trade participation is admitted only for TRADE_TAPE with the explicit
EXECUTION_REALISM_V2 profile. The V2 decision chain, frozen intents, decision
count and fill-policy identity are checkpointed together. Book modes retain
their own visible-depth/queue capacity and reject synthetic BAR participation.
Workbench does not expose a latency contract: its cost matrix marks the latency
scenario inapplicable rather than relabelling it as a performed experiment.
Fees/slippage and admitted participation scenarios independently reexecute Pine
and fresh historical accounts. BAR settings remain on their separate path.

Manual Workbench controls and automatic TRADE_TAPE preparation preserve account
uploads, callback choice, data/retry identity and result staleness. Automatic
book acquisition remains unsupported: those modes require uploaded execution
data. The UI keeps unsupported capacity choices explicit.

Controlled development receipts live under
`output/pine-host/completion-goal/v2-print-20261022/`. They include four modes
with callbacks on/off, durable account reconstruction, funding, distinct actual
liquidation feedback, partial depth settlements, independent cost scenarios,
realism decision-chain recovery and actual automatic archive preparation. The
initial 84-case integration receipt predates later admission/decision-chain
repairs; later scoped logs retain their exact identities. Failed attempts remain
retained, including the zero decision-chain regression and a test fixture that
incorrectly expected 70 units from a 25-unit print. This is not a TradingView
broker/reference comparison, live trading proof or packaged-app qualification.

The final frozen receipt is `historical-01/receipt.json` (664 passed, 16 Pyne
cases deliberately excluded). Frontend validation passes 16 tests, both
TypeScript projects, scoped ESLint and all 30 locale catalogs. Only these summary
documents change after the gate; the commit receipt records that delta.
