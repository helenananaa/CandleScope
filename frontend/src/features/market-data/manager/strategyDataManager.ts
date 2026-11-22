import type { BacktestReplayChartOptions, BacktestReplayExtraSlot, BacktestResultReplayChart } from "../../backtest/backtestTypes.js";
import type { PreparationJob } from "../../data-preparation/api.js";
import {
  BacktestApiError, defaultBacktestApi, type BacktestApiClient, type ExternalProviderConnection, type StrategyReferenceKind, type StrategyRevisionRecord,
} from "../../backtest/backtestApi.js";
import type { BacktestResultReplayCursor, BacktestResultReplayNoteDraft, BacktestRunRecord } from "../../backtest/backtestTypes.js";
import { isBacktestTerminalState } from "../../backtest/backtestRunClient.js";
import { StrategyRunStreamError, type StrategyRunUpdate } from "../../backtest/backtestRunStream.js";
import { ChartStrategyResultCache } from "../../backtest/chart-tester/chartStrategyResultCache.js";
import {
  buildImportedExternalRunBody, buildResearchExperimentMembers, runChartStrategyBacktest, runResearchBacktest,
  type ChartStrategyRunApi, type ResearchExperimentInput,
} from "../../backtest/chart-tester/chartStrategyRunRequest.js";
import type { ChartStrategyRunRequest } from "../../backtest/chart-tester/chartStrategyTesterUiModel.js";
import { defaultNativeRunClient, type NativeExecutionMode, type NativeRun, type NativeRunClient } from "../../backtest/native/nativeBacktestApi.js";
import { externalSnapshotRequest, matchingExternalConnections } from "../../backtest/research/externalProviderModel.js";
import { defaultContinuousApi } from "../../backtest/continuous/continuousApi.js";
import type { ContinuousApi } from "../../backtest/continuous/continuousTypes.js";
import { ContinuousStrategyDataManager } from "./continuousStrategyDataManager.js";
import { holdFollow, type HeldFollow } from "../../backtest/follow/hostFollow.js";
import { parseStrategyExperiment, type StrategyExperiment } from "../../backtest/experiment/strategyExperiment.js";
import { parseRunResult, RUN_RESULT_FAMILY_IDENTITY, RunResultContractError, type RunResult, type RunResultFamily } from "../../backtest/runResult/runResult.js";
import {
  parseStrategyRunCapabilities, parseStrategyRunStatus, parseStrategyVersion, StrategyRunContractError,
  type StrategyRunCapabilities, type StrategyRunProgress, type StrategyRunStatus, type StrategyVersion,
} from "../../backtest/runResult/strategyRun.js";

const RETAINED_RUN_RESULTS = 8;

type ExternalInput = Omit<Parameters<typeof buildImportedExternalRunBody>[0], "api" | "signal">;
type ExternalRunDraft = { readonly revision: StrategyRevisionRecord; readonly body: Record<string, unknown> };

type ResearchRequest = Omit<Parameters<typeof runResearchBacktest>[0], "api" | "waitForTerminal">;
export type StrategyDataApi = ChartStrategyRunApi & Pick<BacktestApiClient, "streamRun" | "getReport" | "getChart" | "cancelRun" | "listRuns" | "compareRuns"> & Pick<BacktestApiClient, "getResultReplay" | "saveResultReplayNote" | "observeStrategyPreparation">
  & Partial<Pick<BacktestApiClient, "capabilities" | "listStrategyRevisions" | "externalProviders"
    | "getStrategyRun" | "getStrategyRunResult" | "cancelStrategyRun" | "strategyRunCapabilities" | "watchStrategyRun"
    | "compareRecentRun" | "createResearchLaunchContext" | "getSelectedVersion"
    | "getStrategyVersion" | "strategyVersionNames" | "nameStrategyVersion" | "unnameStrategyVersion"
    | "getStrategyReference" | "listStrategyReferences" | "putStrategyReference" | "removeStrategyReference" | "importStrategyReferences"
    | "holdStrategyFollow" | "renewStrategyFollow" | "releaseStrategyFollow"
    | "createStrategyExperiment" | "getStrategyExperiment" | "listStrategyExperiments" | "cancelStrategyExperiment"
    | "retryStrategyExperimentMember" | "watchStrategyExperiment"
    | "exportRun" | "getSignalTrace" | "createReviewBridge" | "revealReviewBridge">>;

/** Owns fixed-history operations and immutable results independently of live
 * chart stores. Releasing a consumer never cancels a durable shared run. */
export class StrategyDataManager {
  private readonly operations = new Set<AbortController>();
  private readonly results = new ChartStrategyResultCache();
  private readonly updates = new Map<string, StrategyRunUpdate>();
  private readonly retainedResults: string[] = [];
  /** Completed run results never change, so parsed values are kept by family and run id. */
  private readonly runResults = new Map<string, RunResult>();
  private runCapabilities: StrategyRunCapabilities | null = null;
  private streams = 0;
  private closed = false;

  readonly continuous: ContinuousStrategyDataManager;

  constructor(private readonly api: StrategyDataApi = defaultBacktestApi, continuousApi: ContinuousApi = defaultContinuousApi,
    private readonly nativeRuns: NativeRunClient = defaultNativeRunClient) {
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

  private externalProviderApi() {
    if (!this.api.externalProviders) {
      throw new StrategyRunStreamError("FLAG_DISABLED", "External model connections are unavailable");
    }
    return this.api.externalProviders;
  }

  externalModelRevisions(signal?: AbortSignal) {
    return this.operation(signal, async (owned) => {
      const capabilities = await this.api.capabilities?.(owned);
      if (!capabilities?.flags.BACKTEST_EXTERNAL_PROVIDER_ENABLED) return null;
      const revisions = await this.api.listStrategyRevisions?.(owned) ?? [];
      return revisions.filter(revision => revision.provider_kind === "EXTERNAL_PROVIDER");
    });
  }

  registerExternalModel(input: { name: string; manifest: Record<string, unknown> } | null, signal?: AbortSignal) {
    return this.operation(signal, async (owned) => {
      const manifest = input?.manifest ?? (await this.externalProviderApi().example(owned)).manifest;
      return this.api.createStrategyRevision({
        name: input?.name ?? String(manifest.provider_id),
        language: "EXTERNAL_PROVIDER",
        source_text: JSON.stringify(manifest),
        parameter_schema: [],
      }, owned);
    });
  }

  prepareExternalModel(input: ExternalInput, signal?: AbortSignal): Promise<ExternalRunDraft> {
    return this.operation(signal, async (owned) => ({
      revision: input.revision,
      body: await buildImportedExternalRunBody({ ...input, api: this.api, signal: owned }),
    }));
  }

  externalModelConnections(draft: ExternalRunDraft, signal?: AbortSignal) {
    return this.operation(signal, async (owned) =>
      matchingExternalConnections(await this.externalProviderApi().list(owned), draft.body, draft.revision));
  }

  createExternalModelConnection(draft: ExternalRunDraft, signal?: AbortSignal) {
    return this.operation(signal, (owned) => this.externalProviderApi().create(externalSnapshotRequest(draft.body), owned));
  }

  revokeExternalModelConnection(connectionId: string, signal?: AbortSignal) {
    return this.operation(signal, (owned) => this.externalProviderApi().revoke(connectionId, owned));
  }

  startExternalModel(draft: ExternalRunDraft, connection: ExternalProviderConnection, parameters: Record<string, unknown>, signal?: AbortSignal) {
    return this.operation(signal, async (owned) => {
      if (!connection.ready || !matchingExternalConnections([connection], draft.body, draft.revision).length) {
        throw new StrategyRunStreamError("PROVIDER_CONNECTION_REQUIRED", "Connect the external model for this frozen snapshot");
      }
      const body = { ...draft.body, parameters, external_connection_id: connection.connection_id };
      await this.externalProviderApi().smoke(connection.connection_id, {
        ...externalSnapshotRequest(draft.body),
        parameters,
        output_mode: draft.body.output_mode,
      }, owned);
      await this.api.validate(body, owned);
      owned.throwIfAborted();
      return this.api.createRun(body, crypto.randomUUID(), owned);
    });
  }

  observeResearchPreparation(id: string, scope: string, retry: boolean, onProgress: (job: PreparationJob) => void | Promise<void>): Promise<PreparationJob> {
    return this.operation(undefined, (signal) => {
      if (!this.api.observeStrategyPreparation) {
        throw new StrategyRunStreamError("STRATEGY_PREPARATION_UNAVAILABLE", "Strategy preparation is unavailable");
      }
      return this.api.observeStrategyPreparation(id, scope, retry, onProgress, signal);
    });
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

  /** Any run's current status through the run facade (ADR-BACKTEST-015 P2). Never cached. */
  loadRunStatus(runId: string, signal?: AbortSignal): Promise<StrategyRunStatus> {
    return this.operation(signal, async (owned) => {
      if (!this.api.getStrategyRun) unavailable();
      const status = parseStrategyRunStatus(await this.api.getStrategyRun(runId, owned));
      owned.throwIfAborted();
      if (status.run_id !== runId) throw new StrategyRunContractError("run_id", `asked for ${runId}, served ${status.run_id}`);
      return status;
    });
  }

  /**
   * Follow one fixed run's committed status until it finishes (ADR-BACKTEST-015 P2b).
   * Resolves with the terminal status, whatever its outcome; releasing the watch never cancels the run.
   */
  watchRun(runId: string, onStatus?: (status: StrategyRunStatus, progress: StrategyRunProgress | null) => void,
    signal?: AbortSignal): Promise<StrategyRunStatus> {
    return this.operation(signal, async (owned) => {
      if (!this.api.watchStrategyRun) unavailable();
      this.streams += 1;
      try {
        return await this.api.watchStrategyRun(runId, owned, (status, progress) => {
          if (!owned.aborted && !this.closed) onStatus?.(status, progress);
        });
      } finally {
        this.streams -= 1;
      }
    });
  }

  /** The backend's settings for fixed runs (feature flags such as the replay review bridge). */
  loadBacktestCapabilities(signal?: AbortSignal) {
    return this.operation(signal, async (owned) => {
      if (!this.api.capabilities) unavailable();
      return this.api.capabilities(owned);
    });
  }

  /** The server's export of a fixed run: its configuration, report and hashes, as one JSON document. */
  exportRun(runId: string, signal?: AbortSignal): Promise<Record<string, unknown>> {
    return this.operation(signal, async (owned) => {
      if (!this.api.exportRun) unavailable();
      return this.api.exportRun(runId, owned);
    });
  }

  /** A page of a fixed run's recorded strategy decisions, oldest first. */
  loadSignalTrace(runId: string, after = 0, limit = 1_000, signal?: AbortSignal) {
    return this.operation(signal, async (owned) => {
      if (!this.api.getSignalTrace) unavailable();
      return this.api.getSignalTrace(runId, after, limit, owned);
    });
  }

  /**
   * A blind review of a completed run in training replay (ADR-BACKTEST-001): the server creates a
   * training session over the run's window that shares only the fixed data and a read-only result.
   */
  createReviewBridge(runId: string, startTimeMs: number, endTimeMs: number, signal?: AbortSignal): Promise<Record<string, unknown>> {
    return this.operation(signal, async (owned) => {
      if (!this.api.createReviewBridge) unavailable();
      return this.api.createReviewBridge(runId, startTimeMs, endTimeMs, owned);
    });
  }

  revealReviewBridge(bridgeId: string, signal?: AbortSignal): Promise<Record<string, unknown>> {
    return this.operation(signal, async (owned) => {
      if (!this.api.revealReviewBridge) unavailable();
      return this.api.revealReviewBridge(bridgeId, owned);
    });
  }

  /**
   * Experiments (ADR-BACKTEST-015 P5b): one strategy run over several inputs. The backend submits and
   * keeps the members; a closed page, a switched chart or a restart does not cancel or lose them.
   */
  createExperiment(body: Record<string, unknown>, signal?: AbortSignal): Promise<StrategyExperiment> {
    return this.operation(signal, async (owned) => {
      if (!this.api.createStrategyExperiment) unavailable();
      return parseStrategyExperiment(await this.api.createStrategyExperiment(body, owned));
    });
  }

  loadExperiment(experimentId: string, signal?: AbortSignal): Promise<StrategyExperiment> {
    return this.operation(signal, async (owned) => {
      if (!this.api.getStrategyExperiment) unavailable();
      return parseStrategyExperiment(await this.api.getStrategyExperiment(experimentId, owned));
    });
  }

  /**
   * Run one research request over several inputs as an experiment (ADR-BACKTEST-015 P5b): its members
   * are built here (one strategy revision, each input's snapshot or preparation) and kept by the backend.
   */
  createResearchExperiment(input: { request: ChartStrategyRunRequest; inputs: readonly ResearchExperimentInput[] },
    signal?: AbortSignal): Promise<StrategyExperiment> {
    return this.operation(signal, async (owned) => {
      if (!this.api.createStrategyExperiment) unavailable();
      const { revision, members } = await buildResearchExperimentMembers({ api: this.api, request: input.request, inputs: input.inputs, signal: owned });
      return parseStrategyExperiment(await this.api.createStrategyExperiment({
        idempotency_key: crypto.randomUUID(),
        name: input.request.displayName,
        strategy: { language: input.request.language, draft_id: input.request.draftId,
          draft_content_revision: input.request.draftContentRevision, strategy_revision_id: revision.revision_id },
        members,
      }, owned));
    });
  }

  /** The newest experiments, newest first. */
  listExperiments(limit = 20, signal?: AbortSignal): Promise<StrategyExperiment[]> {
    return this.operation(signal, async (owned) => {
      if (!this.api.listStrategyExperiments) unavailable();
      const body = await this.api.listStrategyExperiments(limit, owned) as { experiments?: unknown };
      if (!Array.isArray(body?.experiments)) throw new StrategyRunStreamError("STRATEGY_STREAM_INVALID", "experiments must be a list");
      return body.experiments.map(parseStrategyExperiment);
    });
  }

  /** Stop the members still preparing or running; finished members keep their results. */
  cancelExperiment(experimentId: string, signal?: AbortSignal): Promise<StrategyExperiment> {
    return this.operation(signal, async (owned) => {
      if (!this.api.cancelStrategyExperiment) unavailable();
      return parseStrategyExperiment(await this.api.cancelStrategyExperiment(experimentId, owned));
    });
  }

  /** Submit a failed or cancelled member again. */
  retryExperimentMember(experimentId: string, ordinal: number, signal?: AbortSignal): Promise<StrategyExperiment> {
    return this.operation(signal, async (owned) => {
      if (!this.api.retryStrategyExperimentMember) unavailable();
      return parseStrategyExperiment(await this.api.retryStrategyExperimentMember(experimentId, ordinal, owned));
    });
  }

  /**
   * Follow an experiment through its commit-driven stream: each member's preparation and run
   * changes are reported, without polling. Resolves once no member is active; stopping the watch
   * never cancels the experiment.
   */
  watchExperiment(experimentId: string, onExperiment: (value: StrategyExperiment) => void,
    signal?: AbortSignal): Promise<StrategyExperiment> {
    return this.operation(signal, async (owned) => {
      if (!this.api.watchStrategyExperiment) unavailable();
      this.streams += 1;
      try {
        return await this.api.watchStrategyExperiment(experimentId, (value) => {
          if (!owned.aborted && !this.closed) onExperiment(value);
        }, owned);
      } finally {
        this.streams -= 1;
      }
    });
  }

  /**
   * Hold a chart FOLLOW run for one cell (ADR-BACKTEST-015 P4b) until `signal` aborts: create or
   * join it, renew its lease, and release it at the end. `onReady` reports the run to show once it
   * has a result. Rejects when the backend refuses the input; the caller keeps the fixed result.
   */
  holdFollowRun(body: Record<string, unknown>, holder: string, onReady: (held: HeldFollow) => void,
    signal: AbortSignal): Promise<void> {
    return this.operation(signal, (owned) => {
      const api = this.api;
      const hold = api.holdStrategyFollow, renew = api.renewStrategyFollow, release = api.releaseStrategyFollow;
      if (!hold || !renew || !release) unavailable();
      return holdFollow({
        hold: (value, at) => hold.call(api, value, at),
        renew: (followId, who, at) => renew.call(api, followId, who, at),
        release: (followId, who) => release.call(api, followId, who),
        ready: (followId, at) => this.followReady(followId, at),
        gone: (failure) => failure instanceof BacktestApiError && failure.status === 404,
      }, body, holder, onReady, owned);
    });
  }

  /** Resolves once a FOLLOW run has a result: it caught up, possibly as a recomputed generation. */
  private async followReady(runId: string, signal: AbortSignal): Promise<void> {
    for (;;) {
      const watch = new AbortController();
      const stop = () => watch.abort(signal.reason);
      signal.addEventListener("abort", stop, { once: true });
      let ready = false;
      try {
        const last = await this.watchRun(runId, (status) => {
          if (status.result_available) { ready = true; watch.abort(); }
        }, watch.signal);
        if (last.result_available) return;
        throw new StrategyRunStreamError(last.error?.code ?? "RUN_STOPPED", "The FOLLOW run stopped before it had a result");
      } catch (failure) {
        if (ready) return;
        if (signal.aborted) throw failure;
        if (failure instanceof StrategyRunStreamError && failure.code === "RUN_IDENTITY_CHANGED") continue;
        throw failure;
      } finally {
        signal.removeEventListener("abort", stop);
      }
    }
  }

  /**
   * Follow a host run to its end through the run facade's status stream. Updates carry the
   * run's header with its new state; the full record is read once at the end and returned
   * whatever the outcome (a failed run is a result, not an error).
   */
  followHostRun(runId: string, onUpdate?: (run: BacktestRunRecord) => void, signal?: AbortSignal): Promise<BacktestRunRecord> {
    return this.operation(signal, async (owned) => {
      let latest = await this.api.getRun(runId, owned);
      if (isBacktestTerminalState(latest.state)) return latest;
      if (!this.api.watchStrategyRun) unavailable();
      this.streams += 1;
      try {
        await this.api.watchStrategyRun(runId, owned, (status) => {
          if (owned.aborted || this.closed || status.terminal || status.source_state === latest.state) return;
          latest = { ...latest, state: status.source_state as BacktestRunRecord["state"] };
          onUpdate?.(latest);
        });
      } finally {
        this.streams -= 1;
      }
      const record = await this.api.getRun(runId, owned);
      if (!isBacktestTerminalState(record.state)) {
        throw new StrategyRunStreamError("RESULT_IDENTITY_MISMATCH", "The finished run's record is not terminal");
      }
      return record;
    });
  }

  /** Run the chart's strategy on the chart's history; the run is followed by stream, not polled. */
  runChartStrategy(options: Omit<Parameters<typeof runChartStrategyBacktest>[0], "api" | "waitForTerminal">) {
    return this.operation(options.signal, (signal) => runChartStrategyBacktest({
      ...options, api: this.api, signal,
      waitForTerminal: (runId, _signal, onUpdate) => this.followHostRun(runId, onUpdate, signal),
    }));
  }

  compareRecentRun(runId: string, signal?: AbortSignal) {
    return this.operation(signal, (owned) => {
      if (!this.api.compareRecentRun) unavailable();
      return this.api.compareRecentRun(runId, owned);
    });
  }

  /** The strategy version a research run selected, for returning it to a chart. */
  loadSelectedRunVersion(runId: string, signal?: AbortSignal) {
    return this.operation(signal, (owned) => {
      if (!this.api.getSelectedVersion) unavailable();
      return this.api.getSelectedVersion(runId, owned);
    });
  }

  createResearchLaunchContext(payload: Parameters<BacktestApiClient["createResearchLaunchContext"]>[0]) {
    return this.operation(undefined, () => {
      if (!this.api.createResearchLaunchContext) unavailable();
      return this.api.createResearchLaunchContext(payload);
    });
  }

  // -- Strategy versions (ADR-BACKTEST-015 P3b) -----------------------------

  /** The exact code of a version, with the names pointing at it. */
  loadStrategyVersion(versionHash: string, signal?: AbortSignal): Promise<StrategyVersion> {
    return this.operation(signal, async (owned) => {
      if (!this.api.getStrategyVersion) unavailable();
      const version = parseStrategyVersion(await this.api.getStrategyVersion(versionHash, owned));
      if (version.version_hash !== versionHash) throw new StrategyRunContractError("version_hash", `asked for ${versionHash}, served ${version.version_hash}`);
      return version;
    });
  }

  listStrategyVersionNames(signal?: AbortSignal) {
    return this.operation(signal, async (owned) => {
      if (!this.api.strategyVersionNames) unavailable();
      return (await this.api.strategyVersionNames(owned)).names;
    });
  }

  /** "Named save": point a name at a version. Naming again moves the name. */
  nameStrategyVersion(name: string, versionHash: string, signal?: AbortSignal) {
    return this.operation(signal, (owned) => {
      if (!this.api.nameStrategyVersion) unavailable();
      return this.api.nameStrategyVersion(name, versionHash, owned);
    });
  }

  unnameStrategyVersion(name: string, signal?: AbortSignal) {
    return this.operation(signal, (owned) => {
      if (!this.api.unnameStrategyVersion) unavailable();
      return this.api.unnameStrategyVersion(name, owned);
    });
  }

  // -- Strategy references (ADR-BACKTEST-015 P3c) ---------------------------

  /** A reference's stored value (unvalidated: each kind's reader validates it), or null. */
  loadStrategyReference(kind: StrategyReferenceKind, key: string, signal?: AbortSignal): Promise<unknown> {
    return this.operation(signal, (owned) => {
      if (!this.api.getStrategyReference) unavailable();
      return this.api.getStrategyReference(kind, key, owned);
    });
  }

  listStrategyReferences(kind: StrategyReferenceKind, prefix = "", signal?: AbortSignal) {
    return this.operation(signal, (owned) => {
      if (!this.api.listStrategyReferences) unavailable();
      return this.api.listStrategyReferences(kind, prefix, owned);
    });
  }

  saveStrategyReference(kind: StrategyReferenceKind, key: string, value: unknown, signal?: AbortSignal): Promise<void> {
    return this.operation(signal, (owned) => {
      if (!this.api.putStrategyReference) unavailable();
      return this.api.putStrategyReference(kind, key, value, owned);
    });
  }

  removeStrategyReference(kind: StrategyReferenceKind, key: string, signal?: AbortSignal): Promise<void> {
    return this.operation(signal, (owned) => {
      if (!this.api.removeStrategyReference) unavailable();
      return this.api.removeStrategyReference(kind, key, owned);
    });
  }

  /** Bring browser-storage entries in once; entries the backend already holds are kept. */
  importStrategyReferences(kind: StrategyReferenceKind, entries: Array<{ key: string; value: unknown }>, signal?: AbortSignal) {
    return this.operation(signal, (owned) => {
      if (!this.api.importStrategyReferences) unavailable();
      return this.api.importStrategyReferences(kind, entries, owned);
    });
  }

  // -- Native and CandleScope-matched runs ----------------------------------

  createNativeRun(mode: NativeExecutionMode, body: Record<string, unknown>, idempotencyKey: string, signal?: AbortSignal): Promise<NativeRun> {
    return this.operation(signal, (owned) => this.nativeRuns.create(mode, body, idempotencyKey, owned));
  }

  loadNativeRun(mode: NativeExecutionMode, runId: string, signal?: AbortSignal): Promise<NativeRun> {
    return this.operation(signal, (owned) => this.nativeRuns.get(mode, runId, owned));
  }

  /** The recent runs of one mode, plus any `include` ids the list no longer holds (unreadable ones are skipped). */
  listNativeRuns(mode: NativeExecutionMode, include: Iterable<string> = [], signal?: AbortSignal): Promise<NativeRun[]> {
    return this.operation(signal, async (owned) => {
      const runs = await this.nativeRuns.list(mode, owned);
      const listed = new Set(runs.map((run) => run.run_id));
      const missing = [...new Set(include)].filter((runId) => !listed.has(runId));
      const restored = await Promise.all(missing.map((runId) => this.nativeRuns.get(mode, runId, owned).catch(() => null)));
      return [...runs, ...restored.filter((run): run is NativeRun => run !== null)];
    });
  }

  cancelNativeRun(mode: NativeExecutionMode, runId: string, signal?: AbortSignal): Promise<NativeRun> {
    return this.operation(signal, (owned) => this.nativeRuns.cancel(mode, runId, owned));
  }

  /**
   * Follow a native run through the run facade's stream (no polling). Each committed state
   * change updates its header; the finished record (result or error) is read once.
   */
  followNativeRun(current: NativeRun, onRun: (run: NativeRun) => void, signal?: AbortSignal): Promise<NativeRun> {
    return this.operation(signal, async (owned) => {
      let latest = current;
      const mode: NativeExecutionMode = current.execution_mode === "CANDLESCOPE" ? "CANDLESCOPE" : "NATIVE";
      if (!this.api.watchStrategyRun) unavailable();
      this.streams += 1;
      let terminal: StrategyRunStatus;
      try {
        terminal = await this.api.watchStrategyRun(current.run_id, owned, (status) => {
          if (owned.aborted || this.closed || status.terminal || status.source_state === latest.state) return;
          latest = { ...latest, state: status.source_state };
          onRun(latest);
        });
      } finally {
        this.streams -= 1;
      }
      const record = await this.nativeRuns.get(mode, current.run_id, owned);
      if (record.run_id !== current.run_id || record.state !== terminal.source_state) {
        throw new StrategyRunStreamError("RESULT_IDENTITY_MISMATCH", "Native run record differs from its finished status");
      }
      onRun(record);
      return record;
    });
  }

  /** Cancel any run family's run; returns its status. Cancelling a finished run changes nothing. */
  cancelStrategyRun(runId: string, signal?: AbortSignal): Promise<StrategyRunStatus> {
    return this.operation(signal, async (owned) => {
      if (!this.api.cancelStrategyRun) unavailable();
      const status = parseStrategyRunStatus(await this.api.cancelStrategyRun(runId, owned));
      if (status.run_id !== runId) throw new StrategyRunContractError("run_id", `asked for ${runId}, served ${status.run_id}`);
      return status;
    });
  }

  /**
   * The backend's one capability matrix. Reading it starts the script engines to
   * describe them, so it is kept until `refresh` asks again.
   */
  loadRunCapabilities(signal?: AbortSignal, { refresh = false }: { refresh?: boolean } = {}): Promise<StrategyRunCapabilities> {
    return this.operation(signal, async (owned) => {
      if (this.runCapabilities && !refresh) return this.runCapabilities;
      if (!this.api.strategyRunCapabilities) unavailable();
      const capabilities = parseStrategyRunCapabilities(await this.api.strategyRunCapabilities(owned));
      owned.throwIfAborted();
      this.runCapabilities = capabilities;
      return capabilities;
    });
  }

  /**
   * A run in `candlescope.run-result/1` (ADR-BACKTEST-015 P1), validated against its family.
   * A finished fixed run never changes, so it is cached; a forward run's result is its
   * committed account at the moment of the read (P2d), and a FOLLOW run's its state at the
   * chart's newest applied bar (P4b), so those are read every time.
   */
  loadRunResult(family: RunResultFamily, runId: string, signal?: AbortSignal): Promise<RunResult> {
    return this.operation(signal, async (owned) => {
      const key = `${family}\u0000${runId}`;
      const clock = family === "continuous" ? "FORWARD" : family === "follow" ? "FOLLOW" : "FIXED";
      const live = clock !== "FIXED";
      const cached = live ? undefined : this.runResults.get(key);
      if (cached) {
        this.runResults.delete(key);
        this.runResults.set(key, cached);
        return cached;
      }
      if (!this.api.getStrategyRunResult) unavailable();
      const raw = await this.api.getStrategyRunResult(runId, owned);
      owned.throwIfAborted();
      const result = parseRunResult(raw);
      const expected = RUN_RESULT_FAMILY_IDENTITY[family];
      if (result.source !== expected.source || result.authority !== expected.authority) {
        throw new RunResultContractError("source", `${family} runs must be served by ${expected.source} with ${expected.authority} authority`);
      }
      if (result.clock_policy !== clock) {
        throw new RunResultContractError("clock_policy", `${family} runs cannot be served as ${result.clock_policy}`);
      }
      if (live) return result;
      this.runResults.set(key, result);
      while (this.runResults.size > RETAINED_RUN_RESULTS) this.runResults.delete(this.runResults.keys().next().value!);
      return result;
    });
  }

  loadResultReplay(cursor: BacktestResultReplayCursor, signal?: AbortSignal) {
    return this.operation(signal, async (owned) => {
      if (!this.api.getResultReplay) throw new StrategyRunStreamError("STRATEGY_STREAM_UNAVAILABLE", "Result replay is unavailable");
      const frame = await this.api.getResultReplay(cursor, owned);
      const invalidBars = (bars: typeof frame.bars) => !Array.isArray(bars)
        || bars.some(bar => !bar || frame.time_ms === null || bar.open_time_ms > frame.time_ms
          || (bar.closed && bar.close_time_ms !== undefined && bar.close_time_ms > frame.time_ms));
      const invalidStudy = (study: typeof frame.ma, period: number | undefined, bars: typeof frame.bars) => {
        if (period === undefined) return study !== undefined;
        if (study?.period !== period || !Array.isArray(study.points) || study.points.length > bars.length) return true;
        const closed = new Set(bars.filter(bar => bar.closed && bar.close_time_ms !== undefined).map(bar => bar.open_time_ms));
        let previous = -Infinity;
        return study.points.some(point => {
          const invalid = !point || !closed.has(point.open_time_ms) || point.open_time_ms <= previous
            || !Number.isFinite(point.value);
          if (!invalid) previous = point.open_time_ms;
          return invalid;
        });
      };
      const comparison = frame.comparison;
      const invalidChart = (chart: BacktestResultReplayChart | null | undefined, requested: BacktestReplayChartOptions | undefined) => {
        if (requested === undefined) return chart != null;
        if (!chart || chart.interval !== requested.interval
          || chart.dataset_id !== requested.dataset?.datasetId || chart.data_epoch !== requested.dataset?.dataEpoch
          || invalidBars(chart.bars) || invalidStudy(chart.ma, requested.maPeriod, chart.bars)) return true;
        return requested.dataset !== undefined && (typeof chart.symbol !== "string" || !chart.symbol
          || !Array.isArray(chart.display_intervals) || !chart.display_intervals.includes(chart.interval)
          || chart.display_intervals.some(interval => typeof interval !== "string")
          || chart.bars.some(bar => !bar.closed || !Number.isSafeInteger(bar.close_time_ms)));
      };
      const expectedCharts = cursor.additionalCharts ?? {};
      const extraCharts = frame.additional_charts;
      const invalidExtras = (extraCharts !== undefined && (!extraCharts || typeof extraCharts !== "object" || Array.isArray(extraCharts)))
        || Object.keys(extraCharts ?? {}).length !== Object.keys(expectedCharts).length
        || Object.entries(expectedCharts).some(([slot, chart]) => invalidChart(extraCharts?.[slot as BacktestReplayExtraSlot], chart));
      const notes = frame.notes;
      const invalidNotes = notes !== undefined && (!Array.isArray(notes) || notes.length > 100
        || new Set(notes.map(note => note?.id)).size !== notes.length
        || notes.some(note => !note || typeof note.id !== "string" || !Number.isSafeInteger(note.revision)
          || note.revision < 1 || note.revision > 20 || typeof note.body !== "string" || !note.body.trim()
          || !Number.isSafeInteger(note.cursor) || note.cursor < 0 || note.cursor > frame.cursor
          || (note.cursor === 0 ? note.time_ms !== null : (!Number.isSafeInteger(note.time_ms)
            || frame.time_ms === null || note.time_ms === null || note.time_ms > frame.time_ms))));
      if (invalidNotes || (frame.schema !== "candlescope.user-trade-result-replay/1" && frame.schema !== "candlescope.local-bar-result-replay/1")
        || frame.run_id !== cursor.runId
        || frame.snapshot_hash !== cursor.snapshotHash || frame.report_hash !== cursor.reportHash
        || frame.cursor !== cursor.cursor || frame.interval !== cursor.interval
        || !Number.isSafeInteger(frame.total) || frame.total < cursor.cursor
        || (frame.display_intervals !== undefined && (!Array.isArray(frame.display_intervals)
          || frame.display_intervals.some(interval => typeof interval !== "string")))
        || invalidChart(comparison, cursor.comparisonInterval ? { interval: cursor.comparisonInterval,
          ...(cursor.comparisonDataset ? { dataset: cursor.comparisonDataset } : {}),
          ...(cursor.comparisonMaPeriod === undefined ? {} : { maPeriod: cursor.comparisonMaPeriod }),
        } : undefined)
        || invalidExtras || invalidBars(frame.bars) || invalidStudy(frame.ma, cursor.maPeriod, frame.bars)
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

  saveResultReplayNote(cursor: BacktestResultReplayCursor, note: BacktestResultReplayNoteDraft, signal?: AbortSignal) {
    return this.operation(signal, async (owned) => {
      if (!this.api.saveResultReplayNote) throw new StrategyRunStreamError("STRATEGY_STREAM_UNAVAILABLE", "Result replay notes are unavailable");
      const saved = await this.api.saveResultReplayNote(cursor, note, owned);
      if (saved.revision !== note.expectedRevision + 1) {
        throw new StrategyRunStreamError("RESULT_IDENTITY_MISMATCH", "Result replay note revision does not match the requested save");
      }
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
      continuous: this.continuous.diagnostics(), results: this.results.diagnostics(), runResults: this.runResults.size, runs: [...this.updates].map(([runId, event]) => ({
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
    this.runResults.clear();
    this.runCapabilities = null;
    this.updates.clear();
  }
}

function unavailable(): never {
  throw new StrategyRunStreamError("STRATEGY_STREAM_UNAVAILABLE", "Run results are unavailable from this backend");
}
