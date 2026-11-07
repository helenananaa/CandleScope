# Selected research version → independent chart run

Product source: `8249089410b1ff39ee55282ce881291b5e2262cb`.
Base: `f84f6b1082ab53ab968fb3f5d3f7e06028880c2a` (#260).
Refs #158; this is the qualified Python source/component flow, not closure of the full issue.

Selecting a saved research result must use that run's immutable program and
parameters, even after the research editor has changed. The reader fetches five
run-reference columns plus the referenced revision/bundle. It verifies compiled
and source hashes, reads Python editor files without executing them, and retains
Pine's frozen library sources. It does not restore report/account/checkpoint
history. Archived versions remain readable; missing, changed, unfinished,
external-bundle and retired-language versions fail explicitly.

The research result action stores only a durable run/version pointer. The main
chart dialog offers an explicit workspace/chart target. Applying persists a new
independent draft, then uses the existing atomic workspace command with the
captured workspace, window and document revision. A changed/closed target cannot
be overwritten. The target receives source, parameters, market, absolute range
and supported execution settings, with auto-run off and group linking removed.
It receives no research account, checkpoint, request key or Python approval.

The user selects History → Live, reviews Python permissions and explicitly
initializes through the existing ContinuousStrategyPanel / StrategyDataManager /
controller / Host kernel. New requests have independent account/run ownership.
Selected starting capital, fees, sizing, output, warmup and standard BAR realism
are retained. Profile checks compare fees and participation as exact decimals.

## Evidence

- `regression.log.gz`: **134 backend tests, 5 warnings**, including an actual
  Python research subprocess/Host run, immutable version reads, real Pine library
  compilation and continuing execution/API/provider/definition regressions.
- `frontend-tests-final.log.gz`: **4,932 tests + 1 isolated performance test**,
  no failures/skips. `desktop-tests.log.gz`: **130 tests**, no failures/skips.
- TypeScript, architecture, plugin-platform, 30-locale checks and build passed.
  Lint has zero errors and the pre-existing SingleChartPanes ref-cleanup warning.
  Build retains the existing large-chunk warning. Final correction tests: 59.
- `receipt.json.gz`: actual production return controls, workspace runtime,
  storage/editor and continuous panel in a browser composition fixture, backed
  by the real API, SQLite, Python worker, DataManager and execution Host.
  Only deterministic market BAR inputs and public stream leases are fixtures.
  No frozen-version, financial, provider or continuous API responses are mocked.
- Explicitly return the old selected version to **cell-2**, initially ETHUSDT,
  while cell-1 and its original program remain unchanged. No execution occurs
  until fresh Python consent and the initialize action.
- Existing account uses different source/parameters (`fast=9, slow=11`); returned
  account receives selected parameters (`fast=3, slow=7`) and initial capital
  **5000**, equity sizing **20%**, equal fees **3.5 bps**, slippage **2 bps**.
  Both independently process 20 → 25 BAR events; the existing definition stays
  identical and the completed research database record stays byte-for-byte equal.
- The actual renderer shows **25** processed events, position
  `1.998899864451675630769230768`, equity
  `5004.938134334740712671031105`. Equity matches a separate Decimal cash-plus-
  position-times-mark calculation against the committed account, not an equity
  sample. See `02-new-continuous-account.png` and `final-backend-audit.json.gz`.
- Renderer reload restores the same independent draft/new-run reference and 25
  events, with Python permission unchecked and no second create request. See
  `03-renderer-restored.png`.
- Zero page errors. Server shuts down normally, releases every fixture stream
  lease and preserves the research record. All **5 owned server/Vite/worker**
  PIDs were independently absent after shutdown (process receipts + shutdown).

The production button's normal `/?research-version=…` navigation is asserted.
The workflow then uses the composition fixture to isolate the production return
dialog/panel from unrelated public chart transports. This is **not packaged or
native full-quit/restart acceptance**, Windows qualification or live-market proof.
Source/helper hashes are retained in `source-manifest.json.gz`.

## Admission and remaining work

The return UI currently admits editor Python on native crypto 1m BAR, spot or
Binance linear V1, leverage 1/funding off, equity-percent sizing, TARGET_POSITION,
standard BAR realism and equal maker/taker fees. The browser account case above
is Binance spot. Advanced risk rules, unsupported precision/clocks, distinct fees,
Pine and retired runtimes are refused without modifying the research version.
The read-only version API additionally preserves valid Pine source/libraries;
this does not admit Pine to the continuous execution Host.

#158 stays open for Pine/other execution contracts and packaged/native
save/full-quit/restart coverage. No main merge or CI qualification is claimed.
Earlier failed browser/setup receipts remain under the development-goal output
directory; they were not relabelled as successful acceptance.

## Reproduction

Use the qualified SDK/core test interpreter, a fresh owned `DATA_DIR` and
`RESEARCH_RETURN_QA_PROFILE`, `PYTHONPATH=backend` and
`CORS_ORIGINS=http://127.0.0.1:23183` to run `server.py` on port 23184. Run Vite on
23183 with `VITE_API_BASE=http://127.0.0.1:23184/api/v1` and
`VITE_API_PROXY_TARGET=http://127.0.0.1:23184`. This matches the production
cross-origin authority boundary; a same-origin proxy GET does not carry Origin
and cannot authorize Python. Run `browser.mjs` with a fresh
`RESEARCH_RETURN_QA_OUT` and `CANDLESCOPE_PLAYWRIGHT_PACKAGE` pointing to an
installed playwright-core package. Stop the owned server/Vite normally and
verify child PIDs are gone. No public exchange access is needed.
