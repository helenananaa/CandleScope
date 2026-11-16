import { isFrontendScript } from "./frontendScriptContract.js";
import { computeFrontendScript } from "./frontendScriptRuntime.js";
import { awaitIndicatorComputations } from "./indicatorComputeSettlement.js";
import type { IndicatorComputeBatchExecutor } from "./indicatorComputeController.js";
import type { IndicatorComputeBatchItem } from "./indicatorTypes.js";
import { createIncrementalBuiltinCompute } from "./builtinIncrementalCompute.js";

const liveBuiltinExecutors = new WeakMap<IndicatorComputeBatchExecutor, IndicatorComputeBatchExecutor>();
function liveBuiltinExecutor(hosted: IndicatorComputeBatchExecutor): IndicatorComputeBatchExecutor {
  let executor = liveBuiltinExecutors.get(hosted);
  if (!executor) {
    executor = createIncrementalBuiltinCompute(hosted, {
      supports: request => request.name === "EMA" && request.replayContext === undefined,
      allowSparseSeed: true,
      maxEntries: 8, maxCachedBars: 20_000, eventName: "indicator.builtin.incremental",
    });
    liveBuiltinExecutors.set(hosted, executor);
  }
  return executor;
}

/** Intercept before either the live backend executor or replay executor. */
export async function routeIndicatorComputeBatch(
  options: Parameters<IndicatorComputeBatchExecutor>[0],
  hosted: IndicatorComputeBatchExecutor,
  frontend = computeFrontendScript,
) {
  const browserJobs = options.jobs.filter(job => isFrontendScript(job.request));
  const hostedJobs = options.jobs.filter(job => !isFrontendScript(job.request));
  const browser = awaitIndicatorComputations(browserJobs.map(async job => {
    const payload = await frontend(job.request, options.signal);
    const result = { clientId: job.clientId, jobKey: job.jobKey, payload };
    options.onResults?.([result]);
    return result;
  }));
  const server = hostedJobs.length ? liveBuiltinExecutor(hosted)({ ...options, jobs: hostedJobs })
    : Promise.resolve({ ok: true, results: [] as IndicatorComputeBatchItem[] });
  const [local, remote] = await awaitIndicatorComputations([browser, server] as const);
  const results = [...local, ...remote.results];
  const byKey = new Map(results.map(item => [item.jobKey, item]));
  if (results.length !== options.jobs.length || byKey.size !== options.jobs.length
    || options.jobs.some(job => byKey.get(job.jobKey)?.clientId !== job.clientId)) {
    throw new Error("Indicator compute response identity mismatch");
  }
  return { ok: true, results: options.jobs.map(job => byKey.get(job.jobKey)!) };
}
