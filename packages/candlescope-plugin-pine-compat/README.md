# CandleScope Pine Compatibility Plugin

This package bridges the independently released
[`pine-compat-runtime`](https://github.com/helenananaa/pine-compat-runtime) wheel to
the public `candlescope.script-runtime/1` SDK. It contains adapter code only: no
Pine engine source snapshot and no imports from CandleScope private backend
packages.

Bridge `0.4.0` targets the official `pine-compat-runtime==0.3.3` wheels. Windows is locally verified;
Linux and macOS installation checks run in the PR CI matrix. Its producer manifest records tag `v0.3.3`, release commit
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
forming replacements, confirmation and appends. Transport still returns complete
Render IR snapshots. HTTP computations are independent. Analysis exposes native
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

Indicators accept imports, requested contexts, `input.source` selection from
OHLCV/derived price fields, explicit clocks and market metadata. Strategies use
the separate native or external entry point and registry. External matching uses
scheduled persistent observations (`pine-external/6`); CandleScope remains the
account/fill authority. Fixed calculation windows are mapped back to the frozen
chart timeline. Dynamic windows that need account-feedback discovery/rebasing
remain unsupported and fail explicitly.

## Host inputs

The indicator editor saves the JSON object in `params.__pineHost`; IPC carries it
as `options.pineHost`. Native runs freeze `host_inputs` in the run identity and
accept library sources and requested dataset references in their existing fields.
Exchange metadata is filled when available; inverse contracts are rejected.
The runtime still uses documented synthetic defaults for absent metadata, exposed
as `meta.symbolMetadataSource`; supply authoritative values when those fields matter.

```json
{
  "chartMetadata": {"minMove": 1, "priceScale": 100, "pointValue": 1,
    "quantityStep": "0.001", "minContract": "0.001", "currency": "USDT"},
  "libraries": {"owner/Math/1": "//@version=6\nlibrary(\"Math\")\nexport twice(float x) => x * 2"},
  "requestWarmupBars": {"BINANCE:ETHUSDT:60": 100}
}
```

Indicator-only `contexts` entries contain `symbol`, Pine `timeframe`, OHLCV `bars`
with timestamps in **seconds**, and optional `forming`. A forming provider row is
fed as a forming update, not confirmed history. `executionTimes` are **milliseconds**,
one per root bar. The host supplies historical bar-close times and the observation
clock for live `timenow`; these are host evaluation clocks, not reconstructed ticks.
External matching owns each scheduled clock and rejects a separate `executionTimes`.
`symbolMetadata`, `currencyRates`, `barCalendars`, and `sessionWindows` use the
Pine 0.3.3 public schema. FX/calendars/session windows must be supplied explicitly;
there is no exchange-calendar or FX download service. External account window
rules belong to the host and cannot be supplied as Pine `sessionWindows`.

## Notifications

The editor's opt-in checkbox routes confirmed live Pine alerts into the existing
notification center. A generated Pine rule controls delivery channels, pause state,
cooldown and trigger limits. Initial history, previews, HTTP computations and
replayed closed bars never notify. Event IDs are deterministic and deduplicated
by the persistent alert store; an active chart subscription is required. Editing
the rule's target or expression disconnects it from the original Pine producer.

Run locally:

```powershell
python -m pip install --no-index --find-links <candidate-wheel-directory> candlescope-plugin-pine-compat==0.4.0
python -m candlescope_plugin_pine_compat
```

The builder accepts this bridge, SDK `0.2.0`, and the pinned Pine engine wheel.
Pass `--lock release/release-lock.candidate.json`, three `--wheel` arguments and
`--output` for the candidate. Qualify installation and real sidecar execution
before activating it.

## Strategy installation boundary

Install the frozen bridge, SDK and engine wheel set through
`install_native_strategy_plugins.py --runtime pine --activate` after qualification.
This updates only Pine's native registry entry and preserves Pyne's entry.
Installing the indicator CSPKG does not register native strategy execution.

For a locally qualified CSPKG, `first-party-local-overrides.json` beside the
indicator runtime registry can pin `{"schemaVersion":1,"runtimes":{"candlescope.pine-compat":
{"version":"0.4.0","bundleSha256":"sha256:<bundle digest>"}}}`. Startup checks the
managed installation and refuses a mismatched pin; it never downloads an unpublished
version or silently replaces it with the public 0.3.1 catalog entry. To roll back,
use the installer's previous activation and remove this Pine pin. Native installation
receipts retain `previous-native-registry.json` separately. Public download catalogs
are unchanged until a release is actually published.
