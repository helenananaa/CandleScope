import { isFrontendScript } from "./frontendScriptContract.js";
import { computeFrontendScript } from "./frontendScriptRuntime.js";
import type { IndicatorComputeBatchExecutor } from "./indicatorComputeController.js";
import type { IndicatorComputeBatchItem } from "./indicatorTypes.js";

/** Intercept before either the live backend executor or replay executor. */
export async function routeIndicatorComputeBatch(
  options: Parameters<IndicatorComputeBatchExecutor>[0],
  hosted: IndicatorComputeBatchExecutor,
  frontend = computeFrontendScript,
) {
  const browserJobs = options.jobs.filter(job => isFrontendScript(job.request));
  const hostedJobs = options.jobs.filter(job => !isFrontendScript(job.request));
  const browser = Promise.all(browserJobs.map(async job => {
    const payload = await frontend(job.request, options.signal);
    const result = { clientId: job.clientId, jobKey: job.jobKey, payload };
    options.onResults?.([result]);
    return result;
  }));
  const server = hostedJobs.length ? hosted({ ...options, jobs: hostedJobs })
    : Promise.resolve({ ok: true, results: [] as IndicatorComputeBatchItem[] });
  const [local, remote] = await Promise.all([browser, server]);
  const results = [...local, ...remote.results];
  const byKey = new Map(results.map(item => [item.jobKey, item]));
  if (results.length !== options.jobs.length || byKey.size !== options.jobs.length
    || options.jobs.some(job => byKey.get(job.jobKey)?.clientId !== job.clientId)) {
    throw new Error("Indicator compute response identity mismatch");
  }
  return { ok: true, results: options.jobs.map(job => byKey.get(job.jobKey)!) };
}
