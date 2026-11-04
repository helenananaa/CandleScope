import { defaultBacktestApi, type BacktestApiClient } from "../../backtest/backtestApi.js";
import type { BacktestRunRecord } from "../../backtest/backtestTypes.js";
import { isBacktestTerminalState } from "../../backtest/backtestRunClient.js";
import { StrategyRunStreamError, type StrategyRunUpdate } from "../../backtest/backtestRunStream.js";
import { ChartStrategyResultCache } from "../../backtest/chart-tester/chartStrategyResultCache.js";
import { runResearchBacktest, type ChartStrategyRunApi } from "../../backtest/chart-tester/chartStrategyRunRequest.js";

type ResearchRequest = Omit<Parameters<typeof runResearchBacktest>[0], "api" | "waitForTerminal" | "wait" | "pollIntervalMs">;
export type StrategyDataApi = ChartStrategyRunApi & Pick<BacktestApiClient, "streamRun" | "getReport" | "getChart" | "cancelRun">;

/** Owns fixed-history operations and immutable results independently of live
 * chart stores. Releasing a consumer never cancels a durable shared run. */
export class StrategyDataManager {
  private readonly operations = new Set<AbortController>();
  private readonly results = new ChartStrategyResultCache();
  private readonly updates = new Map<string, StrategyRunUpdate>();
  private readonly retainedResults: string[] = [];
  private streams = 0;
  private closed = false;

  constructor(private readonly api: StrategyDataApi = defaultBacktestApi) {}

  private async operation<T>(signal: AbortSignal | undefined, action: (signal: AbortSignal) => Promise<T>): Promise<T> {
    if (this.closed) throw new StrategyRunStreamError("STRATEGY_MANAGER_CLOSED", "Strategy data manager is closed");
    signal?.throwIfAborted();
    if (this.operations.size >= 32) throw new StrategyRunStreamError("RUN_CAPACITY_EXCEEDED", "Strategy operation capacity reached");
    const controller = new AbortController();
    const abort = () => controller.abort(signal?.reason);
    signal?.addEventListener("abort", abort, { once: true });
    this.operations.add(controller);
    try {
      const result = await action(controller.signal);
      controller.signal.throwIfAborted();
      return result;
    } finally {
      signal?.removeEventListener("abort", abort);
      this.operations.delete(controller);
    }
  }

  private async wait(runId: string, signal: AbortSignal, onUpdate?: (run: BacktestRunRecord) => void): Promise<BacktestRunRecord> {
    if (!this.api.streamRun) throw new StrategyRunStreamError("STRATEGY_STREAM_UNAVAILABLE", "The strategy stream transport is unavailable");
    this.streams += 1;
    try {
      const run = await this.api.streamRun(runId, signal, (event) => {
        if (signal.aborted || this.closed) return;
        this.updates.delete(runId);
        this.updates.set(runId, event);
        while (this.updates.size > 32) this.updates.delete(this.updates.keys().next().value!);
        onUpdate?.(event.run);
      });
      signal.throwIfAborted();
      this.requireCompleted(run);
      return run;
    } finally {
      this.streams -= 1;
    }
  }

  private requireCompleted(run: BacktestRunRecord): void {
    if (run.state !== "COMPLETED") throw new StrategyRunStreamError(run.failure_code ?? `RUN_${run.state}`, `Strategy run ${run.state}`);
  }

  runResearch(request: ResearchRequest) {
    return this.operation(request.signal, (signal) => runResearchBacktest({
      ...request, api: this.api, signal,
      waitForTerminal: (runId, _signal, onUpdate) => this.wait(runId, signal, onUpdate),
    }));
  }

  private async readResult(runId: string, signal: AbortSignal) {
    const result = await this.results.load(this.api, runId, signal);
    signal.throwIfAborted();
    const previous = this.retainedResults.indexOf(runId);
    if (previous >= 0) this.retainedResults.splice(previous, 1);
    this.retainedResults.push(runId);
    while (this.retainedResults.length > 8) this.results.clear(this.retainedResults.shift()!);
    return result;
  }

  loadResult(runId: string, signal?: AbortSignal) {
    return this.operation(signal, (owned) => this.readResult(runId, owned));
  }

  restoreRun(runId: string, signal?: AbortSignal) {
    return this.operation(signal, async (owned) => {
      const current = await this.api.getRun(runId, owned);
      const terminal = isBacktestTerminalState(current.state) && current.state !== "FAILED" ? current : await this.wait(runId, owned);
      this.requireCompleted(terminal);
      return this.readResult(runId, owned);
    });
  }

  cancelRun(runId: string, signal?: AbortSignal) {
    return this.operation(signal, (owned) => this.api.cancelRun(runId, owned));
  }

  diagnostics() {
    return { closed: this.closed, operations: this.operations.size, streams: this.streams,
      results: this.results.diagnostics(), runs: [...this.updates].map(([runId, event]) => ({
        runId, state: event.run.state, snapshotHash: event.run.snapshot_hash,
        configHash: event.run.config_hash, progress: event.progress,
      })) };
  }

  dispose(): void {
    this.closed = true;
    for (const operation of this.operations) operation.abort();
    this.results.clear();
    this.retainedResults.length = 0;
    this.updates.clear();
  }
}
