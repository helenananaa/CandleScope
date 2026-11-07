import { defaultBacktestApi, type BacktestApiClient } from "../../backtest/backtestApi.js";
import type { BacktestResultReplayCursor, BacktestRunRecord } from "../../backtest/backtestTypes.js";
import { isBacktestTerminalState } from "../../backtest/backtestRunClient.js";
import { StrategyRunStreamError, type StrategyRunUpdate } from "../../backtest/backtestRunStream.js";
import { ChartStrategyResultCache } from "../../backtest/chart-tester/chartStrategyResultCache.js";
import { runResearchBacktest, type ChartStrategyRunApi } from "../../backtest/chart-tester/chartStrategyRunRequest.js";
import { defaultContinuousApi } from "../../backtest/continuous/continuousApi.js";
import type { ContinuousApi } from "../../backtest/continuous/continuousTypes.js";
import { ContinuousStrategyDataManager } from "./continuousStrategyDataManager.js";

type ResearchRequest = Omit<Parameters<typeof runResearchBacktest>[0], "api" | "waitForTerminal" | "wait" | "pollIntervalMs">;
export type StrategyDataApi = ChartStrategyRunApi & Pick<BacktestApiClient, "streamRun" | "getReport" | "getChart" | "cancelRun" | "listRuns" | "compareRuns"> & Partial<Pick<BacktestApiClient, "getResultReplay">>;

/** Owns fixed-history operations and immutable results independently of live
 * chart stores. Releasing a consumer never cancels a durable shared run. */
export class StrategyDataManager {
  private readonly operations = new Set<AbortController>();
  private readonly results = new ChartStrategyResultCache();
  private readonly updates = new Map<string, StrategyRunUpdate>();
  private readonly retainedResults: string[] = [];
  private streams = 0;
  private closed = false;

  readonly continuous: ContinuousStrategyDataManager;

  constructor(private readonly api: StrategyDataApi = defaultBacktestApi, continuousApi: ContinuousApi = defaultContinuousApi) {
    this.continuous = new ContinuousStrategyDataManager(continuousApi, (signal, action) => this.operation(signal, action));
  }

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

  loadResultReplay(cursor: BacktestResultReplayCursor, signal?: AbortSignal) {
    return this.operation(signal, async (owned) => {
      if (!this.api.getResultReplay) throw new StrategyRunStreamError("STRATEGY_STREAM_UNAVAILABLE", "Result replay is unavailable");
      const frame = await this.api.getResultReplay(cursor, owned);
      const invalidBars = (bars: typeof frame.bars) => !Array.isArray(bars)
        || bars.some(bar => frame.time_ms === null || bar.open_time_ms > frame.time_ms
          || (bar.closed && bar.close_time_ms !== undefined && bar.close_time_ms > frame.time_ms));
      if ((frame.schema !== "candlescope.user-trade-result-replay/1" && frame.schema !== "candlescope.local-bar-result-replay/1")
        || frame.run_id !== cursor.runId
        || frame.snapshot_hash !== cursor.snapshotHash || frame.report_hash !== cursor.reportHash
        || frame.cursor !== cursor.cursor || frame.interval !== cursor.interval
        || !Number.isSafeInteger(frame.total) || frame.total < cursor.cursor
        || frame.comparison?.interval !== cursor.comparisonInterval
        || invalidBars(frame.bars) || (frame.comparison && invalidBars(frame.comparison.bars))
        || !Array.isArray(frame.fills) || !Array.isArray(frame.order_events)
        || !Array.isArray(frame.closed_bar_signals)
        || frame.closed_bar_signals.some(signal => signal.reveal_sequence > frame.cursor)
        || frame.fills.some((fill) => fill.cursor > frame.cursor)
        || frame.order_events.some((order) => order.reveal_sequence > frame.cursor)) {
        throw new StrategyRunStreamError("DATA_SNAPSHOT_MISMATCH", "Result replay frame does not match the requested boundary");
      }
      return frame;
    });
  }

  restoreRun(runId: string, signal?: AbortSignal) {
    return this.operation(signal, async (owned) => {
      const current = await this.api.getRun(runId, owned);
      const terminal = isBacktestTerminalState(current.state) && current.state !== "FAILED" ? current : await this.wait(runId, owned);
      this.requireCompleted(terminal);
      return this.readResult(runId, owned);
    });
  }

  listRuns(signal?: AbortSignal) {
    return this.operation(signal, (owned) => this.api.listRuns(owned));
  }

  compareRuns(leftRunId: string, rightRunId: string, signal?: AbortSignal) {
    return this.operation(signal, async (owned) => {
      if (!leftRunId || !rightRunId || leftRunId === rightRunId) {
        throw new StrategyRunStreamError("COMPARISON_PAIR_INVALID", "Select two different runs");
      }
      const comparison = await this.api.compareRuns(leftRunId, rightRunId, owned);
      if (comparison.schema !== "RUN_COMPARE_V3" || comparison.left.runId !== leftRunId || comparison.right.runId !== rightRunId) {
        throw new StrategyRunStreamError("RESULT_IDENTITY_MISMATCH", "Comparison response does not match the selected runs");
      }
      return comparison;
    });
  }

  cancelRun(runId: string, signal?: AbortSignal) {
    return this.operation(signal, (owned) => this.api.cancelRun(runId, owned));
  }

  diagnostics() {
    return { closed: this.closed, operations: this.operations.size, streams: this.streams,
      continuous: this.continuous.diagnostics(), results: this.results.diagnostics(), runs: [...this.updates].map(([runId, event]) => ({
        runId, state: event.run.state, snapshotHash: event.run.snapshot_hash,
        configHash: event.run.config_hash, progress: event.progress,
      })) };
  }

  dispose(): void {
    this.closed = true;
    this.continuous.dispose();
    for (const operation of this.operations) operation.abort();
    this.results.clear();
    this.retainedResults.length = 0;
    this.updates.clear();
  }
}
