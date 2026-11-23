import type { ChartStrategyRunRequest } from "../backtest/chart-tester/chartStrategyTesterUiModel.js";
import type { ResearchExperimentInput } from "../backtest/chart-tester/chartStrategyRunRequest.js";
import type { StrategyExperiment } from "../backtest/experiment/strategyExperiment.js";
import type { LocalDatasetManifest } from "../local-data/localDataTypes.js";
import type { StrategyDataManager } from "../market-data/manager/strategyDataManager.js";
import { importedResearchRange, importedResearchRunSource } from "./importedDatasetSource.js";
import { RESEARCH_BATCH_MAX_INPUTS, marketInputKey, supportsBatchSource, validMarketInput, type ResearchMarketInput } from "./strategyResearchBatch.js";

type ExperimentManager = Pick<StrategyDataManager, "createResearchExperiment" | "listExperiments" | "watchExperiment"
  | "cancelExperiment" | "retryExperimentMember" | "createRobustnessExperiment" | "revealExperimentHoldout" | "adoptStudyExperiment">;
export interface ResearchExperimentsState { experiments: readonly StrategyExperiment[]; loaded: boolean; failed: boolean }

/**
 * The research page's batch runs as backend experiments (ADR-BACKTEST-015 P5b): one strategy over
 * several inputs. The backend submits and keeps the members; this page lists them and follows the
 * active ones through their streams. Leaving the page or switching its chart stops only the watching.
 */
export class ResearchExperiments {
  private state: ResearchExperimentsState = { experiments: [], loaded: false, failed: false };
  private readonly listeners = new Set<() => void>();
  private readonly watches = new Map<string, AbortController>();
  private closed = false;

  constructor(private readonly manager: ExperimentManager) {}

  snapshot = (): ResearchExperimentsState => this.state;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  private publish(next: ResearchExperimentsState): void {
    if (this.closed) return;
    this.state = next;
    this.listeners.forEach((listener) => listener());
  }

  /** Show an experiment as served: newest first, replacing its previous view. */
  private upsert(experiment: StrategyExperiment): void {
    const others = this.state.experiments.filter((item) => item.experimentId !== experiment.experimentId);
    this.publish({ ...this.state, experiments: [experiment, ...others].sort((a, b) => b.createdAtMs - a.createdAtMs) });
    if (!experiment.terminal) this.watch(experiment.experimentId);
  }

  private watch(experimentId: string): void {
    if (this.closed || this.watches.has(experimentId)) return;
    const controller = new AbortController();
    this.watches.set(experimentId, controller);
    void this.manager.watchExperiment(experimentId, (value) => this.upsert(value), controller.signal)
      .catch(() => undefined)  // the list keeps the last state; reopening the page follows it again
      .finally(() => { if (this.watches.get(experimentId) === controller) this.watches.delete(experimentId); });
  }

  /** Load the newest experiments and follow the ones still running. */
  start(): void {
    this.closed = false;
    void this.manager.listExperiments(20).then((experiments) => {
      this.publish({ experiments, loaded: true, failed: false });
      for (const experiment of experiments) if (!experiment.terminal) this.watch(experiment.experimentId);
    }, () => this.publish({ ...this.state, loaded: true, failed: true }));
  }

  /** Run the request over the chosen imported datasets and exchange histories as one experiment. */
  async submit(request: ChartStrategyRunRequest, datasets: readonly LocalDatasetManifest[],
    markets: readonly ResearchMarketInput[] = []): Promise<StrategyExperiment> {
    const count = datasets.length + markets.length;
    const precise = request.attachment.fidelityPreference === "PRECISE";
    if (count < (markets.length ? 1 : 2) || count > RESEARCH_BATCH_MAX_INPUTS
      || new Set(datasets.map((dataset) => dataset.dataset_id)).size !== datasets.length
      || new Set(markets.map(marketInputKey)).size !== markets.length
      || datasets.some((dataset) => !supportsBatchSource(dataset, precise))
      || markets.some((market) => !validMarketInput(market))
      || request.attachment.pythonBarExecution
      || (request.language === "python" && !request.pythonTrustedConfirmed)) throw new Error("RESEARCH_BATCH_UNSUPPORTED");
    const inputs: ResearchExperimentInput[] = [
      ...datasets.map((dataset) => {
        const { startMs, endMs } = importedResearchRange(dataset, request.attachment);
        return {
          input: { kind: "IMPORTED_DATASET", datasetId: dataset.dataset_id, dataEpoch: dataset.data_epoch, name: dataset.name,
            symbol: dataset.symbol, interval: dataset.interval, startMs, endMs },
          source: importedResearchRunSource(dataset, request.attachment),
        };
      }),
      ...markets.map(({ session, startMs, endMs }) => ({
        input: { kind: "EXCHANGE_SERIES", exchange: session.exchange, marketType: session.marketType, symbol: session.symbol,
          interval: session.interval, startMs, endMs },
        source: { kind: "MARKET_HISTORY" as const, session: { ...session }, startMs, endMs },
      })),
    ];
    const experiment = await this.manager.createResearchExperiment({ request: structuredClone(request), inputs });
    this.upsert(experiment);
    return experiment;
  }

  /** Check the request's strategy for robustness over an imported dataset (a Study V2 in the backend). */
  async submitRobustness(request: ChartStrategyRunRequest, dataset: LocalDatasetManifest,
    fields: Parameters<ExperimentManager["createRobustnessExperiment"]>[0]["fields"]): Promise<StrategyExperiment> {
    const experiment = await this.manager.createRobustnessExperiment({ request: structuredClone(request),
      dataset: { dataset_id: dataset.dataset_id, data_epoch: dataset.data_epoch, interval: dataset.interval }, fields });
    this.upsert(experiment);
    return experiment;
  }

  /** Show a study the research tools made (a `?study=` link) as a robustness experiment. */
  async openStudy(studyId: string): Promise<StrategyExperiment> {
    const experiment = await this.manager.adoptStudyExperiment(studyId);
    this.upsert(experiment);
    return experiment;
  }

  /** Open a robustness check's holdout; the study runs it and the page follows it again. */
  async revealHoldout(experimentId: string): Promise<void> {
    this.upsert(await this.manager.revealExperimentHoldout(experimentId));
  }

  /** Stop the members still preparing or running; finished members keep their results. */
  async cancel(experimentId: string): Promise<void> {
    this.upsert(await this.manager.cancelExperiment(experimentId));
  }

  /** Submit a failed or stopped member again. */
  async retry(experimentId: string, ordinal: number): Promise<void> {
    this.upsert(await this.manager.retryExperimentMember(experimentId, ordinal));
  }

  dispose(): void {
    this.closed = true;
    for (const controller of this.watches.values()) controller.abort();
    this.watches.clear();
    this.listeners.clear();
  }
}
