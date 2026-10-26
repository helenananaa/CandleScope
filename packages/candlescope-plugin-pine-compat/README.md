# CandleScope Pine Compatibility Plugin

This package bridges the independently released
[`pine-compat-runtime`](https://github.com/helenananaa/pine-compat-runtime) wheel to
the public `candlescope.script-runtime/1` SDK. It contains adapter code only: no
Pine engine source snapshot and no imports from CandleScope private backend
packages.

Bridge `0.3.2` targets the official `pine-compat-runtime==0.3.2` wheels for
Windows, Linux, macOS Apple Silicon and macOS Intel.
`release/release-lock.json` pins Windows; the `release-lock.linux-x86_64.json`,
`release-lock.macos-arm64.json` and `release-lock.macos-x86_64.json` locks pin
the other targets, including engine release identity and all wheel hashes.
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

The current source candidate adds explicit execution clocks, cached source
analysis, and exchange price grids. `syminfo` price-grid values require actual
host metadata instead of synthetic defaults. Native backtests and replay freeze
execution clocks at bar close; indicators use the host observation clock.

Indicator `request.security` and `request.security_lower_tf` can read complete,
already-local standard candles from exact exchanges and market types. Literal
and inherited chart selectors are resolved; dynamic/nested contexts require a
finite declaration in `params.__pineContexts` / `options.pineRequestContexts`
(at most 16). Missing data fails explicitly; execution does not initiate a
download or substitute another market. Versioned indicator imports are supplied
as an explicit `options.pineLibrarySources` map; the editor persists that map in
`params.__pineLibraries`, including preview, range requests and subscriptions.

The current development-core candidate (`b9200480e`, requirements schema 3)
also accepts explicit effective currency rates through `pineCurrencyRates`
(indicator params `__pineCurrencyRates`) or frozen native `currency_rates`.
Their `effectiveTime` is the actual availability time in Unix milliseconds;
future frames do not affect earlier queries. Missing pairs remain input errors.
Chart quote currency comes from exchange metadata or explicit chart metadata,
never from a symbol-name guess. Native batch and fixed-history replay share
these inputs. Chart revisions and host-matching runs also freeze library sources.
These are source-candidate capabilities, not a published-plugin release claim.
Analysis, compilation and session identities include the full library sources;
public results expose dependency SHA-256 digests. Transitive imports require all
source files. The host does not fetch libraries from the internet.

Native drawing snapshots now use `collections.objects.pineScenes` and the public
`drawings` payload lane. The chart renders vertical/arrow lines, boxes, labels,
curved/filled polylines, linefills and viewport-positioned tables with merged cells.
Snapshots replace object state, including deletions; older range responses cannot
replace a newer observation. Coordinates retain the execution window and original
chart times across gaps, prepend and replay. Fonts and curve interpolation use
host rendering; pixel parity with TradingView is not claimed. Native plotchar, plotarrow, OHLC
bars/candles and vertical gradient fills use the same scene renderer.
The bridge requires `render.native-scene/1`; older hosts reject the capability
instead of silently dropping these objects.

New chart strategy revisions use `PINE_ENGINE` / `pine-engine-chart-v1`, calling
the real engine in an isolated process with actual Host account feedback. The
profile supports closed-bar market entries/closes, one entry ID and net positions;
price orders, pyramiding, requests and intrabar callbacks use the separate native
strategy workbench. Frozen `PINE_SUBSET` revisions keep their prior semantics.
Compiled revisions bind the installed engine identity; reinstalling requires
recompilation. Host checkpoints retain the visible bars/account transcript.

`pine-external/6` and chart evaluators negotiate append transport, including
stable requested contexts and confirmed fill-pass groups. The companion isolated
engine candidate `0.3.2+external.1` adds `Program.external_session().append(...)`:
committed state is retained and only new bars/account frames execute. Frozen
request changes, historical corrections, unconfirmed-pass replacement, process
restart and dataset-end-dependent scripts rebase deliberately. `barstate.islast`,
`last_bar_index/time`, visible-chart builtins and `calc_bars_count` cannot safely
reuse a growing historical prefix. Synthetic ticker contexts also retain replay.
Older engines keep the batch fallback. Outputs are still full snapshots; this
removes repeated interpreter evaluation, not all history-sized transport costs.

Build the companion engine from upstream branch `codex/external-incremental-host`
(base `28ecae3c645e9269e2099d27cc9abbb1f52ee9ea`) with `maturin build --release`.
`qualify_source_candidate.py --engine-wheel <candidate.whl>` builds and verifies
a separately labelled offline CSPKG against that exact wheel digest. Omit that
option to qualify against the unchanged official engine.

These are source-candidate capabilities, not a replacement for the published
0.3.2 CSPKG. Published release locks and active user installations are unchanged.

Run locally:

```powershell
python -m pip install --no-index --find-links <candidate-wheel-directory> candlescope-plugin-pine-compat==0.3.2
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
This updates only Pine's native registry entry and preserves unrelated entries.
Installing the indicator CSPKG does not register native strategy execution.
