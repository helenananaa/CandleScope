# Indicators follow the displayed chart input

This extends the default backend synthetic series implementation on
`codex/synthetic-series-150`, after base `969209b53`. Ordinary price styles retain
normal bars. Heikin Ashi, Renko, Point & Figure, Kagi and Line Break now default
indicator input to the same backend snapshot as the main chart. The ordinary
hosted indicator owner receives no definitions in this mode. Builtins and Pine
compute on the backend; explicitly frontend JavaScript indicators keep their
isolated browser executor and consume the same displayed rows.

The API resolves prices from an exact DM series/generation/revision, not submitted
synthetic prices. Ordered execution keys keep same-time bricks distinct without
turning them into script dates. Script clocks, explicit requested contexts and
revealed read cutoffs remain real. Output alignment, colors, pane legends and
Pine index-based scenes preserve every display row. Explicit Pine time-based
objects retain their source-clock coordinates. Unsupported plugin chart-clock
contracts produce diagnostics and preserve definitions. Pyne remains retired.

`close-source/2` adds a documented volume allocation: source volume accumulates
until a display cohort is emitted and is divided among its records. HA volume is
unchanged. This is estimated display volume, not tick-derived volume or a claim
of TradingView parity. The old TypeScript price oracle was not changed to absorb
this intentional contract change; volume conservation is checked separately.

## Current evidence

- [Backend tests](backend-tests.txt): 90 pass, covering authoritative prices,
  revision/identity rejection, source ownership, all transforms, volume, local and
  replay source regressions, builtin batches, source-clock provider ranges and
  continued Pyne rejection.
- [Installed Pine tests](installed-pine-tests.txt): 24 pass. The SDK request travels
  through the actual installed sidecar's JSON-RPC entry point with `-I`; equal
  source times retain independent SMA/history values, real `time`, preview
  flags, explicit requested contexts, rewind and fresh-state reconstruction.
  Ordinary candle sessions and event-request strategy regression cases also pass.
- [Browser](browser.json): real production-minified Chrome, nine cases: five
  transforms, parameter change, replay, forward and captured rewind. Builtin and
  isolated JS MAs match an independent adjacent-display-row mean; JS receives
  real source clocks. No raw hosted indicator sockets, remaining workers or
  uncaught browser exceptions. The production wrapper and chart renderer mount
  together under the workspace data manager.
- [Migration oracle](migration-oracle.json): 270 cases / 19,231 rows compare prices
  and lineage against the unchanged TypeScript transforms. HA volume parity and
  the new non-HA volume conservation check pass independently.
- Full frontend regression: 5,102 functional tests plus the isolated performance
  gate pass. Final focused frontend tests and color tests also pass; type/build
  results are recorded in `checks.json`. The isolated drawing performance test
  initially failed during concurrent compiler/test work (p95 1.954 ms), then
  [passed](performance-retry.txt) at p95 0.592 ms after that work drained. The
  drawing implementation was not changed; this is not synthetic-series speed
  qualification.
- Default source-build packaging successfully builds and installs/verifies both
  runtime bundles for Darwin arm64. [Manifest](bundle-manifest.json) and exact
  [artifact hashes](artifacts.json) identify the unpublished source build. Public
  release locks were not rewritten to invent published binaries.

The earlier signed QA app and its receipts under `synthetic-series-pinned-20261112`
remain historical. This iteration verifies source/browser behavior and packaged
runtime processes; it does not establish installed native UI save/exit/restart,
Windows, notarization, live-exchange or long-duration performance acceptance.
Strategy signal/broker inputs still follow their explicit existing contracts;
`strategy_qualified` remains false. Durable synthetic checkpoints and broader
issue #150 requirements remain open.

## Reproduction

From the isolated task checkout:

```sh
cd frontend
npm test
npm run typecheck
npm run build
cd ..
.venv/bin/python -m pytest -q backend/tests/test_chart_indicator_input.py backend/tests/test_synthetic_series.py backend/tests/test_synthetic_api.py backend/tests/test_synthetic_pinned.py backend/tests/test_indicator_compute_batch.py backend/tests/test_pine_host_inputs.py backend/tests/test_pyne_removal.py
.venv/bin/python backend/scripts/qualify_synthetic_series.py
.venv/bin/python frontend/scripts/prepare-desktop-plugins.py --output output/chart-indicator-plugin-build --cache frontend/.desktop-runtime/plugin-build --qualification
```

Install the exported SDK/bridge/engine wheels into an isolated Python 3.12
interpreter, then set `NATIVE_TEST_PINE_PYTHON` to that interpreter for
`backend/tests/test_native_chart_indicator_input.py` and
`backend/tests/test_pine_indicator_observations.py`; run the plugin's
`test_chart_indicator_input.py`, `test_native_sessions.py` and
`test_event_strategy.py` alongside them. The release host-contract qualification
entry point now requires the ordered-chart contract and these gates.

For the browser fixture, start `tests.chart_indicator_browser_server:app` with
uvicorn from `backend`, then run from `frontend`:

```sh
VITE_API_BASE=http://127.0.0.1:18931/api/v1 node scripts/frontend-script-integration.mjs --chart-indicator --out ../output/chart-indicator-browser-complete
```
