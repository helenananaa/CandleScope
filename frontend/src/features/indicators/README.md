# Indicators Feature

`features/indicators` owns indicator state and rendering outputs for the active
chart session. It consumes chart-session and market-data contracts, then exposes
stable view/action/status objects to the app shell.

## Public Contract

`useIndicatorRuntime({ session, marketData, candleUpColor, candleDownColor, onIndicatorRemoved })`
exposes:

```js
{
  view: {
    activeIndicators,
    mainOverlayLines,
    subPanes,
    markers,
    fills,
    hlines,
    bgcolors,
    barcolors,
    signals,
    paramSchemas,
  },
  actions: {
    addIndicator,
    removeIndicator,
    toggleVisibility,
    updateIndicatorParams,
    updateIndicatorScript,
    recompute,
    ensureVisibleIndicatorRange,
    requestIndicatorRange,
  },
  status: { computing, realtimeMode },
}
```

The hook returns only `view`, `actions`, and `status`; callers must not depend
on legacy flat fields.

## Execution Routing

Indicator execution is hosted by default. Existing builtin, Pyne, and custom
script definitions with no `executionTarget`, or with
`executionTarget: "hosted"`, use the hosted WebSocket plus
`/indicators/range/batch` history path. The backend owns K-line lookup and can
share it across the range batch.

`executionTarget: "local"` is an explicit internal opt-in. "Local" means the
controller sends the newest 2,000 chart OHLCV bars directly to the backend; it
does not mean browser-side execution. That path uses
`/indicators/compute/batch`. The catalog UI does not currently select it.
Hosted and explicit-local definitions fail closed when they lack a valid engine
name or non-empty script. The legacy single-item `/indicators/compute` endpoint
is not used by the current controller.

The two batch contracts are intentionally separate:

- Hosted range work is grouped by exchange, market, symbol, interval, demand
  scope, and demand generation. A 40 ms coalescing window produces ordered
  chunks of at most 32 items, with one physical request at a time per group.
- Explicit-local compute sends 1-32 unique `clientId`/`jobKey` items with one
  shared context and one shared OHLCV field per HTTP request. Larger plans are
  split into parallel chunks of at most 32, so each chunk carries its own OHLCV
  field. Response count and identities must match exactly; an item-level engine
  error is isolated in that item's payload.

### Frontend JavaScript

`frontend-js` is a first-party browser language, shown as JavaScript (Frontend)
in the existing editor. It is distinct from community runtime language IDs.
`bars`, `params`, and `plot(name, values, { pane, color })` form its window-plot
API. A values array contains exactly one finite number or null per input bar;
the Host assigns timestamps from the supplied window. Up to eight line plots
target `main` or `separate`. There are no order, account, DOM or Host API hooks.

The normal live compute controller supplies its newest 2,000 chart bars. Replay
supplies only its revealed, loaded display window. The browser runtime accepts
at most 50,000 bars and rejects larger input explicitly. This language does not
claim a canonical full-history mathematical seed: loading a different window
can change a recursive script's values. Builtin canonical replay is unchanged.

Both live and provided-bars compute intercept this language before either
backend executor. The existing coordinator owns generations, cancellation,
errors and immutable cache publication; saved language/source/parameters reuse
custom-indicator persistence. Only this explicit language avoids hosted WS and
history range requests. A backend plugin's `javascript` language keeps its own
route.

User source is data sent to a dedicated Worker inside a first-party sandbox
frame with an opaque origin, restrictive CSP and no Host bridge. Blob workers
inherit that CSP. The parent validates numeric outputs independently; it never
evaluates source. DOM/Node/storage/network and child-worker capabilities are
unavailable. There are two active workers across all charts and 32 queued jobs;
queued cancellation removes work immediately. A two-second execution timeout
or cancellation terminates the worker through its owner before releasing its
slot (bounded owner destruction if acknowledgement fails). Successful jobs also
terminate their worker. These are execution/input/output limits, not a browser
process memory quota against arbitrary hostile code.

The isolated bootstrap and CSP behavior are covered by real-browser tests,
including infinite loops and subsequent successful work. Browser standards:
[Worker CSP inheritance](https://developer.mozilla.org/en-US/docs/Web/API/Web_Workers_API/Using_web_workers#content_security_policy)
and [opaque sandbox origins](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe#sandbox).

## Work, Cache, and Hydration Ownership

The explicit-local lifecycle includes the dataset and normalized chart context,
the exact bounded OHLCV content sent to the backend, and the local execution
plan. Each bounded job key also includes indicator id, mode, name, script,
security mode, and canonical parameters. Same-key callers join one physical
batch and only its owner publishes results. A lifecycle change aborts old work,
advances its epoch, clears completed ownership, and fences late responses.

Successful compute is marked complete only after its immutable result is stored
in the indicator cache. A new physical attempt first removes the old
explicit-local cache entry. Transport failure therefore clears the submitted
indicator's lines and auxiliary trading outputs instead of showing stale data.
Terminal item errors remain visible across cache hydration and stop automatic
retry until the lifecycle changes or the user forces recomputation.

Cache identity includes execution target, so hosted and explicit-local results
never share an entry. The write boundary deep-copies and freezes owned data.
Within one `contentVersion`, payload and metadata reads return stable read-only
views without cloning; a real mutation publishes a new version and view.

At a hydration ownership change, a layout effect synchronously resets old
auxiliary outputs and publishes cache-owned line/schema references. A cache miss
clears stale line data but preserves an explicit-local terminal error. A later
task, deduplicated by lifecycle, content signature, and content version, reads
the latest cache again before refreshing lines/schema and hydrating markers,
fills, hlines, bgcolors, barcolors, and signals in one reducer pass. Stale tasks
are fenced, and unchanged output lanes retain their references.

Hosted range lifecycle is `series + demand.scope + demand.generation`. Revision
supersession inside that lifecycle marks prior work stale without unnecessarily
rebuilding the scheduler epoch.

## Internal Ownership

- `activeIndicatorStore.ts` owns active indicator persistence and mutation.
- `useIndicatorCatalogRuntime.ts` owns preset/custom indicator catalog loading
  and custom indicator save/delete actions.
- `indicatorComputeController.ts` owns explicit-local direct-OHLCV backend
  compute scheduling and fail-closed publication.
- `indicatorComputeJobRuntime.ts` owns local lifecycle, bounded job identities,
  singleflight, completion acknowledgement, cancellation, and stale fencing.
- `indicatorRangeScheduler.ts` owns hosted history coverage, request coalescing,
  in-flight barriers, cancellation, and stale-response protection.
- `indicatorRangeLifecycle.ts` owns hosted scheduler lifecycle identity.
- `indicatorStreamController.ts` owns hosted indicator WebSocket subscriptions,
  snapshots, patches, resume acknowledgements, and sequence recovery.
- `indicatorResultCacheStore.ts` owns context/execution-scoped immutable result
  versions and stable cache views.
- `indicatorHydrationRuntime.ts` owns deferred cache publication deduplication,
  cancellation, and stale fencing.
- `indicatorOutputReducer.ts` owns cache hydration and stable
  marker/fill/hline/bgcolor/barcolor/signal output updates.
- `indicatorPaneProjection.ts` maps active indicator lines into main overlays and
  sub panes as a pure projection.
- `scriptRuntimeCatalog.ts` resolves descriptor-declared languages, runtimes,
  and safe editor hints without a closed runtime-ID union.

## Script Runtime Discovery

`IndicatorEditor` loads `GET /api/v1/indicators/runtimes` and validates the
schema before enabling run, save, or fork actions. The language selector is
generated from routed descriptors. Unknown community languages use Monaco's
plaintext mode; Pyne completion, theme, and security controls remain optional
host enhancements rather than a plugin whitelist.

Plugins may advertise `meta.ui.languages.<language-id>.monacoLanguage` and
`starterSource` strings. These are data-only hints and never load plugin-owned
JavaScript, CSS, or React code. The chosen language is part of HTTP/range/WS
requests, custom-indicator persistence, result-cache identity, and stream
configuration identity.

## Allowed Dependencies

- May consume `features/chart-session` and `features/market-data` contracts
  through arguments passed by the app composition root.
- May consume market-data indicator range request status/actions idempotently and
  issue hosted indicator range requests through the indicator stream controller.
- May notify the app composition root when an indicator is removed so owning
  features can handle related cleanup through their own public actions.
- May call indicator backend services through `services/indicatorApi`.
- May use chart data shape supplied by market-data, without owning K-line
  loading, caching, WebSocket ticks, or gap recovery.
- May expose feature UI entry points such as `IndicatorPanel` and
  `IndicatorEditor`.

## Forbidden Dependencies

- Do not own symbol, exchange, market type, interval selection, or K-line data
  lifecycle.
- Do not import App internals or raw Lightweight Charts objects.
- Do not write drawing, watchlist, settings, export, or alert state here.
- Do not move indicator rendering series lifecycle into this feature; chart
  rendering remains behind chart components and the chart adapter boundary.

## Migration Notes

Phase 11 removed the old `src/hooks/useIndicators.js` wrapper and folded the
indicator compute, payload, catalog, security-policy, hosted stream helpers,
and indicator panel/editor UI into this feature.
