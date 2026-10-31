# Shared live indicator demand

This implements the first integration of #161 on top of #168's market cache
health protocol. `MarketDataWorkspaceProvider` composes `MarketDataManager`,
`IndicatorDataManager`, and `ChartDataFlowManager`. Chart selection declares
intent through the combined flow; chart windows and output publication remain
private to each chart.

## Ownership

- `MarketDataManager` remains the only shared market admission owner.
- `IndicatorDataManager` owns in-flight range and provided-input computation
  demands. Its stream port uses the existing shared indicator socket/shard
  coordinator. This change does not introduce semantic deduplication of live
  indicator WebSocket subscriptions or move their checkpoint state into a new
  store.
- `indicatorResultCacheStore` remains the normalized result owner. No second
  result collection is introduced. Definitions, parameters, complete market
  identity, input scope and provided input origin retain their existing cache
  identities.
- `useIndicatorRuntime` retains per-chart output guards, range recovery,
  hydration and resume policy. Replay retains its existing execution route and
  shared-result-cache opt-out.

## Requests and cancellation

The workspace broker joins concurrent semantically equal requests. Equality
includes complete market identity, definition/script, parameters, requested
range or exact provided OHLCV (including finality). Stored custom script IDs
remain part of equality when no inline definition is supplied. Logical chart
IDs and request scope/generation are not computation identity.

Each consumer has its own abort lease. Cancelling one rejects that consumer
immediately. Only the final consumer cancels its work; a physical batch is
aborted only when all its entries are unused. Transport requests receive
manager-owned client IDs, job keys and scope, and responses are checked and
mapped back to each consumer's logical identity. Request input is copied once
per new shared entry, not once per joining chart.

Each of the range and compute brokers permits two active physical batches,
128 pending distinct entries, and 32 entries per batch. Forty milliseconds of
coalescing lets adjacent chart effects share work. Queued foreground requests
precede speculative requests. Foreground demand joins its entry before taking
the existing foreground gate, so preempting a warm consumer cannot cancel a
foreground consumer of the same work.

Hosted ranges capture the observed closed input prefix through the requested
end. Corrections before the output range can therefore invalidate recursive
results. Provided computations bind their actual input window. Results whose
input has been invalidated or disconnected cannot complete successfully.

Live JavaScript keeps its existing forming-preview contract: a held forming
sample may finish while that candle receives more ticks. Closed input and
forming finality are still fenced. The result cache separately requires an
exact full-input stamp, so a superseded forming sample may display as a
preview but cannot become a certified reusable result.

## Selection and bounded warming

The runtime registers its enabled indicator plan by chart owner. Output-only
changes do not replace the plan. Hidden, errored, invalid and retired-language
definitions are excluded. An intent includes at most eight definitions, with
at most four target intents per 30 seconds and four waiting/running targets.
Every intent expires after 30 seconds and has only one execution attempt.

Indicator work waits until the target's 500 closed bars have healthy coverage,
continuity and freshness. It uses the same foreground/preload gate as market
warming. Local calculations use at most the current 2,000-row target window;
hosted calculations request the 500 closed bars through HTTP. Speculative
indicator WebSocket subscriptions are never created, so hovering does not
activate live hosted alerts.

Selection promotes running work before cancelling hover demand. Promotion
releases the speculative gate while retaining the existing bounded chart
handoff. A foreground consumer can then join the same in-flight computation.
Plan replacement, owner release, unrelated foreground preemption and expiry
cancel speculation. Late speculative results cannot publish or populate cache.

On selection, an exact, current cached local result bypasses physical
computation. Force recompute bypasses this cache path, replay remains opted
out, and a different viewport/input origin cannot reuse the result. Hosted
results reuse the existing computed-range coverage/hydration path. A larger
window or changed forming sample correctly requires fresh computation.

## Health and recovery

Result health reports computed range coverage, input validity, source
continuity, source freshness and last computation time separately. A current
closed result does not by itself prove that the source is fresh. Existing
market version invalidation and per-chart indicator correction/recovery
schedulers remain authoritative.

Complete market identity is also included in the hosted subscription signature
and the committed-message fence. A late provider/price/session variant frame
cannot be relabelled as the chart's new identity.

## Evidence and remaining release work

Run `npm run test:indicator-flow:browser` from `frontend` for the production
Chromium fixture. It uses real React runtimes, independent chart windows and
real isolated JavaScript workers, with controlled market/hosted transports.
It covers shared computation, warm selection without recomputation, HTTP-only
hosted warming, independent cancellation and historical correction.

Unit regressions cover consumer and batch budgets, identity isolation, stored
custom scripts, disconnect/correction fencing, held forming samples, exact
cache reuse, force/replay boundaries, promotion, preemption and plan replacement.

This is not #161 native installed-package qualification, all-provider coverage,
long-duration soak, cross-window request sharing, or proof of semantically
shared hosted subscriptions. #168's real-package acceptance applies to its own
immutable package; it is not inherited by this change.
