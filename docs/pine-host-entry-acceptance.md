# Controlled Pine Host entry acceptance

This fixture mounts the production Workbench, report and replay components and
uses real production API routes, preparation, plugin resolution, the installed
interpreter, Host accounts and SQLite recovery. Market bars and account rules
are synthetic. It is a controlled component-entry test, not the complete
desktop application, a packaged release, live exchange data or an official
TradingView output comparison.

## Start an isolated backend and UI

Use a backend test Python with the normal application dependencies. The state
directory must be new. The plugin registry must point to the explicitly chosen
installed candidate. Neither command changes a global registry or release pin.

```powershell
python backend/scripts/pine_host_acceptance.py `
  --state output/playwright/pine-host-entry/state `
  --runtime-registry <isolated-registry.json>
```

In another terminal:

```powershell
node frontend/scripts/pine-host-acceptance.mjs `
  --state output/playwright/pine-host-entry/state
```

Open the printed browser URL in an isolated browser profile/session. Append
`?automatic=1` to exercise automatic preparation instead of a frozen dataset.
The backend has no live market download provider. Its synthetic minute history
is bounded to 10,001 rows. Direct execution uses ten minute bars; automatic
execution constructs four daily bars from minute history.

To restart the backend against its durable data, add `--resume` and keep the
same state and registry. The recorded port is reused unless explicitly changed.
Shutdown endpoints are `POST /api/harness/stop` on the backend and
`GET /__acceptance_stop` on the UI helper. Both bind only to loopback.

## Browser checks

1. The restored account-upload marker requires file reselection and disables
   Run. Select `<state>/account.json` using the real file chooser. Keep V2,
   leverage 10, BAR fill recalculation, participation 0.05 and AUTO costs.
2. Run directly. Expect the V2 account and OHLC V2 matcher, quantities
   `[5, 2, 3, 4]`, and a completed cost matrix. BAR latency must remain explicitly
   unavailable. This fixture's baseline ending equity is `9996.3635`.
3. Open interactive replay, seek to chart cursor 3, save a snapshot, play to the
   endpoint, restore the snapshot, and play again. The partial report must not
   display the future cost matrix. At the complete endpoint, compare the full
   replay result with the immutable original run, including `report_hash`.
4. Reload. Account-file reselection is required again; the previous immutable
   report remains accessible with the changed-input warning. Change AUTO/SKIP
   and check report staleness before rerunning.
5. Use `?automatic=1`, reselect the account file, and Run. This goes through the
   actual preparation route and immutable publication. Expect four daily bars,
   V2, a completed cost matrix and quantities `[7, 7]`. The larger aggregated
   volume explains the difference from minute-bar partial fills.
6. Restart the backend with `--resume`, reload the UI and reopen the retained
   report/replay. Replaying from a saved prefix must reproduce the original
   endpoint without booking earlier fills again.

Only mark a check passed after executing it and inspecting its output. Keep
browser snapshots/screenshots, API result comparisons and candidate identities
under the chosen output directory. The fixture itself does not assert that a
human or automation completed this list.

## Market identity defect found during acceptance

Automatic preparation formerly published raw market names such as `usdm`,
while chart-context resolution canonicalized that name to `futures`. The new
snapshot could then be unavailable to its own logical binding, producing
`DEPENDENCY_NOT_READY` after successful acquisition. Native input planning now
uses the same chart-context normalization for exchange, market type and symbol
before deduplication and publication. Explicit Pine binding symbols are retained.

Regression coverage checks alias/case deduplication and installed-worker V2
automatic preparation for both `futures` and `usdm`, including funding, capacity,
retry identity and repeated launch. The original failed synthetic job is retained
in the local acceptance artifacts. Existing frozen job submissions and immutable
datasets are not rewritten by this fix. A subsequent lookup-side repair applies
the same canonical identity to older frozen manifests. Five legacy alias cases
check byte-preserving resolution, and a persisted `usdm` preparation failure is
retried after service restart with its original request and fingerprint. It
launches one real installed-worker run and retains the frozen manifest and bars.

The historical baseline on source `730fcf85` passed all 305 cases in its declared
21-module profile with zero skips and stable source/runtime/registry fingerprints.
After the identity fix, the preparation/context boundary suite passed 74 cases.
Those scopes and source identities remain separate. Native-preparation test
expectations now include the independently reexecuted cost accounts; only named
test waits were extended for cold worker/Parquet setup, with production deadlines
unchanged.

The controlled browser session on 2026-10-20 exercised the tracked fixture with
the production registry resolver: direct AUTO, automatic AUTO, changing to SKIP
with stale-result disclosure, file reselection, automatic SKIP, saved-prefix
replay, backend restart with retained SQLite state, reopening historical replay,
and restoring/replaying the saved prefix again. Both complete replay endpoints
matched the original report hash. The tracked page's console reported zero
errors. Local snapshots, API comparisons and source fingerprints are retained
under `output/playwright/pine-host-entry-20261020/`; this remains component-entry
evidence, not packaged acceptance.

The complete post-preparation-fix profile at `e0ab1718` passed all 307 cases,
zero failures/errors/skips, with unchanged source, runtime and registry hashes.
Its receipt is `output/pine-host/completion-goal/historical-20261020-02/receipt.json`.
The later legacy-lookup repair passed 83 preparation/context/qualification cases
against the fresh candidate managed install, with zero skips. Its receipt is
`output/pine-host/completion-goal/legacy-alias-fixed-tests.xml`. Its six new cases
are included in subsequent historical profiles rather than inheriting the
307-case result.

## Isolated candidate bundle checkpoint

A private, unpublished `.cspkg` was built from freshly built SDK/bridge wheels
and the retained core wheel whose native binary exactly matches the historical
worker. The production offline installer created an isolated managed install,
launched its worker, and checked both analysis and execution protocol probes.
The arithmetic probe emitted `[202, 204]`; its execution digest matches the
existing fixed release probe. The changed Host-requirements analysis digest is
recorded only in a private candidate lock. Published locks remain unchanged.

Bundle SHA256: `de125e2cd573759dc5f4290f0b65185c0d7f06eb8f9a6165650ed18448181019`.
All 56 Python/native payload files in the installed core, SDK and bridge match
the historical worker byte for byte. Local lock, wheel hashes, protocol output,
installer receipt and payload comparison are retained under
`output/pine-host/completion-goal/candidate-package/`. The core checkout revision
is contextual provenance; selection of the retained wheel by binary hash does
not attest that the wheel was freshly built from that checkout.

This qualifies isolated plugin installation and its bounded probe. The default
desktop recipe still pins the released core, so a complete candidate application
must use explicit candidate inputs and pass the later packaged-entry gate.

The first 313-case profile against this managed candidate stopped after 85
passing cases at a queued V2 chart `PROVIDER_TIMEOUT`. Source/runtime/registry
hashes were unchanged. A core release compilation was running concurrently;
resource contention is a hypothesis, not an established root cause. The failed
receipt, log and synthetic SQLite state are retained in
`output/pine-host/completion-goal/historical-20261020-03/`. After compilation
ended, the exact queued-chart case passed three separate executions under the
unchanged production budget. Those repeats, retained in
`output/pine-host/completion-goal/provider-timeout-recheck/`, do not qualify the
complete candidate profile. Keep this failure distinct from the 307-case
historical pass and the 83-case boundary pass.

The unchanged managed candidate then passed the complete 313-case profile,
zero failures/errors/skips and stable source/runtime/registry fingerprints, at
Host `5d44bbf5` in 1565.562 seconds. Receipt:
`output/pine-host/completion-goal/historical-20261020-04/receipt.json`.
This closes the complete controlled historical gate for that worker; the
default-sizing worker is a later, independently qualified input. Its entry
evidence is documented in [Pine defaults](pine-default-sizing.md).
