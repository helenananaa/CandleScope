# F112: isolated allocation leaves a stale zero opening capacity

Priority: P1. Original acceptance: SIM-03/SIM-04/SIM-05. Native failure observed on the qualified Z1 package (PR74 head a173e6d2, backend equal to main bcf6b18d).

Create HEDGE / ISOLATED, reveal the first LTCUSDT aggregate trade, then allocate 500 USDT independently to LONG and SHORT in the Risk panel. The account correctly reports both allocations, cash/equity 10000 and available equity 9000. Returning to the order panel with quantity 1 still shows a maximum of 0 LTC, disables Open Long and leaves the fee/margin preview empty. No orders had been submitted.

Changing only the draft leverage from 5x to 3x and back to 5x restores capacity to 23.58295339 and 39.26571541 LTC respectively. Financial fields, global clock and all order/fill/ledger pages remain equal. The account-history audit proof refreshes naturally; both audits remain PASS with no differences. This workaround is diagnostic evidence and does not qualify the failed journey.

The advisory scheduler deliberately deduplicates capacity requests across cursor changes, but its context also omitted explicit isolated allocation changes. A settled zero capacity could therefore survive newly funded collateral. Conservative rebasing cannot increase zero into an authoritative positive cap.

Include the selected leg's explicit allocation in capacity, sizing and preview identities, including the target side identities populated by submit-time validation. HEDGE uses the track and LONG/SHORT key; ONE_WAY uses the track key. An unrelated leg's allocation does not change the selected context. Existing debounce, cursor handling, server validation and financial calculations are unchanged. PR75 is excluded from this branch.

Validation includes allocation selection/scheduler tests and a real mounted React order component with retained native portfolio schema and fixture advisory responses. The original main component reproduces the stale zero; the patched component requests capacity at allocation 0/500/100/0/500, updates the preview and disables again after release. Other-leg allocation and cursor-only updates issue no new capacity request. This fixture forbids trading and does not replace normal desktop qualification.

Evidence is retained locally under `output/acceptance-delivery-20261016/batch-ad/`: AD08 predeclared independent raw/Decimal oracle, AD10/AD11 allocation receipts, AD12 failure AX/screenshots, AD13 draft-only counterexample, AD14 native failure, AD15 saved-state/full-exit receipts, AD16/AD17 mounted candidate/baseline observations and AD18 scope boundary. The saved native run is a3956601cc294dfab70401f1e2785c3b at time 1791619141493/source1, zero orders/fills and LONG/SHORT allocations 500 each.

Remaining gate: exact-head official package, normal native allocation change without draft workaround, actual dual-leg orders, pending limits, save/full exit/restart, cancel, close one leg releasing only its allocation, close the other and independently reconcile all records. Extreme-risk/liquidation, funding, protection, partial-fill and other acceptance gaps remain open.
