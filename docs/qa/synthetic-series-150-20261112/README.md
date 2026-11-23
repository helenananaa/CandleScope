# Issue #150 — first source migration slice, 2026-11-12

Base: main `83778381611f67b0835a7dce8a1bde08f48b9837`.
Candidate branch: `codex/synthetic-series-150`.
This record covers source/component/browser evidence. It does not close #150.

## Implemented candidate

Backend-owned HA and close-source Renko, shared DataManager instances/leases,
bounded history preparation and source events, confirmed/preview separation,
revision/generation resnapshots, ordinal pages and replacement patches.
The frontend workspace owns immutable shared replicas; chart bindings own their
range demand and renderer/lineage mapping. Enabled candidates do not run a
browser transform when their backend fails.

The normal live-reference entry is gated by
`VITE_BACKEND_SYNTHETIC_SERIES=1`, default off. It retains explicit
`display-window/1` semantics. Anchored fixed-parameter kernels have a separate
identity, but all API output still says `strategy_qualified: false`.

## Checks

* 84 focused backend tests passed: new kernel/service/API checks plus existing
  DataManager namespace, GC, continuity and BarAggregator contracts. This
  includes immutable consumer payloads, capacity rejection without partial
  adoption, source subscription recovery, cancellation during a shared seed,
  HTTP generation-checked pagination and ASGI cancellation-safe release.
* Offline migration comparison passed 45 cases / 6,775 output records:
  source lengths 1/2/14/100/1500, price precisions 0/2/8, HA, fixed Renko and
  window-ATR Renko. Compared prices, ordering, lineage and Renko preview/config
  metadata with the retained TypeScript reference. This is a migration oracle,
  not independent exchange or TradingView equivalence.
* Real minified Chromium mounted the production `SingleChartPanes` against
  the real DataManager cache/query/event bus and synthetic HTTP/WS routes.
  Only market production was controlled; no exchange/network history source
  or user profile was used.
* That browser fixture replaced both browser mathematical implementations with
  throwing functions. Renko rendered the independent 9-brick reference and
  changed to 11 on a forming update. Switching to HA rendered five records
  with close 116; another forming update produced close 118. Closing the chart
  returned backend instances and stream leases to zero. No captured renderer
  exceptions or remaining workers. See [browser receipt](browser.json).
* Final full frontend run: 5,092 functional tests passed, followed by the
  isolated drawing-performance test. Targeted
  representation/platform/replica/i18n checks also passed (341 at that
  checkpoint). The earlier full run found the two new untranslated pt-BR/Korean
  status strings; both were translated before the passing final run.
* Frontend typecheck, changed-code ESLint (zero errors), production build,
  i18n validation and frontend/backend architecture checks were run. The
  pre-existing chart cleanup-ref ESLint warning is separate from this change.

Reproduction:

```sh
# From backend, using the task's environment:
python -m pytest -q tests/test_synthetic_series.py tests/test_synthetic_api.py
python scripts/qualify_synthetic_series.py
python -m uvicorn tests.synthetic_browser_server:app --host 127.0.0.1 --port 18150

# From frontend, while the isolated fixture is running:
VITE_API_BASE=http://127.0.0.1:18150/api/v1 node scripts/frontend-script-integration.mjs --backend-synthetic
```

The fixture freezes only its QueryEngine wall clock to keep the controlled
forming bar in the same bucket during cold calendar/bootstrap work. Its timeout
is not a latency budget, and these runs establish no cold-load or performance
percentile. Failed early fixture/harness runs remain in local output alongside
the passing run; their results were not counted as acceptance.

## Open requirements

Point & Figure/Kagi/Line Break; persistent checkpoints and seed migration;
production deep ordinal paging; fixed dataset/replay version binding;
indicator and strategy input selection/adapter qualification; reducing retained
array copying/scanning and range reseeds; common resource accounting and process
isolation qualification; multi-chart/reconnect/endurance/performance matrices.

No actual installed macOS package, save/exit/restart, Windows package, live
exchange or notarization acceptance is established by this batch. The full
original #150 requirements remain authoritative.
