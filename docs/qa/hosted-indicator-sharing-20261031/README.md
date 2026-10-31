# Hosted indicator subscription sharing — 2026-10-31

Continuation of #161, based on the merge of #172 (`0b490d4e`). That merge also
includes #173's backend work. This change shares equivalent hosted builtin
subscriptions inside one workspace/window while preserving per-chart output,
history, readiness and viewports. Pine and other script subscriptions retain
private live state and alert ownership.

Contract: [INDICATOR_DATA_FLOW.md](../../architecture/INDICATOR_DATA_FLOW.md).
Source/receipt hashes: [source-manifest.json](source-manifest.json).

Final local [full check](checks.json) passed: 4,669 frontend tests, one isolated
performance gate, 124 desktop tests, architecture/plugin/i18n checks, type
checking, lint and production build. The existing `SingleChartPanes` effect
cleanup warning and bundle-size warnings remain. Node 24.22.1 / npm 11.19.1;
dependencies use the committed lockfile.

## Review and targeted regressions

The initial regressions failed before implementation: equal builtin demands
opened two subscriptions, and partial release restarted the survivor. Targeted
connection, coordinator and hosted-runtime tests now pass (48 tests).

Coverage includes semantic parameter/market separation, canonical parameter
order, workspace/window isolation, private scripts, fresh late-join ACKs,
per-consumer revision invalidation, A/B/A stale-frame rejection, targeted refresh,
stable unrelated shards, capacity changes, reentrant cancellation, callback
mutation/error isolation, ACK retry, minimum compatible resume and overload
cold recovery.

Review also caught two defects before delivery:

- Concatenating market identity dimensions could collide when a dimension
  contained the separator. The sharing key now serializes the normalized object.
- Including seed history length in identity restarted streams as chart history
  grew, including private Pine sessions. The manager now treats seed depth as a
  budget and uses the largest consumer request for a fresh subscribe. Ordinary
  growth preserves the wire; existing warmup-threshold logic explicitly refreshes
  an insufficient seed. Both new regressions failed before their fixes.

## Production Chromium evidence

[Indicator flow](indicator-flow-chromium.json) passes 11 cases with real React
runtimes, real Lightweight Charts and isolated browser workers. Market HTTP and
hosted WebSocket transports are controlled.

The added hosted scenarios prove two chart demands use one active wire, a late
join receives a fresh ACK, overload reconnection restores one cold subscription,
normal new-candle growth does not resubscribe, parameter divergence/rejoin affects
the intended demand, partial release retains the survivor and final release
closes the transport. Historical output and the independent viewport survive.
No workers remain after cleanup, no renderer exceptions were captured, and the
owned browser exited normally. Diagnostic compute counts in the receipt are a
pre-cleanup snapshot; they are not an assertion of idle background computation.

[JavaScript/replay/editor](javascript-chromium.json) passes 12 runtime cases and
three editor cases, including sandbox restrictions, cancellation, timeout,
continuous live ticks, source replacement, replay, persistence and save failure.

Reproduce from `frontend`:

```sh
node --import tsx --test src/features/indicators/__tests__/sharedIndicatorStreamCoordinator.test.ts src/features/indicators/__tests__/indicatorStreamConnection.test.ts src/features/indicators/__tests__/indicatorWsRuntime.test.ts
npm run test:indicator-flow:browser
npm run test:frontend-js:browser
npm run check
```

## Qualification boundary

#172 was separately reviewed, corrected, qualified with its actual relocated
macOS arm64 ZIP (including save, normal full exit and same-profile restart), and
merged after its arm64/x64 CI passed at `d95ea7d6`. Its ZIP SHA-256 is
`6fa1847e095696e51111416ea5bff3eedef49983053002afb58f528f7f19a0cb`.
See [PR #172](https://github.com/helenananaa/CandleScope/pull/172) and
[its completed CI](https://github.com/helenananaa/CandleScope/actions/runs/41198042628).

Those receipts qualify that source only. The later subscription changes here
have controlled production-browser evidence, not new installed-package
qualification. All-provider coverage, long-duration soak, cross-window sharing,
provider-certified script session sharing and the full 157-item acceptance
matrix remain outside this receipt. #161 remains open.
