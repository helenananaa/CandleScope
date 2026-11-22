import { readNdjsonUntilTerminal, readStrategyRunStream, StrategyRunStreamError, type StrategyRunUpdate } from "./backtestRunStream.js";
import { parseStrategyExperimentFrame, type StrategyExperiment } from "./experiment/strategyExperiment.js";
import { API_BASE } from "../../services/apiConfig.js";
import { readStrategyRunStatusStream, type StrategyRunProgress, type StrategyRunStatus } from "./runResult/strategyRun.js";
import type { ResearchSelectedVersion } from "../strategy-research/researchSelectedVersion.js";
import { preparationRequest, waitForPreparation, type PreparationJob } from "../data-preparation/api.js";
import type {
  BacktestReport,
  BacktestChartData,
  BacktestResearchLaunchContext,
  BacktestResearchLaunchContextInput,
  BacktestResultReplayCursor,
  BacktestResultReplayFrame,
  BacktestResultReplayNoteDraft,
  BacktestRunRecord,
  RecentRunCompareV1,
  RunCompareV3,
  SignalTracePage,
  BacktestStudyComparison,
  BacktestStudyRecord,
} from "./backtestTypes.js";

export type { SignalTracePage } from "./backtestTypes.js";

export interface ExternalProviderIdentity {
  manifest_hash: string;
  provider_id: string;
  provider_revision: string;
  provider_kind: "MODEL" | "STRATEGY";
  artifact_sha256: string;
  runtime_lock: string;
  reproducibility: "RECORDED_OUTPUT_ONLY";
}

export interface ExternalProviderConnection {
  connection_id: string;
  scope: { strategy_revision_id: string; dataset_id: string; data_epoch: string; snapshot_hash: string; manifest_hash: string };
  scope_hash: string;
  connection_file: string;
  ready: boolean;
  example_command: string | null;
}

export interface ExternalProviderApi {
  example(signal?: AbortSignal): Promise<{ manifest: Record<string, unknown>; manifest_command: string }>;
  list(signal?: AbortSignal): Promise<ExternalProviderConnection[]>;
  create(body: Record<string, unknown>, signal?: AbortSignal): Promise<ExternalProviderConnection>;
  revoke(connectionId: string, signal?: AbortSignal): Promise<Record<string, unknown>>;
  smoke(connectionId: string, body: Record<string, unknown>, signal?: AbortSignal): Promise<Record<string, unknown>>;
  trace(runId: string, after?: number, signal?: AbortSignal): Promise<{ items: Array<Record<string, unknown>>; next_after: number; has_more: boolean }>;
}

export interface BacktestStrategyDescriptor {
  revision_id: string;
  provider_kind: string;
  language?: string;
  label: string;
  description: string;
  input_modes: string[];
  output_modes: string[];
  signal_clock: string;
  required_features: string[];
  warmup_requirement: Record<string, unknown>;
  parameter_schema: Array<Record<string, unknown>>;
  accepts_source: boolean;
  unsupported?: string[];
  source_hash?: string;
  compiled_hash?: string;
  runtime_revision?: string;
  external_provider?: ExternalProviderIdentity;
}

export interface StrategyRevisionRecord extends BacktestStrategyDescriptor {
  schema_version?: string;
  base_revision_id?: string;
  diagnostics?: Array<Record<string, unknown>>;
  reused?: boolean;
}

export interface BacktestCapabilities {
  runtime_mode?: "LIVE" | "LOCAL_OFFLINE";
  flags: Record<string, boolean>;
  fidelity_modes: string[];
  strategies: BacktestStrategyDescriptor[];
  account_models?: string[];
  funding_modes_v2?: string[];
  host_policy_revision?: string;
  sizing_policies?: string[];
  chart_context?: {
    schema_version: "candlescope.backtest-chart-context/1";
    enabled: boolean;
    resolve_is_local_only: boolean;
    materialize_requires_confirmation: boolean;
  };
  quick_presets?: BacktestQuickPreset[];
}

export interface BacktestQuickPreset {
  id: string;
  revision: string;
  label: string;
  market_types: string[];
  account_model: string;
  sizing_policy: string;
  equity_percent: string;
  initial_cash: string;
  leverage: string;
  fee_source: string;
  fee_bps: string;
  slippage_bps: string;
  execution_model_revision: string;
  contract_data_mode: string;
  funding_mode: string;
}

export type ChartContextStatus =
  | "READY"
  | "NEEDS_DATA"
  | "UNSUPPORTED_INTERVAL"
  | "UNSUPPORTED_FIDELITY"
  | "AMBIGUOUS_MARKET"
  | "UNAVAILABLE";

export interface ChartContextResolveRequest {
  exchange: string;
  market_type: string;
  symbol: string;
  interval: string;
  range_mode: "ALL_AVAILABLE" | "VISIBLE" | "CUSTOM";
  start_time_ms: number | null;
  end_time_ms: number | null;
  fidelity_preference: "FAST" | "PRECISE";
}

export interface ChartContextMaterializeRequest {
  resolution_token: string;
  user_confirmed: boolean;
  idempotency_key: string;
  expected_dataset_id?: string;
  expected_data_epoch?: string;
}

export interface ChartContextResolution {
  automatic_preparation_available?: boolean;
  prepared_run?: BacktestRunRecord;
  preparation?: { warmup_bars: number; requested_start_ms: number; prepared_start_ms: number };
  schema_version: "candlescope.backtest-chart-context/1";
  status: ChartContextStatus;
  resolution_token: string;
  chart_context_hash: string;
  expires_at_ms: number;
  request: ChartContextResolveRequest;
  dataset_id: string | null;
  data_epoch: string | null;
  snapshot_hash: string | null;
  coverage: {
    requested_start_ms: number | null;
    requested_end_ms: number | null;
    available_start_ms: number | null;
    available_end_ms: number | null;
    row_count: number | null;
    missing_ranges: Array<Record<string, unknown>>;
    complete: boolean;
  };
  fidelity: {
    preference: "FAST" | "PRECISE";
    mode: "BAR_APPROX" | "AGG_TRADE_EXECUTION";
    capabilities: string[];
  };
  quality_warnings: Array<{ code: string; message: string }>;
  quick_preset_id: string;
  cost_preset: Record<string, string>;
  account_execution_preset: Record<string, string>;
  materialize: {
    required: boolean;
    source_interval?: string;
    estimated_bars?: number | null;
    estimated_bytes?: number | null;
    reason?: string;
  };
}

export interface BacktestApiClient {
  externalProviders?: ExternalProviderApi;
  prepareChartContext?(body: ChartContextResolveRequest, signal?: AbortSignal, strategy?: {
    strategy_revision_id: string;
    python_runtime_mode?: string;
    python_trusted_confirmed?: boolean;
    parameters: Record<string, unknown>;
    pine_contexts?: unknown[];
      output_mode?: "SIGNAL" | "TARGET_POSITION" | "ORDER_INTENT";
    signal_chart?: import("../../shared/strategyRunSettings.js").ChartSignalDefinition;
    python_bar_execution?: import("../../shared/strategyRunSettings.js").PythonBarExecution;
    execution_overrides?: import("../../shared/strategyRunSettings.js").StrategyExecutionOverrides;
    chart_cell_scope: string;
    strategy_draft_id: string;
  }, idempotencyKey?: string, onProgress?: (job: PreparationJob) => void | Promise<void>): Promise<ChartContextResolution>;
  observeStrategyPreparation?(jobId: string, scope: string, retry: boolean,
    onProgress: (job: PreparationJob) => void | Promise<void>, signal?: AbortSignal): Promise<PreparationJob>;
  capabilities(signal?: AbortSignal): Promise<BacktestCapabilities>;
  listDatasets(signal?: AbortSignal): Promise<BacktestDataset[]>;
  previewSnapshot(
    body: SnapshotPreviewRequest,
    signal?: AbortSignal,
  ): Promise<BacktestSnapshot>;
  resolveChartContext(
    body: ChartContextResolveRequest,
    signal?: AbortSignal,
  ): Promise<ChartContextResolution>;
  materializeChartContext(
    body: ChartContextMaterializeRequest,
    signal?: AbortSignal,
  ): Promise<ChartContextResolution>;
  listRuns(signal?: AbortSignal): Promise<BacktestRunRecord[]>;
  listStrategyRevisions(signal?: AbortSignal): Promise<StrategyRevisionRecord[]>;
  validate(body: Record<string, unknown>, signal?: AbortSignal): Promise<{ ok: boolean }>;
  createRun(
    body: Record<string, unknown>,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<BacktestRunRecord>;
  getRun(runId: string, signal?: AbortSignal): Promise<BacktestRunRecord>;
  getSelectedVersion?(runId: string, signal?: AbortSignal): Promise<ResearchSelectedVersion>;
  streamRun?(runId: string, signal?: AbortSignal, onUpdate?: (event: StrategyRunUpdate) => void): Promise<BacktestRunRecord>;
  getReport(runId: string, signal?: AbortSignal): Promise<BacktestReport>;
  getChart(runId: string, signal?: AbortSignal): Promise<BacktestChartData>;
  /**
   * The run facade (ADR-BACKTEST-015 P2), one entry for every run family. Values are
   * unvalidated wire values: see `parseStrategyRunStatus`, `parseRunResult` and
   * `parseStrategyRunCapabilities`.
   */
  getStrategyRun?(runId: string, signal?: AbortSignal): Promise<unknown>;
  getStrategyRunResult?(runId: string, signal?: AbortSignal): Promise<unknown>;
  cancelStrategyRun?(runId: string, signal?: AbortSignal): Promise<unknown>;
  /** A commit-driven status stream for one fixed run; resolves with its terminal status. */
  watchStrategyRun?(runId: string, signal?: AbortSignal,
    onStatus?: (status: StrategyRunStatus, progress: StrategyRunProgress | null) => void): Promise<StrategyRunStatus>;
  strategyRunCapabilities?(signal?: AbortSignal): Promise<unknown>;
  /**
   * Chart FOLLOW runs (ADR-BACKTEST-015 P4b): a chart cell holds a live run through a lease.
   * `holdStrategyFollow` creates or joins the run (`{ follow_id, created, from_ms, lease_ms }`);
   * the run stops once no cell renews its lease. Values are unvalidated wire values.
   */
  holdStrategyFollow?(body: Record<string, unknown>, signal?: AbortSignal): Promise<unknown>;
  /**
   * Experiments (ADR-BACKTEST-015 P5b): one strategy run over several inputs, held by the backend.
   * Values are unvalidated wire values; the strategy data manager parses them.
   */
  createStrategyExperiment?(body: Record<string, unknown>, signal?: AbortSignal): Promise<unknown>;
  getStrategyExperiment?(experimentId: string, signal?: AbortSignal): Promise<unknown>;
  listStrategyExperiments?(limit: number, signal?: AbortSignal): Promise<unknown>;
  cancelStrategyExperiment?(experimentId: string, signal?: AbortSignal): Promise<unknown>;
  retryStrategyExperimentMember?(experimentId: string, ordinal: number, signal?: AbortSignal): Promise<unknown>;
  revealStrategyExperimentHoldout?(experimentId: string, signal?: AbortSignal): Promise<unknown>;
  /** The experiment's commit-driven stream; reports each experiment and resolves with the first one no member is active in. */
  watchStrategyExperiment?(experimentId: string, onExperiment: (value: StrategyExperiment) => void,
    signal?: AbortSignal): Promise<StrategyExperiment>;
  renewStrategyFollow?(followId: string, holder: string, signal?: AbortSignal): Promise<unknown>;
  releaseStrategyFollow?(followId: string, holder: string): Promise<void>;
  /** Content-addressed strategy versions and their names (ADR-BACKTEST-015 P3b); unvalidated wire values. */
  getStrategyVersion?(versionHash: string, signal?: AbortSignal): Promise<unknown>;
  getStrategyVersionDraft?(versionHash: string, signal?: AbortSignal): Promise<unknown>;
  strategyVersionNames?(signal?: AbortSignal): Promise<{ names: Array<{ name: string; version_hash: string; named_at_ms: number }> }>;
  nameStrategyVersion?(name: string, versionHash: string, signal?: AbortSignal): Promise<{ name: string; version_hash: string }>;
  unnameStrategyVersion?(name: string, signal?: AbortSignal): Promise<{ name: string; removed: boolean }>;
  /** Small references the strategy pages keep (ADR-BACKTEST-015 P3c); values are unvalidated JSON. */
  getStrategyReference?(kind: StrategyReferenceKind, key: string, signal?: AbortSignal): Promise<unknown>;
  listStrategyReferences?(kind: StrategyReferenceKind, prefix: string, signal?: AbortSignal): Promise<Array<{ key: string; value: unknown; updated_at_ms: number }>>;
  putStrategyReference?(kind: StrategyReferenceKind, key: string, value: unknown, signal?: AbortSignal): Promise<void>;
  removeStrategyReference?(kind: StrategyReferenceKind, key: string, signal?: AbortSignal): Promise<void>;
  importStrategyReferences?(kind: StrategyReferenceKind, entries: Array<{ key: string; value: unknown }>, signal?: AbortSignal): Promise<{ imported: string[]; kept: string[] }>;
  getResultReplay?(cursor: BacktestResultReplayCursor, signal?: AbortSignal): Promise<BacktestResultReplayFrame>;
  saveResultReplayNote?(cursor: BacktestResultReplayCursor, note: BacktestResultReplayNoteDraft,
    signal?: AbortSignal): Promise<{ revision: number }>;
  exportRun(runId: string, signal?: AbortSignal): Promise<Record<string, unknown>>;
  cancelRun(runId: string, signal?: AbortSignal): Promise<BacktestRunRecord>;
  resumeRun(runId: string, signal?: AbortSignal): Promise<BacktestRunRecord>;
  listStudies(signal?: AbortSignal): Promise<BacktestStudyRecord[]>;
  getStudy(studyId: string, signal?: AbortSignal): Promise<BacktestStudyRecord>;
  createStudy(body: Record<string, unknown>, signal?: AbortSignal): Promise<BacktestStudyRecord>;
  startStudy(studyId: string, signal?: AbortSignal): Promise<BacktestStudyRecord>;
  cancelStudy(studyId: string, signal?: AbortSignal): Promise<BacktestStudyRecord>;
  revealStudyHoldout(studyId: string, signal?: AbortSignal): Promise<BacktestStudyRecord>;
  compareStudy(studyId: string, signal?: AbortSignal): Promise<BacktestStudyComparison>;
  createStrategyRevision(body: Record<string, unknown>, signal?: AbortSignal): Promise<StrategyRevisionRecord>;
  smokeStrategyRevision(revisionId: string, body: Record<string, unknown>, signal?: AbortSignal): Promise<Record<string, unknown>>;
  getSignalTrace(runId: string, after?: number, limit?: number, signal?: AbortSignal): Promise<SignalTracePage>;
  compareRuns(leftRunId: string, rightRunId: string, signal?: AbortSignal): Promise<RunCompareV3>;
  compareRecentRun(runId: string, signal?: AbortSignal): Promise<RecentRunCompareV1>;
  cloneRun(runId: string, parameter: string, value: unknown, idempotencyKey: string, signal?: AbortSignal): Promise<BacktestRunRecord>;
  copyStrategyRevision(revisionId: string, name: string, signal?: AbortSignal): Promise<StrategyRevisionRecord>;
  archiveStrategyRevision(revisionId: string, signal?: AbortSignal): Promise<StrategyRevisionRecord>;
  createReviewBridge(runId: string, startTimeMs: number, endTimeMs: number, signal?: AbortSignal): Promise<Record<string, unknown>>;
  /** A new run of the same strategy and input with changed settings (ADR-BACKTEST-015 P5c). */
  deriveRun?(runId: string, overrides: Record<string, unknown>, idempotencyKey: string, signal?: AbortSignal): Promise<BacktestRunRecord>;
  getReviewBridge(bridgeId: string, signal?: AbortSignal): Promise<Record<string, unknown>>;
  revealReviewBridge(bridgeId: string, signal?: AbortSignal): Promise<Record<string, unknown>>;
  inspectPythonBundle(zipBase64: string, signal?: AbortSignal): Promise<Record<string, unknown>>;
  createPythonBundle(zipBase64: string, signal?: AbortSignal): Promise<Record<string, unknown>>;
  getPythonBundle(bundleId: string, signal?: AbortSignal): Promise<Record<string, unknown>>;
  createPythonRevision(bundleId: string, signal?: AbortSignal): Promise<StrategyRevisionRecord>;
  getPythonRuntimeReceipt(revisionId: string, signal?: AbortSignal): Promise<Record<string, unknown>>;
  createResearchLaunchContext(
    body: BacktestResearchLaunchContextInput,
    signal?: AbortSignal,
  ): Promise<BacktestResearchLaunchContext>;
  getResearchLaunchContext(
    contextId: string,
    signal?: AbortSignal,
  ): Promise<BacktestResearchLaunchContext>;
}

export interface BacktestDataset {
  dataset_id: string;
  data_epoch: string;
  name: string;
  symbol: string;
  interval: string;
  rows: number;
  first_open_ms: number | null;
  last_close_ms: number | null;
  strategy_revisions: string[];
  source?: string;
  checksum?: string;
  coverage?: Record<string, unknown>;
  gap?: Record<string, unknown>;
  revision?: string;
  contract_history?: {
    bundle_hash: string;
    roles: string[];
  };
}

export interface SnapshotPreviewRequest {
  execution_data?: unknown;
  dataset_id: string;
  data_epoch: string;
  start_time_ms: number;
  end_time_ms: number;
  interval?: string;
  fidelity_mode?: string;
  exchange?: string;
  market_type?: string;
  contract_data_mode?: string;
  account_model?: string;
  funding_mode?: string;
}

export interface BacktestSnapshot {
  data_epoch: string;
  snapshot_hash: string;
  coverage_start_ms: number;
  coverage_end_ms: number;
  row_count: number;
  market_row_count?: number;
  quality: Record<string, unknown>;
  role_hashes?: Record<string, string>;
  fidelity_capabilities: string[];
  catalog_dataset_id?: string;
  identity?: Record<string, unknown>;
}

/** What the strategy pages keep in the backend instead of browser storage (ADR-BACKTEST-015 P3c). */
export type StrategyReferenceKind = "continuous-run" | "research-handoff" | "research-return";

export class BacktestApiError extends Error {
  constructor(
    readonly code: string,
    readonly apiMessage: string,
    readonly details: Record<string, unknown>,
    readonly status: number,
  ) {
    super(`${code}: ${apiMessage}`);
    this.name = "BacktestApiError";
  }
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      error?: { code?: string; message?: string; details?: Record<string, unknown> };
    } | null;
    const detail = payload?.error;
    if (detail?.code && detail.message) {
      throw new BacktestApiError(
        detail.code,
        detail.message,
        detail.details ?? {},
        response.status,
      );
    }
    throw new BacktestApiError(
      "BACKTEST_API_UNAVAILABLE",
      `HTTP ${response.status}`,
      {},
      response.status,
    );
  }
  return (await response.json()) as T;
}

function requestOptions(options: RequestInit, signal?: AbortSignal): RequestInit {
  return signal === undefined ? options : { ...options, signal };
}

/** The run facade is served beside `/backtests` (ADR-BACKTEST-015 P2). */
function strategyRunsBase(base: string) {
  return base.endsWith("/backtests") ? `${base.slice(0, -"/backtests".length)}/strategy-runs` : `${API_BASE}/strategy-runs`;
}

export function createBacktestApi(base = `${API_BASE}/backtests`, runsBase = strategyRunsBase(base)): BacktestApiClient {
  // Versions are served beside the run facade.
  const sibling = (name: string) => runsBase.endsWith("/strategy-runs")
    ? `${runsBase.slice(0, -"/strategy-runs".length)}/${name}` : `${API_BASE}/${name}`;
  const versionsBase = sibling("strategy-versions");
  const referencesBase = sibling("strategy-references");
  const followsBase = sibling("strategy-follows");
  const experimentsBase = sibling("strategy-experiments");
  return {
    externalProviders: {
      async trace(runId, after = 0, signal) {
        return readJson(await fetch(`${base}/provider-connections/runs/${encodeURIComponent(runId)}/trace?after=${after}&limit=200`, requestOptions({}, signal)));
      },
      async example(signal) {
        return readJson(await fetch(`${base}/provider-connections/example`, requestOptions({}, signal)));
      },
      async list(signal) {
        const payload = await readJson<{ connections: ExternalProviderConnection[] }>(
          await fetch(`${base}/provider-connections`, requestOptions({}, signal)),
        );
        return payload.connections;
      },
      async create(body, signal) {
        return readJson(await fetch(`${base}/provider-connections`, requestOptions({
          method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
        }, signal)));
      },
      async revoke(connectionId, signal) {
        return readJson(await fetch(`${base}/provider-connections/${encodeURIComponent(connectionId)}/revoke`, requestOptions({ method: "POST" }, signal)));
      },
      async smoke(connectionId, body, signal) {
        return readJson(await fetch(`${base}/provider-connections/${encodeURIComponent(connectionId)}/smoke`, requestOptions({
          method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
        }, signal)));
      },
    },
    async capabilities(signal) {
      return readJson(await fetch(`${base}/capabilities`, requestOptions({}, signal)));
    },
    async listDatasets(signal) {
      const payload = await readJson<{ datasets: BacktestDataset[] }>(
        await fetch(`${base}/datasets`, requestOptions({}, signal)),
      );
      return payload.datasets;
    },
    async previewSnapshot(body, signal) {
      return readJson(
        await fetch(`${base}/datasets/snapshot`, requestOptions({
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
        }, signal)),
      );
    },
    async resolveChartContext(body, signal) {
      return readJson(
        await fetch(`${base}/chart-context/resolve`, requestOptions({
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
        }, signal)),
      );
    },
    async materializeChartContext(body, signal) {
      return readJson(
        await fetch(`${base}/chart-context/materialize`, requestOptions({
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
        }, signal)),
      );
    },
    async prepareChartContext(body, signal, strategy, idempotencyKey = crypto.randomUUID(), onProgress = () => undefined) {
      const transport = { basePath: base.replace(/\/backtests$/, "/data-preparations") };
      const initial = await preparationRequest<PreparationJob>("/strategy", {
        method: "POST", headers: { "content-type": "application/json" }, signal: signal ?? null,
        body: JSON.stringify({ idempotency_key: idempotencyKey, context: body, ...(strategy ? { strategy } : {}) }),
      }, transport);
      const ready = await waitForPreparation(initial, onProgress, signal, transport);
      if (!ready.result?.resolution) throw new Error("Prepared strategy context is missing");
      if (ready.result.strategy_run) return { ...ready.result.resolution, prepared_run: ready.result.strategy_run };
      return readJson(await fetch(`${base}/chart-context/resolve`, requestOptions({
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify(ready.result.resolution.request),
      }, signal)));
    },
    async observeStrategyPreparation(jobId, scope, retry, onProgress, signal) {
      const transport = { basePath: base.replace(/\/backtests$/, "/data-preparations") };
      const path = `/${encodeURIComponent(jobId)}`;
      const verify = (job: PreparationJob) => {
        const intent = job.request.intent.strategy as { chart_cell_scope?: unknown } | undefined;
        if (job.id !== jobId || job.request.consumer !== "STRATEGY" || intent?.chart_cell_scope !== scope) {
          throw new Error("STRATEGY_PREPARATION_IDENTITY_MISMATCH");
        }
      };
      let job = await preparationRequest<PreparationJob>(path, { signal: signal ?? null }, transport);
      verify(job);
      if (retry && (job.state === "BLOCKED_STORAGE" || (job.state === "FAILED" && job.error?.retryable))
        && !job.cancel_requested) {
        job = await preparationRequest<PreparationJob>(path + "/retry", { method: "POST", signal: signal ?? null }, transport);
      }
      return waitForPreparation(job, async update => {
        verify(update);
        await onProgress(update);
      }, signal, transport);
    },
    async listRuns(signal) {
      const payload = await readJson<{ runs: BacktestRunRecord[] }>(
        await fetch(`${base}/runs`, requestOptions({}, signal)),
      );
      return payload.runs;
    },
    async listStrategyRevisions(signal) {
      const payload = await readJson<{ items: StrategyRevisionRecord[] }>(
        await fetch(`${base}/strategy-revisions`, requestOptions({}, signal)),
      );
      return payload.items;
    },
    async validate(body, signal) {
      return readJson(
        await fetch(`${base}/runs/validate`, requestOptions({
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
        }, signal)),
      );
    },
    async createRun(body, idempotencyKey, signal) {
      return readJson(
        await fetch(`${base}/runs`, requestOptions({
          method: "POST",
          headers: {
            "content-type": "application/json",
            "Idempotency-Key": idempotencyKey,
          },
          body: JSON.stringify(body),
        }, signal)),
      );
    },
    async streamRun(runId, signal, onUpdate) {
      const response = await fetch(`${base}/runs/${encodeURIComponent(runId)}/events`, requestOptions({
        headers: { Accept: "application/x-ndjson" },
      }, signal));
      if (!response.ok) await readJson(response);
      if (!response.body || !response.headers.get("content-type")?.startsWith("application/x-ndjson")) {
        throw new StrategyRunStreamError("STRATEGY_STREAM_UNAVAILABLE", "The backend did not return a strategy result stream");
      }
      return readStrategyRunStream({ body: response.body, runId, ...(signal ? { signal } : {}), ...(onUpdate ? { onUpdate } : {}) });
    },
    async getRun(runId, signal) {
      return readJson(await fetch(
        `${base}/runs/${encodeURIComponent(runId)}`,
        requestOptions({}, signal),
      ));
    },
    async getSelectedVersion(runId, signal) {
      return readJson(await fetch(`${base}/runs/${encodeURIComponent(runId)}/strategy-version`, requestOptions({}, signal)));
    },
    async getReport(runId, signal) {
      return readJson(
        await fetch(
          `${base}/runs/${encodeURIComponent(runId)}/report`,
          requestOptions({}, signal),
        ),
      );
    },
    async getChart(runId, signal) {
      return readJson(
        await fetch(
          `${base}/runs/${encodeURIComponent(runId)}/chart`,
          requestOptions({}, signal),
        ),
      );
    },
    async getStrategyRun(runId, signal) {
      return readJson(await fetch(`${runsBase}/${encodeURIComponent(runId)}`, requestOptions({}, signal)));
    },
    async getStrategyRunResult(runId, signal) {
      return readJson(await fetch(`${runsBase}/${encodeURIComponent(runId)}/result`, requestOptions({}, signal)));
    },
    async watchStrategyRun(runId, signal, onStatus) {
      const response = await fetch(`${runsBase}/${encodeURIComponent(runId)}/events`, requestOptions({
        headers: { Accept: "application/x-ndjson" },
      }, signal));
      if (!response.ok) await readJson(response);
      if (!response.body || !response.headers.get("content-type")?.startsWith("application/x-ndjson")) {
        throw new StrategyRunStreamError("STRATEGY_STREAM_UNAVAILABLE", "The backend did not return a run status stream");
      }
      return readStrategyRunStatusStream({ body: response.body, runId, ...(signal ? { signal } : {}), ...(onStatus ? { onStatus } : {}) });
    },
    async cancelStrategyRun(runId, signal) {
      return readJson(await fetch(`${runsBase}/${encodeURIComponent(runId)}/cancel`, requestOptions({ method: "POST" }, signal)));
    },
    async getStrategyVersion(versionHash, signal) {
      return readJson(await fetch(`${versionsBase}/${encodeURIComponent(versionHash)}`, requestOptions({}, signal)));
    },
    async getStrategyVersionDraft(versionHash, signal) {
      return readJson(await fetch(`${versionsBase}/${encodeURIComponent(versionHash)}/draft`, requestOptions({}, signal)));
    },
    async strategyVersionNames(signal) {
      return readJson(await fetch(`${versionsBase}/names`, requestOptions({}, signal)));
    },
    async nameStrategyVersion(name, versionHash, signal) {
      return readJson(await fetch(`${versionsBase}/names/${encodeURIComponent(name)}`, requestOptions({
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version_hash: versionHash }),
      }, signal)));
    },
    async unnameStrategyVersion(name, signal) {
      return readJson(await fetch(`${versionsBase}/names/${encodeURIComponent(name)}`, requestOptions({ method: "DELETE" }, signal)));
    },
    async getStrategyReference(kind, key, signal) {
      const response = await fetch(`${referencesBase}/${kind}/entry?key=${encodeURIComponent(key)}`, requestOptions({}, signal));
      if (response.status === 404) return null;
      return (await readJson<{ value: unknown }>(response)).value;
    },
    async listStrategyReferences(kind, prefix, signal) {
      return (await readJson<{ entries: Array<{ key: string; value: unknown; updated_at_ms: number }> }>(await fetch(
        `${referencesBase}/${kind}?prefix=${encodeURIComponent(prefix)}&limit=512`, requestOptions({}, signal)))).entries;
    },
    async putStrategyReference(kind, key, value, signal) {
      await readJson(await fetch(`${referencesBase}/${kind}/entry`, requestOptions({
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key, value }),
      }, signal)));
    },
    async removeStrategyReference(kind, key, signal) {
      await readJson(await fetch(`${referencesBase}/${kind}/entry?key=${encodeURIComponent(key)}`, requestOptions({ method: "DELETE" }, signal)));
    },
    async importStrategyReferences(kind, entries, signal) {
      return readJson(await fetch(`${referencesBase}/${kind}/import`, requestOptions({
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ entries }),
      }, signal)));
    },
    async strategyRunCapabilities(signal) {
      return readJson(await fetch(`${runsBase}/capabilities`, requestOptions({}, signal)));
    },
    async createStrategyExperiment(body, signal) {
      return readJson(await fetch(experimentsBase, requestOptions({
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      }, signal)));
    },
    async getStrategyExperiment(experimentId, signal) {
      return readJson(await fetch(`${experimentsBase}/${encodeURIComponent(experimentId)}`, requestOptions({}, signal)));
    },
    async listStrategyExperiments(limit, signal) {
      return readJson(await fetch(`${experimentsBase}?limit=${limit}`, requestOptions({}, signal)));
    },
    async cancelStrategyExperiment(experimentId, signal) {
      return readJson(await fetch(`${experimentsBase}/${encodeURIComponent(experimentId)}/cancel`, requestOptions({ method: "POST" }, signal)));
    },
    async retryStrategyExperimentMember(experimentId, ordinal, signal) {
      return readJson(await fetch(`${experimentsBase}/${encodeURIComponent(experimentId)}/members/${ordinal}/retry`,
        requestOptions({ method: "POST" }, signal)));
    },
    async revealStrategyExperimentHoldout(experimentId, signal) {
      return readJson(await fetch(`${experimentsBase}/${encodeURIComponent(experimentId)}/reveal-holdout`,
        requestOptions({ method: "POST" }, signal)));
    },
    async watchStrategyExperiment(experimentId, onExperiment, signal) {
      const response = await fetch(`${experimentsBase}/${encodeURIComponent(experimentId)}/events`, requestOptions({
        headers: { Accept: "application/x-ndjson" },
      }, signal));
      if (!response.ok) await readJson(response);
      if (!response.body || !response.headers.get("content-type")?.startsWith("application/x-ndjson")) {
        throw new StrategyRunStreamError("STRATEGY_STREAM_UNAVAILABLE", "The backend did not return an experiment stream");
      }
      return readNdjsonUntilTerminal<StrategyExperiment>({
        body: response.body, ...(signal ? { signal } : {}),
        parse(line) {
          const frame = parseStrategyExperimentFrame(JSON.parse(line));
          if (frame === null) return null;
          if ("error" in frame) throw new StrategyRunStreamError(frame.error.code, frame.error.message);
          onExperiment(frame.experiment);
          return frame.experiment.terminal ? frame.experiment : null;
        },
      });
    },
    async holdStrategyFollow(body, signal) {
      return readJson(await fetch(followsBase, requestOptions({
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      }, signal)));
    },
    async renewStrategyFollow(followId, holder, signal) {
      return readJson(await fetch(`${followsBase}/${encodeURIComponent(followId)}/lease`, requestOptions({
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ holder }),
      }, signal)));
    },
    async releaseStrategyFollow(followId, holder) {
      // keepalive: a cell closing with the page still lets its run go.
      await readJson(await fetch(`${followsBase}/${encodeURIComponent(followId)}/lease?holder=${encodeURIComponent(holder)}`,
        { method: "DELETE", keepalive: true }));
    },
    async getResultReplay(cursor, signal) {
      const query = new URLSearchParams({
        snapshot_hash: cursor.snapshotHash, report_hash: cursor.reportHash,
        cursor: String(cursor.cursor), interval: cursor.interval,
        ...(cursor.comparisonInterval ? { comparison_interval: cursor.comparisonInterval } : {}),
        ...(cursor.comparisonDataset ? {
          comparison_dataset_id: cursor.comparisonDataset.datasetId,
          comparison_data_epoch: cursor.comparisonDataset.dataEpoch,
        } : {}),
        ...(cursor.maPeriod !== undefined ? { ma_period: String(cursor.maPeriod) } : {}),
        ...(cursor.comparisonMaPeriod !== undefined ? { comparison_ma_period: String(cursor.comparisonMaPeriod) } : {}),
      });
      if (cursor.additionalCharts && Object.keys(cursor.additionalCharts).length)
        query.set("additional_charts", JSON.stringify(cursor.additionalCharts));
      return readJson(await fetch(
        `${base}/runs/${encodeURIComponent(cursor.runId)}/result-replay?${query}`,
        requestOptions({}, signal),
      ));
    },
    async saveResultReplayNote(cursor, note, signal) {
      return readJson(await fetch(
        `${base}/runs/${encodeURIComponent(cursor.runId)}/result-replay/notes`,
        requestOptions({
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            snapshot_hash: cursor.snapshotHash, report_hash: cursor.reportHash,
            cursor: cursor.cursor, interval: cursor.interval,
            note_id: note.id, expected_revision: note.expectedRevision, body: note.body,
          }),
        }, signal),
      ));
    },
    async exportRun(runId, signal) {
      return readJson(
        await fetch(
          `${base}/runs/${encodeURIComponent(runId)}/export`,
          requestOptions({}, signal),
        ),
      );
    },
    async cancelRun(runId, signal) {
      return readJson(
        await fetch(
          `${base}/runs/${encodeURIComponent(runId)}/cancel`,
          requestOptions({ method: "POST" }, signal),
        ),
      );
    },
    async resumeRun(runId, signal) {
      return readJson(
        await fetch(
          `${base}/runs/${encodeURIComponent(runId)}/resume`,
          requestOptions({ method: "POST" }, signal),
        ),
      );
    },
    async listStudies(signal) {
      const payload = await readJson<{ studies: BacktestStudyRecord[] }>(
        await fetch(`${base}/studies`, requestOptions({}, signal)),
      );
      return payload.studies;
    },
    async getStudy(studyId, signal) {
      return readJson(await fetch(
        `${base}/studies/${encodeURIComponent(studyId)}`,
        requestOptions({}, signal),
      ));
    },
    async createStudy(body, signal) {
      return readJson(
        await fetch(`${base}/studies`, requestOptions({
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
        }, signal)),
      );
    },
    async startStudy(studyId, signal) {
      return readJson(
        await fetch(
          `${base}/studies/${encodeURIComponent(studyId)}/start`,
          requestOptions({ method: "POST" }, signal),
        ),
      );
    },
    async cancelStudy(studyId, signal) {
      return readJson(
        await fetch(
          `${base}/studies/${encodeURIComponent(studyId)}/cancel`,
          requestOptions({ method: "POST" }, signal),
        ),
      );
    },
    async revealStudyHoldout(studyId, signal) {
      return readJson(
        await fetch(
          `${base}/studies/${encodeURIComponent(studyId)}/reveal-holdout`,
          requestOptions({ method: "POST" }, signal),
        ),
      );
    },
    async compareStudy(studyId, signal) {
      return readJson(
        await fetch(
          `${base}/studies/${encodeURIComponent(studyId)}/compare`,
          requestOptions({}, signal),
        ),
      );
    },
    async createStrategyRevision(body, signal) {
      return readJson(await fetch(`${base}/strategy-revisions`, requestOptions({
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
      }, signal)));
    },
    async smokeStrategyRevision(revisionId, body, signal) {
      return readJson(await fetch(`${base}/strategy-revisions/${encodeURIComponent(revisionId)}/smoke`, requestOptions({
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
      }, signal)));
    },
    async getSignalTrace(runId, after = 0, limit = 200, signal) {
      return readJson(await fetch(`${base}/runs/${encodeURIComponent(runId)}/signal-trace?after=${after}&limit=${limit}`, requestOptions({}, signal)));
    },
    async compareRuns(leftRunId, rightRunId, signal) {
      const query = new URLSearchParams({ left_run_id: leftRunId, right_run_id: rightRunId });
      return readJson(await fetch(`${base}/runs/compare/pair?${query}`, requestOptions({}, signal)));
    },
    async compareRecentRun(runId, signal) {
      return readJson(await fetch(
        `${base}/runs/${encodeURIComponent(runId)}/comparison`,
        requestOptions({}, signal),
      ));
    },
    async deriveRun(runId, overrides, idempotencyKey, signal) {
      return readJson(await fetch(`${base}/runs/${encodeURIComponent(runId)}/derive`, requestOptions({
        method: "POST", headers: { "content-type": "application/json", "Idempotency-Key": idempotencyKey },
        body: JSON.stringify({ overrides }),
      }, signal)));
    },
    async cloneRun(runId, parameter, value, idempotencyKey, signal) {
      return readJson(await fetch(`${base}/runs/${encodeURIComponent(runId)}/clone`, requestOptions({
        method: "POST", headers: { "content-type": "application/json", "Idempotency-Key": idempotencyKey },
        body: JSON.stringify({ parameter, value }),
      }, signal)));
    },
    async copyStrategyRevision(revisionId, name, signal) {
      return readJson(await fetch(`${base}/strategy-revisions/${encodeURIComponent(revisionId)}/copy`, requestOptions({
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name }),
      }, signal)));
    },
    async archiveStrategyRevision(revisionId, signal) {
      return readJson(await fetch(`${base}/strategy-revisions/${encodeURIComponent(revisionId)}/archive`, requestOptions({ method: "POST" }, signal)));
    },
    async createReviewBridge(runId, startTimeMs, endTimeMs, signal) {
      return readJson(await fetch(`${base}/runs/${encodeURIComponent(runId)}/review-bridge`, requestOptions({
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ start_time_ms: startTimeMs, end_time_ms: endTimeMs }),
      }, signal)));
    },
    async getReviewBridge(bridgeId, signal) {
      return readJson(await fetch(`${base}/review-bridges/${encodeURIComponent(bridgeId)}`, requestOptions({}, signal)));
    },
    async revealReviewBridge(bridgeId, signal) {
      return readJson(await fetch(`${base}/review-bridges/${encodeURIComponent(bridgeId)}/reveal`, requestOptions({ method: "POST" }, signal)));
    },
    async inspectPythonBundle(zipBase64, signal) {
      return readJson(await fetch(`${base}/strategy-bundles/inspect`, requestOptions({
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ zip_base64: zipBase64 }),
      }, signal)));
    },
    async createPythonBundle(zipBase64, signal) {
      return readJson(await fetch(`${base}/strategy-bundles`, requestOptions({
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ zip_base64: zipBase64 }),
      }, signal)));
    },
    async getPythonBundle(bundleId, signal) {
      return readJson(await fetch(`${base}/strategy-bundles/${encodeURIComponent(bundleId)}`, requestOptions({}, signal)));
    },
    async createPythonRevision(bundleId, signal) {
      return readJson(await fetch(`${base}/strategy-revisions/python`, requestOptions({
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ bundle_id: bundleId }),
      }, signal)));
    },
    async getPythonRuntimeReceipt(revisionId, signal) {
      return readJson(await fetch(
        `${base}/strategy-revisions/${encodeURIComponent(revisionId)}/runtime-receipt`,
        requestOptions({}, signal),
      ));
    },
    async createResearchLaunchContext(body, signal) {
      return readJson(await fetch(`${base}/research/contexts`, requestOptions({
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      }, signal)));
    },
    async getResearchLaunchContext(contextId, signal) {
      return readJson(await fetch(
        `${base}/research/contexts/${encodeURIComponent(contextId)}`,
        requestOptions({}, signal),
      ));
    },
  };
}

const configuredBacktestApiBase = String(
  import.meta.env?.VITE_BACKTEST_API_BASE ?? "",
).trim().replace(/\/$/, "");

export const defaultBacktestApi = createBacktestApi(
  configuredBacktestApiBase || `${API_BASE}/backtests`,
);
