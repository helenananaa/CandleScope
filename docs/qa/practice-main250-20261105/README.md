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
