# CandleScope Pine Compatibility Plugin

This package bridges the independently released
[`pine-compat-runtime`](https://github.com/helenananaa/pine-compat-runtime) wheel to
the public `candlescope.script-runtime/1` SDK. It contains adapter code only: no
Pine engine source snapshot and no imports from CandleScope private backend
packages.

Bridge `0.4.0` is a source candidate targeting the official `pine-compat-runtime==0.3.3` wheels.
Installation checks run for Windows, Linux and both macOS architectures in the PR CI matrix.
Its producer manifest records tag `v0.3.3`, release commit
`c0ecc3bde5eece9c4f2a63c6785aec9c5e571acc`, and producer commit
`28f54b97a37422eef5357832bd73fb189b988d85`. This local qualification does not publish
a CandleScope release or establish TradingView equivalence.
`release/release-lock.json` pins the engine, SDK and bridge wheel hashes.
Previous locks are archived as `release-lock.0.2.0.json`, `release-lock.0.3.0.json`
`release-lock.0.3.1.json` and `release-lock.0.3.2.json`. Previous Linux and macOS locks are archived under `release-lock.0.3.2.*.json`.
Current platform locks are unpublished 0.4.0 candidates and require CI qualification.
The bridge selects analysis schema 6, runtime schema 9 and changes schema 4.
The host renders lines, labels, boxes, polylines, line fills, tables, character/arrow
plots, OHLC bars/candles and gradients through pane-owned chart primitives.
Colors, price/time coordinates, overlay routing, deletion and zoom are preserved.
Typography, label shapes and automatic table layout are approximations, not pixel
parity with TradingView. `E_RESOURCE_BUDGET` remains a runtime diagnostic.

Historical batches and one trailing forming bar are supported. WebSocket
subscriptions supply `options.pineSessionId` to retain native sessions across
forming replacements, confirmation and appends. A host that negotiated
`render.output-patch/1` and names the stream receives only the changed tail as an
`outputPatch` (see the SDK protocol); resets, recovery and an unknown base answer
with complete Render IR snapshots, as do all other hosts. With
`batch-execution.bars-patch/1` the host sends only the bars after those the runtime
already holds; the SDK rebuilds the full window, and bars kept from the previous
request are not normalized again. HTTP computations are independent. Analysis
exposes native
`meta.hostRequirements`. Requested contexts are discovered from compiled HIR,
including imported libraries and conservative nested-context expansion. Dynamic
symbols/timeframes require explicit context data; ambiguous warmup requires an
explicit `requestWarmupBars` entry. Missing or incomplete provider data fails
with a diagnostic. Provider stream leases are released when dependencies change
or the subscription ends.

Each sidecar retains eight live sessions and a durable SQLite observation journal
at `%LOCALAPPDATA%/CandleScope/pine/observations-v1.sqlite3` (override with
`CANDLESCOPE_PINE_JOURNAL`). LRU eviction, process restart and overlapping sliding
windows reconstruct recorded state, including `varip`; recovery is reported to
the UI. Duplicate reconnect observations are suppressed. Source, parameters,
metadata, confirmed history/clocks or explicit reset epoch changes restart state
with a visible notice. Failed rendering does not commit an observation. Journals
are bounded to 512 sessions, 256 MiB total and 100000 retained root bars; reaching
a limit fails explicitly. Journal cleanup is manual while the sidecar is stopped.
Ticks never observed while disconnected cannot be recovered. A reset button is
available in the indicator editor.

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
python -m pip install --no-index --find-links <candidate-wheel-directory> candlescope-plugin-pine-compat==0.4.0
python -m candlescope_plugin_pine_compat
```

The builder accepts this bridge, SDK `0.2.1`, and the pinned Pine engine wheel.
Pass `--lock release/release-lock.candidate.json`, three `--wheel` arguments and
`--output` for the candidate. Qualify installation and real sidecar execution
before activating it.

## Strategy installation boundary

Install the frozen bridge, SDK and engine wheel set through
`install_native_strategy_plugins.py --runtime pine --activate` after qualification.
This updates only Pine's native registry entry and preserves unrelated entries.
Installing the indicator CSPKG does not register native strategy execution.

For a locally qualified CSPKG, `first-party-local-overrides.json` beside the
indicator runtime registry can pin `{"schemaVersion":1,"runtimes":{"candlescope.pine-compat":
{"version":"0.4.0","bundleSha256":"sha256:<bundle digest>"}}}`. Startup checks the
managed installation and refuses a mismatched pin; it never downloads an unpublished
version or silently replaces it with the public 0.3.2 catalog entry. To roll back,
use the installer's previous activation and remove this Pine pin. Native installation
receipts retain `previous-native-registry.json` separately. Public download catalogs
are unchanged until a release is actually published.
