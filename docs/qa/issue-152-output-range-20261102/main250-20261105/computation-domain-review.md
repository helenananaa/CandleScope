# Native counter regression: computation-domain boundary

Source9e44280a (productb784fb52), actual preserved Native witness in this
folder. This is a focused source/transport audit, not a product fix or pass.

The same chart renders500 then202 while acquiring its501st bar. The actual HTTP
responses are historical-batch/sessionRetained=false. The first request has a
500-bar target; the later one-/two-bar targets run with200 warmup. Each result
is internally consistent with a different script input origin. The renderer
combines them in one displayed state, where opaque cumulative/varip scripts
cannot use a finite warmup as proof of equivalence.

The concrete paths are:

- useIndicatorRuntime.ts: requestIndicatorRange schedules historical range work;
  shared-prefix callbacks and auto-right/correction queues can request a narrow
  newly admitted tail while an existing script result remains displayed.
- indicator_range_batch.py: compute_indicator_range_batch_async deliberately
  slices each script to its own standalone target/calendar warmup. Preserving
  this rule prevents another batch job from introducing unrelated/future input.
- stream_indicator_payloads.py: _script_runtime_request only sets a retained
  pineSessionId for websocket transports; HTTP range jobs are separate batches.
- stream_script_subscriptions.py: corrections can rebuild a retained WS snapshot
  but announce a recomputed range. That drives the frontend's separate historical
  range fetch. Realtime WS execution also has a subscription-owned historyLimit.
- range_result_service.py: script identity intentionally includes historyLimit;
  equal target endpoints do not make independent opaque script inputs equivalent.

A safe repair must define the chart script's calculation origin/input generation
and result ownership across initial history, corrections, right catchup and live
WS delivery. Historical range APIs must keep their standalone/no-future contract
unless an explicit versioned calculation-domain contract is supplied. Shared
infrastructure must remain language-neutral and retain independent chart/session
isolation. Reuse the existing SDK/runtime owner; do not create a second Pine
engine or an unbounded in-memory copy merely to make this example monotonic.

Removing historyLimit from cache identity, enlarging the warmup to500, skipping
initial corrections, accepting a reset, or weakening the Native monotonic/
parity/marker assertions does not establish that ownership contract. A later
repair needs real service+renderer cases for a non-finite cumulative script,
negative offsets, point deletion, source amendment, appended closed/forming bars,
independent charts and saved/full-owned-quit/restart. Keep the original failed
profiles, raw responses and assertions as acceptance counterexamples.

Current status: Native qualification remains failed;322 continuous-strategy-stack
tests elsewhere do not cover this indicator defect. CI must not turn this
observed failure into a merge claim.
