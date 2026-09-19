# CandleScope Pine Compatibility Plugin

This package bridges the independently released
[`pine-compat-runtime`](https://github.com/helenananaa/pine-compat-runtime) wheel to
the public `candlescope.script-runtime/1` SDK. It contains adapter code only: no
Pine engine source snapshot and no imports from CandleScope private backend
packages.

Development bridge `0.3.0.dev1` targets `pine-compat-runtime==0.3.0rc1`, built from
`a481b4644c142badcf9e1bc5430bc3a5f7f2a733`. Select the Windows wheel by SHA-256 in
`release/release-lock.candidate.json`; a version alone cannot identify a candidate.
The original `release-lock.json` retains the historical public v0.2.0 bundle.

Historical batches and one trailing forming bar are supported. WebSocket
subscriptions supply `options.pineSessionId` to retain native sessions across
forming replacements, confirmation and appends. Transport still returns complete
Render IR snapshots. HTTP computations are independent. Analysis exposes native
`meta.hostRequirements`; this does not grant the requested external capabilities.

Each sidecar retains at most eight recently used sessions. Changed history windows,
source or parameters, eviction and process restarts replay history and report
`meta.sessionReset=true`. Cold starts use mid-bar admission; earlier ticks and
varip state cannot be recovered. No persistent recovery or indefinite retention is promised.

External `request.*` data, imports, strategies and unmapped native drawing objects
remain rejected. The backend Pine strategy provider accepts only the unchanged
Long Flat example; arbitrary strategies are not connected to the native engine.

Run locally:

```powershell
python -m pip install --no-index --find-links <candidate-wheel-directory> candlescope-plugin-pine-compat==0.3.0.dev1
python -m candlescope_plugin_pine_compat
```

The builder accepts this bridge, SDK `0.2.0`, and the pinned Pine engine wheel.
Pass `--lock release/release-lock.candidate.json`, three `--wheel` arguments and
`--output` for the candidate. Qualify installation and real sidecar execution
before activating it.
