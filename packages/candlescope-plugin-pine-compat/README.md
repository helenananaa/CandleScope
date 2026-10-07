# CandleScope Pine Compatibility Plugin

This package bridges the independently released
[`pine-compat-runtime`](https://github.com/helenananaa/pine-compat-runtime) wheel to
the public `candlescope.script-runtime/1` SDK. It contains adapter code only: no
Pine engine source snapshot and no imports from CandleScope private backend
packages.

Bridge `0.3.0` targets the official `pine-compat-runtime==0.3.0` Windows
wheel, from tag `v0.3.0` commit `390e93afd87df6ac5a2aa64b940d612b9d49bab9`.
`release/release-lock.json` pins the engine, SDK and bridge wheel hashes.
The previous public lock is archived as `release-lock.0.2.0.json`.
The bridge selects analysis schema 6, runtime schema 9 and changes schema 4.
Gradient fills fail explicitly because Render IR v1 cannot represent them;
solid fills remain supported. `E_RESOURCE_BUDGET` is a runtime diagnostic.

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
python -m pip install --no-index --find-links <candidate-wheel-directory> candlescope-plugin-pine-compat==0.3.0
python -m candlescope_plugin_pine_compat
```

The builder accepts this bridge, SDK `0.2.0`, and the pinned Pine engine wheel.
Pass `--lock release/release-lock.candidate.json`, three `--wheel` arguments and
`--output` for the candidate. Qualify installation and real sidecar execution
before activating it.

## Strategy installation boundary

The official 0.3.0 wheel does not export `Program.run_external` or
`Program.historical_session`, required by CandleScope host matching and fixed
history replay. Keep the previously qualified Pine native installation.
The indicator upgrade is independent; never activate this wheel over that
native registry. Install Pyne alone with `install_native_strategy_plugins.py
--runtime pyne` to preserve the Pine entry.
