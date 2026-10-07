# CandleScope Pine Compatibility Plugin

This package bridges the independently released
[`pine-compat-runtime`](https://github.com/helenananaa/pine-compat-runtime) wheel to
the public `candlescope.script-runtime/1` SDK. It contains adapter code only: no
Pine engine source snapshot and no imports from CandleScope private backend
packages.

Bridge `0.3.1` targets the official `pine-compat-runtime==0.3.1` Windows
wheel, from tag `v0.3.1` commit `14a2ab89c08a85a76d769e9fbe2f13f9c958342d`.
`release/release-lock.json` pins the engine, SDK and bridge wheel hashes.
Previous public locks are archived as `release-lock.0.2.0.json` and `release-lock.0.3.0.json`.
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
remain rejected by the indicator sidecar. Strategies use the separate native or
external strategy entry point and its registry.

Run locally:

```powershell
python -m pip install --no-index --find-links <candidate-wheel-directory> candlescope-plugin-pine-compat==0.3.1
python -m candlescope_plugin_pine_compat
```

The builder accepts this bridge, SDK `0.2.0`, and the pinned Pine engine wheel.
Pass `--lock release/release-lock.candidate.json`, three `--wheel` arguments and
`--output` for the candidate. Qualify installation and real sidecar execution
before activating it.

## Strategy installation boundary

The official 0.3.1 wheel exports `Program.run_external` and
`Program.historical_session`, resolving the 0.3.0 installation blocker.
Install the frozen bridge, SDK and engine wheel set through
`install_native_strategy_plugins.py --runtime pine --activate` after qualification.
This updates only Pine's native registry entry and preserves Pyne's entry.
Installing the indicator CSPKG does not register native strategy execution.
