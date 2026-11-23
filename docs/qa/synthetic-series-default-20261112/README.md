# Default backend synthetic charts, 2026-11-12

Branch: `codex/synthetic-series-150`, based on main
`83778381611f67b0835a7dce8a1bde08f48b9837`. This extends the retained
[first-slice record](../synthetic-series-150-20261112/README.md); its default-off
description is historical. The current live default covers Heikin Ashi, Renko,
Point & Figure, Kagi and Line Break. This record does not close issue #150.

## Behavior

DataManager owns the five transforms through its synthetic namespace. The
frontend workspace data center shares a socket and immutable replica between
charts; each chart owns its range demand and renderer projection. Ordinary
K-lines and synthetic series are separate public data products. Live charts,
including strategy-research live charts, select backend computation without an
environment opt-in. `VITE_BACKEND_SYNTHETIC_SERIES=0` explicitly selects the
previous implementation at build time. Backend failures never silently run a
browser transform. Frozen/offline/replay views retain their own source owners.

Confirmed state and provisional overlays remain separate. Point & Figure and
Kagi replace their active column/leg at the same ordinal. Source continuity
inherits DataManager's calendar, including session breaks. Complete-window
snapshots pin one generation/revision and transfer in chunks of at most 5,000
records; the frontend publishes only the assembled snapshot, then accepts queued
updates. A 6,000-brick fixture verifies the prefix survives transfer and later
updates. Explicit output and shared retention budgets still apply.

## Passing checks

* Backend: 104 tests covering kernels, API, namespace, continuity, lifecycle and
  existing BarAggregator contracts. Focused cases include repeated forming-bar
  extension/retraction/close/amend, session gaps, independent Kagi section and
  Line Break references, and a pinned 6,000-brick snapshot with a queued update
  to 6,005 records.
* Frontend: 5,094 functional tests plus the isolated drawing-performance test.
  Replica tests cover atomic chunk assembly, generation mismatch rejection and
  preserving the complete 6,000-row prefix through a 6,001-row update.
* Differential migration oracle: 270 cases / 19,231 output records across all
  five types, fixed/window-ATR modes, source lengths 1/2/14/100/1500, precisions
  0/2/8 and reversal/line-count variants. OHLC, axis ordering, source lineage
  and renderer metadata match the retained TypeScript implementations. This
  comparison does not establish independent TradingView/exchange equivalence.
* Real Chromium mounts the default `MarketChartSurface` inside the workspace
  provider against real DataManager cache/query/event bus and HTTP/WS routes.
  All five browser mathematical functions throw if called. All five charts
  render and update, the socket reconnects, and two independent chart source
  stores share one frontend socket/backend instance/lease. Releasing one keeps
  the survivor updating; final unmount returns instances/leases to zero. No
  captured renderer errors or remaining workers. See [browser.json](browser.json).
* Typecheck, changed-code ESLint, production build, i18n validation and both
  architecture checks pass. Local checks are separate from cloud CI.
* Ad-hoc signed macOS arm64 unpacked package built successfully. All 121 normal
  packaged frontend files match the tested production build. Four changed
  backend entry/implementation files match repository sources. The bundled
  Python executes 36 kernel/API/namespace tests with imports asserted to resolve
  inside the package. Strict deep signature verification passes before and
  after that run. See [native-runtime.json](native-runtime.json).

The browser fixture controls market production and freezes only QueryEngine's
wall clock; it uses an isolated temporary data profile. It does not connect to
an exchange or a user profile. The native runtime tests use a separate profile,
`python -B` and `pytest --assert=plain`. An initial instrumented pytest run
created 31 assertion-cache files in bundled anyio. Those extra files were moved
to retained local QA artifacts; sealed resources did not change, and the
original signature verified again without resigning. Earlier failed runs remain
local evidence and are not counted as acceptance.

## Reproduction and boundaries

```sh
# From backend, with project dependencies installed:
python -m pytest -q tests/test_synthetic_series.py tests/test_synthetic_api.py
python scripts/qualify_synthetic_series.py
python -m uvicorn tests.synthetic_browser_server:app --host 127.0.0.1 --port 18150

# From frontend, with that isolated fixture running:
VITE_API_BASE=http://127.0.0.1:18150/api/v1 node scripts/frontend-script-integration.mjs --backend-synthetic
```

This establishes default-path component/browser and bundled-runtime evidence.
It does not establish normal native app save/exit/restart, Windows, notarization,
live-exchange correctness, cold-load latency or endurance/performance acceptance.
Issue #150 still owns indicator/strategy input adapters, durable checkpoints,
pinned replay inputs, output-cursor UI navigation and broader resource/platform
qualification. API output continues to report `strategy_qualified: false`.
