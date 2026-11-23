# Frozen and replay backend computation, 2026-11-12

Branch `codex/synthetic-series-150`, extending default-path commit
`c6a013a42745c00c42dac8567d6b700b33b883d7`. Prior records remain historical:
[first slice](../synthetic-series-150-20261112/README.md),
[live default](../synthetic-series-default-20261112/README.md).

## Delivered behavior

All five synthetic chart types use backend calculation for saved run results,
frozen snapshots, pinned local library candles, replay training/review, history
study and quick trade review. Source-specific ownership and captured progress
remain intact. Indicators and strategy execution retain their existing inputs.

Saved results bind config/report/chart receipts; saved frozen views additionally
bind dataset/epoch/snapshot identity. Local display reads use the pinned revision,
including host snapshots and trade-derived candles, without broadening the
separate imported-candle comparison contract. Replay reads use the existing
training history/source-bucket/tape owners, with captured time and source sequence.
An old captured observation remains reproducible after playback advances.

Browser-owned history uses an explicitly client-captured display prefix, admitted
through a separate bounded registration endpoint. Hidden future rows do not
reach that registration. Content identities select immutable calculation inputs;
these copies are not trusted exchange finality or executable strategy inputs.
Registration and every consumer enforce local-origin access, including shared
instance attachment. A 32-entry LRU shares the backend memory budget. Reconnect
re-registers evicted/restarted copies, and pending uploads cancel with the chart.

The offline DataManager core owns synthetic calculation even with no live market
DataManager. Pinned/captured instances open no live subscriptions or backfill.
Historical partial coarse buckets retain their flags; immutable kernels accept
the frozen window and reject live mutation. Output still reports
`strategy_qualified: false`.

## Passing evidence

* 104 backend tests in the broader kernel/API/namespace, saved runtime,
  local-data and replay history/tape regression group. Following the final
  local-reader change, 38 targeted local/source/chart-context tests pass,
  including pinned host snapshots and imported trade-derived candles.
  Another 13 offline-startup, shutdown-order/failure and plugin-lifecycle checks
  pass, including synthetic cleanup before dependent runtime shutdown.
* Backend scenarios include unchanged old-revision results after current-pointer
  changes; saved identity mismatch rejection; replay forward/old-prefix
  reproducibility; time/sequence fencing; real 1m/2m tape prefixes including
  forming and historical partial buckets; no account mutation; shared seed
  cancellation; capture LRU eviction/re-registration, access checks and release.
* Frontend: 5,098 functional tests plus the isolated drawing-performance test.
  Added checks cover source identity separation, captured-prefix registration,
  reconnect re-registration, rewind fences and disposal during an upload.
* Real minified Chromium: all five chart types across five non-live origins
  (25 combinations), plus the existing live-default suite. The fixture uses real
  saved backtest/local revision/replay services and real DataManager HTTP/WS.
  All five frontend mathematical functions throw if invoked. Charts render,
  replay advances and returns to the captured prefix with identical rows and
  generation, and final backend instances/live leases return to zero. No captured
  renderer exceptions or remaining workers. See [browser.json](browser.json).
* Frontend typecheck and changed-code ESLint pass (the pre-existing chart
  cleanup-ref warning remains); frontend/backend architecture checks pass.

The macOS arm64 unpacked QA package passes 46 tests using its bundled Python
and backend modules in isolated profiles. Eight changed backend modules match
the final source. All 175 packaged frontend files match the normal production
build. Strict deep signature verification passes before and after the
write-disabled runtime tests. See [runtime receipt](native-runtime.json) and
[frontend asset receipt](native-assets.json). The final local-data module changed
during the initial package build; its exact source and checked-hash bytecode were
synchronized before resealing the isolated ad-hoc QA app with its existing
entitlements/flags. This is bundled-runtime evidence, not normal native UI
save/exit/restart acceptance.

## Reproduction and limits

```sh
# From backend:
python -m pytest -q tests/test_synthetic_pinned.py tests/test_synthetic_series.py tests/test_synthetic_api.py
python -m uvicorn tests.synthetic_pinned_browser_server:app --host 127.0.0.1 --port 18150

# From frontend, with that isolated backend running:
VITE_API_BASE=http://127.0.0.1:18150/api/v1 node scripts/frontend-script-integration.mjs --backend-synthetic-pinned
```

Fixture data and profiles are isolated; no live exchange or user dataset is
queried. An early browser run reached the captured-step check after its fixture
controller lease expired; the fixture now reacquires immediately before its
command. Earlier failed development checks remain in local output and are not
counted as acceptance. Cloud CI is separate from completed local checks.

Temporary captured copies are re-uploaded after backend restart, not durable
synthetic checkpoints. Window capture, source reads and reseeding remain bounded
history-sized work; no constant-time playback or latency/endurance claim follows.
Windows, notarization, native save/exit/restart and full platform acceptance are
not established. Issue #150 remains open for indicator/strategy adapters,
checkpoint/restart and broader scheduling/performance/platform requirements.
