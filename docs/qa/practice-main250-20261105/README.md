# Practice committed updates on main250

Source503d446f456c6a34d3363bb4f62c4428b4fbbe48 integrates main18cd6f34
without conflicts. Frontend/packages bytes remain identical to e8be1c91.
All60 pre-existing dirty QA files retain their SHA256 values, unstaged.

189 backend regressions pass with6 warnings: actual trading accounts/snapshot/
state streams, Controller, provider/definition/creation journal, BAR host and
Spot depth budget. This uses retained bundled Python with isolated synthetic
data and existing test dependencies; it is not a new full frontend/backend run.
An initial test command referred to a nonexistent test_continuous_runtime file,
ran zero tests, and was replaced by the actual BAR-host/state-stream suites.

A fresh APFS clone of main243-depth runtime contains current tracked backend
and SDK mirrors. Source/build/plugin bytes and deep strict signature pass;
manifest and verification receipts are retained. No profile or LIVE launch yet.
The previously qualified runtime/plugin sources are reused, not rebuilt.
Native queue follows PR227 complete owned exit and current public gate.
Shared cooldown helper now persists newly observed deadlines to both global
state files before stopping. No exchange retry/weight policy was relaxed.

Actual independent committed push, shared/pinned isolation, exact Spot ledger
oracle and save/full owned quit/restart remain pending for this source.
Prior LOCAL_OFFLINE evidence remains separate. Keep Draft and broader177/
Windows open. CI runs in the background; exact head/current base required
before merging main.


## Actual LIVE market / simulated-account Native result

Source503d446f completed13 stages in a fresh isolated arm64 packaged profile:
actual UI-created practice accounts and buy, independent local API working-order
create/cancel/market close, account-A chart pinned while panel selectsB, exact
committed snapshot push and no legacy summary/trades/journal polling or renderer
stream reconnect during the uninterrupted22s phase. Both account streams have
exactly one renderer consumer during that phase. A readonly Decimal oracle checks
both final cash and closed-trade net PnL against actual two fills/fees.

The same source's actual saved profile/full owned quit/restart restores accountA,
all fills and stable balances/trades, ledger epoch/cursor and pinned account.
The final renderer consumer release/reopen ends the stream then acquires exactly
one and restores saved state. No injected response or source mutation; external
exchange data is read-only and all orders belong to isolated local practice
accounts. Saved/restored screenshots were inspected.

Two normal complete exits took15201/15248ms,10 processes each;20 PIDs were
separately confirmed absent. Strict source/build/plugin/signature verification
passes before/between/after. Renderer page errors=[] and no new418 observed.
Backend internal consumer counts are not exposed by this native API; renderer
cancellation and full application cleanup are the actual observed scope.

Two earlier harness failures are retained: ambiguous add-account buttons, then
an exact wrapped-select label that included option text. Actual toolbar/unique
combobox selectors were corrected without product or financial assertion changes.
Their profiles and successful first account entry remain preserved; neither is
counted as completed qualification. This local source pass does not qualify
Windows, all177, live exchange orders or all broader financial scenarios.
Final head/current base review and CI still gate main merge; development does
not wait for CI.
