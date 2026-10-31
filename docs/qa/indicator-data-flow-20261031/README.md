# Indicator data flow — 2026-10-31

Base: #168 plus integrated #138/#148/#144 (`128b4932` main).
Source identity: [source-manifest.json](source-manifest.json).
Contract: [INDICATOR_DATA_FLOW.md](../../architecture/INDICATOR_DATA_FLOW.md).

After integrating main, full local `npm run check` passed: 4,647 frontend tests,
one isolated performance gate, 123 desktop tests, architecture/plugin/i18n checks,
types, lint and build. The subsequent native control fix passed all 124 desktop
tests and changed-file lint.
The existing `SingleChartPanes` effect-cleanup lint warning and bundle-size
warnings remain. Dependencies match the reviewed #168 lockfile environment.

## Production Chromium evidence

[Data flow result](data-flow-chromium.json), Chrome 156.0.8078.74:

- Two real React indicator runtimes share one real JavaScript Worker computation.
- Hover warms the enabled JavaScript plan; selection publishes its exact cached
  result with no additional computation. The other chart keeps its result and
  historical viewport.
- Hosted warming uses the controlled HTTP range transport without creating a
  speculative indicator WebSocket subscription.
- Cancelling one consumer leaves the other consumer's real computation alive.
- A historical amendment invalidates warmed input and recomputes only the
  affected chart.
- Final demand counts are zero, no workers remain, and no renderer exceptions
  were captured. The owned browser exited normally.

[Existing JavaScript/replay regression](existing-js-chromium.json) also passes:
real isolated execution, sandbox restrictions, error cleanup, timeout and
cancellation, continuous live ticks, source replacement, hidden/resumed scripts,
owner changes, replay rewind, remount/persistence and the actual editor flow.

Reproduce from `frontend`:

```sh
npm run test:indicator-flow:browser
npm run test:frontend-js:browser
npm run check
```

The fixtures use production-minified code, real React lifecycles, chart rendering
and browser workers. Market and hosted calculation transports are controlled.
These files are not real-exchange observations, native installed-package
acceptance, Windows qualification, a long-duration soak, or the full 157-item
acceptance matrix. #168's immutable installed-package evidence is separate.

## PR #172 review regression

A hosted warm response may contain less history than requested. Warming now
records the intersection of the returned/requested ranges and the backend
revision, and patches an existing current cache instead of discarding output
outside the returned range. Both added regression cases failed on the original
PR and pass with the fix; all 20 demand/input-binding/warming tests pass.
Both production Chromium receipts above were rerun after this correction.

## Native integration correction

The first actual relocated ZIP run exposed workflow control becoming unavailable
after a frontend JavaScript indicator created its isolated `about:srcdoc` frame.
Electron's `did-start-loading` also fires for subframes. Both desktop control
owners now share a lifecycle listener that disconnects only on a new main-document
navigation or destruction; same-document and sandbox-frame navigation retain
readiness and pending receipts. The new regression failed before the fix and all
124 desktop tests pass afterward. Main-document reload still revokes access.

The merged indicator-flow fixture and main's `--history-stages` fixture passed;
the JavaScript/replay/editor fixture was rerun after integration. Native package
qualification is recorded separately in the PR with its exact artifact hashes.
