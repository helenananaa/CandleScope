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
  coordinator. Equivalent builtin subscriptions share a wire as described below;
  checkpoint state remains in the existing per-consumer recovery lane.
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

Independent execution routes and input-window chunks publish successful work
before reporting sibling failures. Cancelled or superseded computations never
become persistent script errors.

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

### Bounded JavaScript inputs (#164)

`IndicatorDataManager.inputs` reads and subscribes to explicit `[from, to]`
ranges in `SharedMarketCache`. It retains no second row collection. The chart's
owned window declares the bounded time axis and ownership epoch; the shared
cache supplies immutable values and dependency versions. A missing/mismatched
axis waits for data instead of silently substituting a different calculation
origin. Corrections can wake JS before the private chart projection publishes.

Each enabled chart owns one range subscription and retention lease. Selection,
history growth and closing the chart replace/release that consumer's lease;
manager disposal releases all remaining leases. Unrelated range changes do not
wake a consumer. Diagnostics expose active input subscriptions. Cache hard
limits still take precedence over retention.

The existing 250 ms forming-sample scheduler and pending-computation guard
remain in place. Held forming samples may finish during ticks, while source
ownership, closed-row correction, finality and disconnect invalidate old work.
Exact stamps are still required for reusable results. JS and hosted adapters
continue through the same request broker and normalized result-cache admission
functions; per-chart publication guards remain necessary for independent views.

This migration does not introduce persistent Workers or an incremental script
SDK (#154 remains deferred). Broader consolidation of per-chart recovery and
result subscriptions, native-package qualification of this new input path,
and all-provider/long-duration acceptance remain separate #164 work.

Result health reports computed range coverage, input validity, source
continuity, source freshness and last computation time separately. A current
closed result does not by itself prove that the source is fresh. Existing
market version invalidation and per-chart indicator correction/recovery
schedulers remain authoritative.

Complete market identity is also included in the hosted subscription signature
and the committed-message fence. A late provider/price/session variant frame
cannot be relabelled as the chart's new identity.

## Hosted subscription ownership

Within one workspace/window, identical hosted builtin subscriptions share one
manager-owned wire ID. Equality includes complete market identity, definition,
canonical parameters. Display names remain conservative
identity inputs. Logical consumer IDs/signatures and resume checkpoints do not
define computation equality. Fanout restores each consumer's own ID/signature,
clones nested payloads and rechecks membership after reentrant callbacks.
Seed history is a budget: a fresh subscribe uses the maximum requested by its
consumers. Ordinary history growth updates the next subscription's budget
without replacing the active wire or resetting a private script session. The
existing controller explicitly refreshes a seed that crosses its required
warmup threshold. Each chart's HTTP history and viewport remain independent.

Scripts remain private: the current provider contract owns Pine `varip`, live
observations and alert delivery per subscription. Equal source text/parameters
do not prove equal session state. No source-text heuristic or opt-out of those
semantics is introduced. Workspaces/windows also remain separate sharing scopes.

A late builtin consumer causes only its shared group to obtain a fresh cold
subscription acknowledgement with a never-reused wire ID. No old ACK is replayed
and no second output cache is created. The existing per-chart HTTP hydration
continues to own historical readiness. The server's cold subscribe contract is
ACK plus optional preview, not a guaranteed full-history WebSocket snapshot.
Each consumer's old revision is checked against the ACK; an incompatible
epoch/correction invalidates that consumer's history instead of silently
rebasing it onto another consumer's current revision.

Compatible consumers resume from the earliest requested checkpoint. Incompatible
checkpoints use a cold subscription. The existing physical connection still owns
ACK retries, sequence recovery and overload cold-resume handling. Partial release
leaves the surviving wire untouched; final release unsubscribes it. Explicit
refresh affects only groups owned by that caller. Ordinary joins/leaves retain
unrelated shard assignments; advertised-capacity changes deliberately repack.

Diagnostics distinguish logical subscriptions, physical subscriptions, shared
groups, deduplicated subscriptions and private script subscriptions. This phase
reduces duplicate active wire demand; a late join can legitimately send a fresh
subscribe for its group to establish readiness safely.

## Evidence and remaining release work

Run `npm run test:indicator-flow:browser` from `frontend` for the production
Chromium fixture. It uses real React runtimes, independent chart windows and
real isolated JavaScript workers, with controlled market/hosted transports.
It covers shared computation, warm selection without recomputation, HTTP-only
hosted warming, independent cancellation and historical correction. Hosted
React runtimes also exercise late join, parameter divergence/rejoin, partial
release and overload reconnection while preserving private history/viewports.

Unit regressions cover consumer and batch budgets, identity isolation, stored
custom scripts, disconnect/correction fencing, held forming samples, exact
cache reuse, force/replay boundaries, promotion, preemption and plan replacement.

These fixtures alone do not establish native installed-package qualification.
The PR records native acceptance against its exact source and package hashes.
All-provider coverage, long-duration soak, cross-window request sharing and any
future provider-certified sharing of private script sessions remain separate
work. #172's accepted package does not qualify the later subscription changes;
its exact source/artifact receipts remain separate.
