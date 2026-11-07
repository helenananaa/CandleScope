# Committed practice updates on main261

Product source `456e75253d692206f58b0a580864de37a1b2e688`, after conflict-free
integration `9dd0966ccb1e24ccba7e96b7f33e37261c019d51`, includes actual main261
`0de39f37f2389b09a35fc91e3a6d8d5844137da8` above prior #223
`ef5f5d0d52e84f8ebb7cb5e21bb5313777c7cfd8`.

## Physical-read shutdown defect and correction

The old application shutdown signalled TradingAccountDataManager.close(), then
immediately closed its SQLite ledger. run_storage correctly retained a running
thread while cancellation drained, but no application owner awaited that task.
Two actual SQLite/WAL counterexamples held a real account snapshot, initiated
production shutdown_event(), and observed the ledger close before the physical
reader ended, both when the eventual read succeeded and when it failed.
The failing source is the integration commit above; raw failure logs are retained.

Application shutdown now stops matching, awaits DataManagerCore.shutdown_trading(),
then closes the ledger. It closes subscriptions/admission and drains the tracked
storage tasks. A cancelled shutdown waiter continues owning the physical reads,
then propagates cancellation. New tests include repeated cancellation, rejected
new subscription, idempotent shutdown, actual application ordering, and physical
read failure. The matching/financial/stream protocol contracts remain unchanged.

## Current source checks

- One combined backend run: **313 passed / zero skipped / 6 existing warnings**,
  including the3 new shutdown cases, all current continuous controller/provider/
  creation/source tests, trading financial/snapshot/state suites, actual app
  shutdown and offline profile, executors and market/source budget contracts.
  The prior focused17-test pass overlaps this combination and is not added.
- Full `npm run check` exited0: **4894 regular tests, 1 independent performance
  check and 130 desktop tests; zero skipped**. Architecture/plugin/i18n,
  TypeScript, lint and production build completed. The pre-existing
  SingleChartPanes ref-cleanup warning and large-chunk build warning remain.
- Backend architecture's10 existing findings are byte-equal to the actual-main261
  baseline, not a claim of architecture-clean source.

The real HTTP/SQLite + unchanged frontend TradingAccountDataPool/state transport
flow passes, then a fresh backend and fresh frontend model process reopen the
same ledger. Two consumers ofA share one stream whileB remains independent;
market buy, OCO bracket fill, working order create/cancel and stable cursor/fees
are verified. Cash1002.9294 and net PnL2.9294 match separate integer fee arithmetic.
No legacy summary/trades/journal polling, two initial streams, zero outbound
network-guard attempts. Both phases finish with closed owner, zero subscriptions
and read jobs. All4 root processes exit0; all6 observed roots/descendants are
independently absent. This is not a browser or Native restart claim.

The initial HTTP fixture completed its flow and cleanup but exited by SIGINT:
Uvicorn0.34 re-raises the signal after lifespan cleanup. Its receipt/log/profile
remain retained. The new fixture handles KeyboardInterrupt only after the full
owned shutdown completed; both normal exit and explicit zero-resource shutdown
receipts are required. Client/product/financial assertions are unchanged.

## Current unlaunched Native candidate

An APFS clone of the retained strictly verified main250 app contains this exact
backend/SDK, newly built frontend/desktop, updated ASAR integrity and deep ad-hoc
signature. **1064 source files,164 built files,9 plugin assets,76 plugin source
files match, zero mismatches; deep strict signature passes.** Packages are byte-
identical to prior #223; their wheels/core are reused and source-verified, not
rebuilt. This is a local arm64 candidate, not a fresh standalone runtime build
or original CI artifact. No profile exists and it has not been launched.

Assembly: set CANDLESCOPE_BATCH1_QA_ROOT to a fresh owned output root,
CANDLESCOPE_QA_RUNTIME_SOURCE to the retained verified main250 app, and
CANDLESCOPE_QA_REUSE_VERIFIED_PLUGINS=1; run assemble.py with the retained qualified
Python launcher, then node verify.mjs. Full source/helper/tree/command/environment
identities and raw receipts are in source-manifest.json.gz and evidence/.

The old source503d446f's13-stage Native save/full-owned-quit/restart result remains
valid only for that original source. **Current456e7525 Native qualification is
pending.** Do not launch the default LIVE/public path before the persisted
2026-11-06T10:12:49.286Z gate, then use a new isolated profile and the unchanged
financial/UI/save/restart acceptance requirements. Windows, multi-instrument/
HEDGE and wider #177 requirements remain open; replacement account views are not
a resumable row-delta journal. Keep Draft. Development does not wait for CI;
main merging requires final-head/current-base applicable checks and product proof.

All60 files in the original dirty practice worktree retain SHA256 values. That
checked-out local branch remains at its original commit; the clean integration
branch carries this work and the remote PR advances only by fast-forward.
