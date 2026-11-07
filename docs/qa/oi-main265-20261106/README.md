# OI history and runtime shutdown on main265

Product source `d60ebd7619393c2798cc3772f3f838730cd55ad8`, after conflict-free integration `34c735839cb2f11d389c3badbe741904d34c1571`, includes actual main `05a1c2a8f9c2c246cf2dffc9fe82109595913139`. The original OI worktree remains at `30e3f962…`; all 24 dirty files, full status and its checked-out branch were independently protected. Its published remote advances only by fast-forward.

## Real runtime ownership gap

The prior #218 fix retained cancelled OI queries until their physical storage work ended and counted those retiring jobs toward the 32-query limit. The production runtime still cancelled `MarketDataService.shutdown()` at its step deadline. That waiter previously returned cancellation while the shielded cleanup task was still draining SQLite, allowing the runtime to stop its dependent DataManager, ingestion factory and backfill transport too early.

Two actual `DataEngineRuntime.shutdown()` cases reproduced this on the integration source. They use the real MarketDataService/repository and a held SQLite snapshot, a logically cancelled query and a short runtime step deadline, with observed stop adapters for unrelated components. Both successful and failing physical reads left the runtime finished while the SQLite reader remained active. The full original failure log and exact regression helper are retained. This is a runtime/service integration test, not a full application startup or Native claim.

The fix is confined to the actual MarketDataService shutdown waiter. When cancelled, it keeps ownership of the same cleanup task until that task ends, then propagates cancellation. The runtime's `wait_for` can consequently report its deadline only after physical work is drained; its later components cannot run before that point. The timer does not forcibly abort a physical SQLite operation, and this does not claim a hard wall-clock shutdown bound. Query receipts, source timestamps, finality, coverage policy and the existing capacity contract remain unchanged.

The regression verifies one owned storage job remains after logical release, runtime shutdown stays pending beyond its short step deadline, dependent stops have not run, and after releasing the real reader both success/failure paths drain to zero jobs/identities before the later components stop. The original source/query cancellation and 32-work-capacity cases remain enabled. The separate whole-application cancelled-waiter correction is tracked in #223; it is not silently imported or claimed by this branch.

## Qualification

- Final single combination: **605 backend passed / zero skips / six existing warnings**, across the 44 suites in `backend-command.json.gz`. It includes OI/storage/real factory/API/history contracts, the new runtime cases, imported BAR/multi-market/note regressions, native-second-exchange contracts, continuous-account source/controller tests and the market/tape/book/liquidation/manual-history runtime suites. The focused **61-pass** run overlaps and is not added.
- Full `npm run check` completed at integration source34c: **4,894 regular tests / one independent performance check / 130 desktop tests; zero skips**. The entire frontend and packages Git trees equal the final qualified source. Existing SingleChartPanes lint and bundle-size warnings remain. The backend-only ownership fix is not relabelled as a frontend rerun.
- The exact main265 architecture baseline was independently checked against its Git blobs. Current source has the same ten normalized findings, not an architecture-clean result.
- All 24 original dirty files, original worktree status and checked-out local branch remain unchanged. The exact command/environment and source/build/test fingerprints are recorded in `source-manifest.json.gz`.

The first attempt failed in pytest setup because the owned basetemp parent did not exist; no product case ran. The next attempt produced the two real baseline failures. An uncommitted first patch matched a funding-refresh wait rather than shutdown and still failed the same two cases; that diff and result are retained. The funding path was restored, the actual shutdown method corrected, and the unchanged runtime ownership assertions then passed. No test or capacity check was removed.

## Evidence and reproduction

`receipt.json` inventories helpers and compressed raw evidence by hash. The complete before/after and combined logs, original regression helper, misplaced patch, source identities, exact commands and original-file protection inventory are retained. Original uncompressed output and test data remain under the receipt's absolute paths.

Use the retained qualified Python launcher without resolving it. Set `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=packages/candlescope-plugin-sdk/src:packages/candlescope-backtest-sdk/src:backend`, and fresh data/basetemp roots, then run the exact command in the manifest. The held physical-read helper has an explicit release and drains both the cancelled consumer and cleanup task in `finally`, including failed cases.

## Remaining gates

No new large Native candidate was assembled. The prior unlaunched source4db package and original fc7f44f9 22-stage Native OI/pane/cold-storage/full-owned-exit/restart acceptance retain their original identities. **Current-source Native acceptance is still pending**, and the public retry gate remains `2026-11-06T10:12:49.286Z`. The original full-field, source timestamp and receipt assertions must be rerun on a fresh isolated profile after that gate.

A fresh read-only Windows `list_sessions` probe again failed at the MCP SSE gateway with HTTP429 before any host command. This is neither Windows product success nor product failure. Windows and the wider #149 sources/channels, old backfill/delete/revision fencing, cross-process acquisition coordination and performance work remain open. Keep #218 Draft; development does not wait for CI. Main merging still requires final-head/current-base applicable checks and the source-specific Native product evidence.
