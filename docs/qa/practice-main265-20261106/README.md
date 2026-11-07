# Practice state and application shutdown on current main

PR #223 integrates actual main `05a1c2a8f9c2c246cf2dffc9fe82109595913139` without conflicts at `f3fe38b5bf5f631ca8ab90124afd7026417c125c`, including the #264 imported multi-market replay code and #263/#265 QA. The original dirty practice worktree and its checked-out `ef5f5d0d…` branch remain untouched. Its 60 dirty files and complete status were independently checked against the protected inventory.

Current qualified checkout: `e20ab9e808e237955b278a9f61ff92b89a02c652`; application fix `3531c3627f116d121d75b59fd2dcc72661e0b9b8`. The later commit corrects only an exact Decimal expected type in the regression test. Application and frontend source identities are kept separately below.

## Actual application cancellation defect

The prior #223 fix correctly drained a physical account reader when its manager's shutdown waiter was cancelled. The application handler still stopped at that propagated cancellation: its subsequent trading-ledger close and replay-runtime shutdown were skipped. New cases held a real trading SQLite/WAL snapshot while a second real replay SQLite store had already committed a session whose registration was paused. Two normal-shutdown cases passed on the integration source; both repeated-cancellation cases failed because the application abandoned the trading ledger after its reader drained. Their full original failure log is retained.

The application handler now owns the complete existing component cleanup in one child task. Cancelling its waiter repeatedly does not cancel that task or skip remaining owners. It finishes cleanup, then propagates cancellation. The component ordering and existing non-cancellation failure behavior are retained; a cleanup failure during an already cancelled wait is retrieved and logged. This does not claim a new global shutdown timeout or concurrent-call idempotency contract.

The four real-store cases cover successful/failed physical reads, with/without repeated cancellation. They verify that the ledger never closes before its WAL reader ends, the pending replay registration keeps its store owned, both stores finish shutdown before the waiter settles, the committed replay row survives reopening, and the original practice cursor and exact Decimal `1000` cash survive. Test cleanup releases both gates and drains all owned tasks even on failure.

## Source and HTTP qualification

- Final single backend combination: **470 passed / zero skips / six existing warnings**, across the 36 suites recorded in `backend-qualified-command.json.gz`. This includes the new application cases, existing trading financial/state tests, actual imported BAR/multi-market/note routes, continuous-account source/controller tests, replay actor shutdown and real indicator-observer disconnect draining. The earlier 442-pass integration run and focused nine-pass run overlap and are not added to this count.
- Full `npm run check`: **4,897 regular tests / one independent performance check / 130 desktop tests; zero skips**. It completed at integration source f3; the whole frontend and packages Git trees are byte-identical at the final qualified checkout. Existing SingleChartPanes lint and bundle-size warnings remain. These results are carried by that exact tree identity; the final backend-only fix is not presented as a frontend rerun.
- Fresh exact-main backend architecture baseline and current source have the same ten normalized findings. This is not an architecture-clean result.
- Actual HTTP/SQLite and the unchanged frontend DataPool/state transport passed in two fresh server/model phases on application source3531, whose entire `backend/app` tree equals the final qualified checkout. Two consumers of account A shared one stream, account B remained independent, and market order / OCO fill / working-order cancellation preserved independent integer-fee results: cash `1002.9294`, net PnL `2.9294`. No legacy summary/trades/journal polling occurred. Both phases ended with closed owners, zero subscriptions and zero read jobs. All four roots exited0; all five observed owned PIDs were independently absent. The loopback network guard reported zero blocked attempts.

The initial 442-pass combination and an initial HTTP/model restart belong to f3. After the application fix, the first combined run reached the final reopened-cash check in all four new cases but compared a Decimal to a string: 466 passed / four failed. The correction compares exact Decimal `1000`, preserving the ownership, persistence and financial assertions. That complete failed log and classification remain alongside the authoritative 470-pass result.

The real HTTP fixture uses deterministic controlled BAR inputs and a standalone local composition. It is not production LIVE startup, a browser flow or Native app save/quit/restart. A separate HTTP fixture lifespan and the actual production `shutdown_event()` tests are explicitly distinct evidence.

## Evidence and reproduction

`receipt.json` inventories all helpers and compressed raw evidence by hash. `source-manifest.json.gz` records the exact source/build/test fingerprints, trees, commands and distinct evidence sources. The original 60-file protection inventory and all original logs remain at the absolute output paths in that receipt. No original dirty QA or profile database is committed.

Use the retained qualified Python launcher without resolving its symlink. Set `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=packages/candlescope-plugin-sdk/src:packages/candlescope-backtest-sdk/src:backend`, and fresh `DATA_DIR` / `CANDLE_DATA_DIR` / pytest basetemp paths. Run the exact 36-suite command recorded in the manifest. The default HTTP orchestrator creates a new output root and refuses an existing one; both initial and final roots from this delivery remain preserved. Run with a fresh allowed root label and the corresponding new directory before repeating:

```sh
CANDLESCOPE_PRACTICE_HTTP_ROOT_NAME=pr223-main265-http-final-20261106 \
  /absolute/qualified/python -B docs/qa/practice-main265-20261106/http-orchestrator.py
```

Both server and client are copied unchanged from the prior committed helpers; only the orchestrator's fresh root/helper paths changed. Its financial and owner-exit assertions are retained. A new output label must be deliberately added for another run instead of overwriting the retained one.

## Remaining gates

No new large Native candidate was assembled in this round. The old unlaunched456e package and old503d Native acceptance retain their original identities. **Current-source Native UI / financial / save / full-owned-quit / restart remains pending**, with public retries prohibited before `2026-11-06T10:12:49.286Z`. Windows, full #177, multi-instrument/HEDGE and a resumable row-delta journal remain open. The current transport still sends replacement account views. Keep #223 Draft; development does not wait for CI, while main merging requires final-head/current-base applicable checks and the missing Native qualification.
