# Replay frontend latency follow-up — 2026-09-09

This follows `337a1331`. The change reduces frontend work between authoritative advancement, chart updates and indicator updates. It does not change backend execution or eliminate server latency spikes.

## Measurement

Development-only React Profiler commits and bounded application performance events now identify control dispatch/response/authority, runtime presentation publication, display-tail application and local indicator work. The initial sampled click produced several substantial React commits before the command response callback, followed by additional chart/indicator commits. MACD and VOL local preparation took approximately 12.6ms and 6.7ms in that sample.

Metrics below are application update timestamps, not compositor paint timestamps. Samples are small and use successive market bars; no p95 claim is made.

## Changes

- Batch ordinary paused DISPLAY_BAR presentation updates until command acknowledgement and the authoritative tail can be applied together. The ReplayStore authority and its subscribers continue updating immediately. Disconnects, generation/session/epoch changes, controller changes, rewinds, status/warning changes, fills, orders and equity changes are not treated as ordinary deferrable progress. The release callback is idempotent and runs in a finally block.
- Keep runtime and viewer action objects stable. Command construction still reads the last committed React snapshot through a layout-updated ref, preserving the displayed decision-time CAS contract.
- Ignore identical ViewerState payloads instead of publishing another state object.
- Remove the unused sampled-boundary state update on every paused step. Entering playback seeds its sampling boundary from the current view; paused/review rendering continues using the current cursor exactly.
- Reuse immutable historical indicator points and colors, recalculate rounding only for the changed tail, and replace per-bar JSON serialization during prefix comparison with comparison of the actual OHLCV/finality fields. Prefix validation and array-container copying remain linear; this is not an O(1) claim for the entire indicator pipeline.
- Stabilize chart metadata and pane callbacks. Memoize paper/account dock boundaries and stop passing unused indicator status into them. Local form state and locale subscriptions remain active.
- Retain the existing immediate indicator publication and lifecycle checks that prevent future data from being repainted after a rewind.

## Results

Same development frontend with replay MACD/VOL, account sidebar and a real-time page with 10 indicators/full order book open:

| Sample | Click to K-line update | Click to VOL update | Response callback to K-line update |
|---|---:|---:|---:|
| 1 | 141ms | 355ms | 7ms |
| 2 | 189ms | 393ms | 4ms |
| 3 | 139ms | 297ms | 3ms |
| 4 | 137ms | 313ms | 3ms |
| 5 | 148ms | 353ms | 4ms |

The preceding server-only follow-up recorded 319–348ms to K-line update and 580–641ms to VOL update under the corresponding development workload. This turn's local indicator preparation was approximately 0.6–2ms total across both indicators in the matched samples.

Production build with the same two replay indicators/account panels and the real-time page open:

- Response callback to K-line update: 3–4ms.
- Response callback to VOL update: 49–75ms.
- Request durations were highly variable: 6563, 1954, 988, 338 and 214ms in the retained five-sample run. The first attempted step before those samples took 4524ms; its Server-Timing recorded approximately 3677ms in advance and 672ms in display projection. These slow requests were not caused by the post-response frontend path and are not omitted from the evidence.
- End-to-end production update times therefore remained variable. The final two samples were 346/226ms to K-line and 403/272ms to VOL. This is not evidence that every click is instantaneous.

## Verification and state

- Replay frontend suite: 396 passed, including immediate authority during presentation batching, disconnect/controller/rewind exclusions, idempotent release, Python builtin parity and immutable output reuse.
- TypeScript, ESLint, Windows production build and git diff whitespace checks passed. The production build ran from the physical E: workspace path to avoid the known H: alias/Vite root mismatch.
- Final freshly loaded development and production action windows captured no Runtime.exceptionThrown events. A transient Hook-order error during intermediate hot replacement required a full reload; final validation used reloaded pages and the production build.
- No backend source or service restart was needed for this follow-up.
- Browser testing advanced the existing run from 619 to 637 displayed 15m bars, leaving it paused at 2023-02-18 09:59:59. Test tabs and the temporary preview server were cleaned up.

Evidence directory: `output/replay-latency-20260909/`. See `frontend-baseline-trace.json`, `frontend-coalesced-trace.json`, `frontend-final-matched-{network,trace,summary}.json`, `frontend-final-production-{network,trace,summary}.json`, `frontend-production-cold-network.json` and `frontend-final-*` validation logs.
