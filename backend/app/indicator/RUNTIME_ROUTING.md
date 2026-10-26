# Indicator runtime routing

`runtime-registry.json` records verified plugin installations. `indicator-runtime-routes.json` maps language IDs to runtime IDs. The default route is:

```json
{"schemaVersion":1,"routes":[{"language":"pine","mode":"sidecar","runtimeId":"candlescope.pine-compat"}]}
```

The route file lives beside the activation registry, under `%LOCALAPPDATA%/CandleScope/plugins` on Windows or `$XDG_DATA_HOME/candlescope/plugins` (otherwise `~/.local/share/candlescope/plugins`) on Linux. Override it with `CANDLESCOPE_INDICATOR_RUNTIME_ROUTES`. Routes are read at startup, not hot-reloaded. An explicitly selected missing or invalid file fails startup.

New hosted scripts default to Pine. Community sidecar languages must explicitly advertise their language, `batch-execution/1`, and `render.line-series/1` capabilities. Production has no in-process language adapter; `legacy` and `shadow` routes therefore cannot be used as production fallbacks. Missing required runtimes fail startup. Runtime failures after startup return an unavailable error rather than silently changing the executor.

`GET /api/v1/indicators/runtimes` exposes validated routes and public SDK descriptors, including optional `meta.ui.languages.<language-id>.monacoLanguage` and `starterSource` hints. These are data only; plugins cannot inject editor code. The catalog excludes launch commands, paths, PIDs, and stderr.

HTTP compute, range, range/batch, and WebSocket script subscriptions share `IndicatorRuntimeService`. CandleScope owns the market context, bars, result serialization, cache identity, and subscription lifecycle. Cache identity includes language as well as source. Built-in indicators continue to use the local indicator engine.

Pyne has been removed. Its scripts, route entries, strategy providers and security endpoint are unsupported; source code is never translated into Pine. Remove retired entries from explicitly configured route files. Historical evidence under `docs/evidence` records earlier releases, not current capabilities.

Shared transport budgets use `SCRIPT_MAX_BARS`, `SCRIPT_TICK_RECOMPUTE_MAX_BARS` and `SCRIPT_HTTP_THREAD_*`. Plugin-specific execution policy belongs to each runtime.

To activate a community language, install and activate its verified `.cspkg`, add an explicit `sidecar` route, restart CandleScope, and check `/health`, `/api/v1/indicators/runtimes`, and `/api/v1/indicators/diagnostics`. Setting `CANDLESCOPE_PLUGIN_HOST_ENABLED=0` disables the host but does not make configured sidecar routes valid without it.
