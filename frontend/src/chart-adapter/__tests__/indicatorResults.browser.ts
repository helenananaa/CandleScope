import { IndicatorDataManager } from "../../features/indicators/indicatorDataManager.js";
import { buildIndicatorOhlcv } from "../../features/indicators/indicatorComputeRuntime.js";
import { computeFrontendScript } from "../../features/indicators/frontendScriptRuntime.js";
import { routeIndicatorComputeBatch } from "../../features/indicators/frontendScriptBatch.js";
import { SharedMarketCache } from "../../features/market-data/manager/sharedMarketCache.js";
import { ForegroundPreloadGate } from "../../features/market-data/foregroundPreloadGate.js";
import type { IndicatorComputeRequest } from "../../features/indicators/indicatorTypes.js";
import type { KlineBar } from "../../features/market-data/marketDataTypes.js";

function assert(value: unknown, message: string): asserts value { if (!value) throw new Error(message); }

/** Actual opaque-origin workers. The fixed input matrix tests result reuse,
 * not exchange qualification or mathematical equivalence with hosted seeds. */
export async function checkIndicatorResults() {
  const cache = new SharedMarketCache(), gate = new ForegroundPreloadGate(0);
  let executions = 0;
  const manager = new IndicatorDataManager({ cache, gate, coalesceMs: 0,
    compute: options => routeIndicatorComputeBatch(options, async () => { throw new Error("JS reached backend"); },
      (request, signal) => { executions++; return computeFrontendScript(request, signal); }),
  });
  const rows: KlineBar[] = Array.from({ length: 30 }, (_, index) => ({ time: (1_800_000_000 + index * 300) as KlineBar["time"],
    open: 10, high: 50, low: 0, close: 10 + index, volume: 1, is_closed: true }));
  const script = 'let total=0; plot("sum",bars.map(bar=>total+=bar.close));';
  const run = (request: IndicatorComputeRequest, id: string) => manager.compute({ jobs: [{ request, clientId: id, jobKey: id }] });
  try {
    for (const symbol of ["BTCUSDT", "ETHUSDT"]) for (const interval of ["1m", "5m"]) {
      const series = { exchange: "binance", marketType: "spot", symbol, interval };
      const read = cache.beginRead(series); cache.admitResponse(read, { data: rows, endpoint: "history" }); read.release();
      const request = { ...series, language: "frontend-js", script, ohlcv: buildIndicatorOhlcv(rows, { limit: rows.length }) };
      const cold = await run(request, "chart-a"); const count: number = executions;
      const hot = await run(structuredClone(request), "chart-b");
      assert(executions === count, "hot consumer started another worker");
      assert(hot.results[0]?.clientId === "chart-b", "cached output inherited another chart ID");
      assert(Object.isFrozen(hot.results[0]!.payload.lines[0]!.data), "shared worker output is mutable");
      assert(JSON.stringify(cold.results[0]!.payload) === JSON.stringify(hot.results[0]!.payload), "hot output changed");
      const shorter = await run({ ...request, ohlcv: request.ohlcv.slice(10) }, "different-origin");
      assert(executions === count + 1, "a different input origin reused the full-window result");
      assert(shorter.results[0]!.payload.lines[0]!.data[0]!.value === 20, "recursive JS lost its window origin");
      cache.admitRealtime(series, { ...rows[0]!, close: 11 }, "bar.amended");
      const corrected = await run({ ...request, ohlcv: [{ ...request.ohlcv[0]!, close: 11 }, ...request.ohlcv.slice(1)] }, "corrected");
      assert(corrected.results[0]!.payload.lines[0]!.data.at(-1)!.value === 736, "source correction reused stale worker output");
    }
    assert(manager.diagnostics().compute.consumers === 0, "completed matrix retained consumer leases");
    assert(manager.results.diagnostics().reused === 4, "matrix did not exercise completed result reuse");
    return `real JS workers: BTC/ETH × 1m/5m cold/hot results, different origins and corrected input (${executions} executions)`;
  } finally { manager.dispose(); gate.dispose(); }
}
