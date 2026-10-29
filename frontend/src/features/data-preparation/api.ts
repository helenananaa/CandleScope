import { API_BASE } from "../../services/apiConfig.js";
import type { TrainingRunCreatePayload, TrainingRunMutationResponse } from "../replay/replayV2Types.js";
import type { ChartContextResolution } from "../backtest/backtestApi.js";
import type { BacktestRunRecord } from "../backtest/backtestTypes.js";
import type { NativeRun } from "../backtest/native/nativeBacktestApi.js";
import { ReplayV2ApiClient, ReplayV2ApiError } from "../replay/replayV2Api.js";

export class PreparedReplayDeletedError extends Error {
  constructor() { super("Prepared training was deleted"); }
}

export class PreparationApiError extends Error {
  constructor(readonly code: string, message: string, readonly status: number) { super(message); }
}

export interface PreparationJob {
  id: string;
  state: "QUEUED" | "RUNNING" | "READY" | "FAILED" | "CANCELLED" | "BLOCKED_STORAGE";
  stage: string;
  completed: number;
  total: number;
  revision: number;
  cancel_requested: boolean;
  waiting?: { reason: "RATE_LIMIT"; retry_at_ms: number } | null;
  request: { consumer: string; progressive?: boolean; requirements: Array<{ symbol: string }>; intent: Record<string, unknown> };
  result: { run?: TrainingRunMutationResponse["run"]; strategy_run?: BacktestRunRecord; native_run?: NativeRun; inputs?: unknown[]; resolution?: ChartContextResolution } | null;
  error: { code: string; message: string; retryable: boolean } | null;
}

export interface PreparationCapabilities {
  enabled: boolean;
  progressive?: boolean;
  replay_sources: { BAR: boolean; AGG_TRADE: boolean };
  replay_account_modes?: Array<"APPROX_PROXY" | "HISTORICAL_EXACT">;
}

export interface PreparationTransport { fetcher?: typeof fetch; basePath?: string }

export async function preparationRequest<T>(path: string, options: RequestInit = {}, transport: PreparationTransport = {}): Promise<T> {
  const fetcher = transport.fetcher ?? globalThis.fetch;
  const response = await fetcher(`${transport.basePath ?? `${API_BASE}/data-preparations`}${path}`, options);
  const body: unknown = await response.json();
  if (!response.ok) {
    const detail = typeof body === "object" && body !== null && "detail" in body ? body.detail : null;
    const validationFailure = response.status === 422 && Array.isArray(detail);
    const message = typeof detail === "object" && detail !== null && "message" in detail && typeof detail.message === "string"
      ? detail.message : validationFailure ? "Data preparation request validation failed" : `Data preparation failed (${response.status})`;
    const code = typeof detail === "object" && detail !== null && "code" in detail && typeof detail.code === "string"
      ? detail.code : validationFailure ? "DATA_PREPARATION_INVALID_REQUEST" : "DATA_PREPARATION_ERROR";
    throw new PreparationApiError(code, message, response.status);
  }
  return body as T;
}

export async function waitForPreparation(
  initial: PreparationJob,
  onProgress: (job: PreparationJob) => void,
  signal?: AbortSignal,
  transport: PreparationTransport = {},
  acceptReplayPrefix = false,
): Promise<PreparationJob> {
  let job = initial;
  for (;;) {
    signal?.throwIfAborted();
    onProgress(job);
    if (job.state === "READY") return job;
    if (["FAILED", "CANCELLED", "BLOCKED_STORAGE"].includes(job.state)) {
      throw new PreparationApiError(job.error?.code ?? `DATA_PREPARATION_${job.state}`, job.error?.message ?? job.state, 200);
    }
    if (acceptReplayPrefix && job.state === "RUNNING" && job.request.progressive
      && job.result?.run?.adapter_session_id) return job;
    // Aborting an observer leaves the durable server job running.
    await new Promise<void>((resolve, reject) => {
      const abort = () => {
        clearTimeout(timer);
        const reason: unknown = signal?.reason;
        reject(reason instanceof Error ? reason : new DOMException("Observation stopped", "AbortError"));
      };
      const timer = setTimeout(() => { signal?.removeEventListener("abort", abort); resolve(); }, 750);
      signal?.addEventListener("abort", abort, { once: true });
      if (signal?.aborted) abort();
    });
    job = await preparationRequest<PreparationJob>(`/${job.id}`, { signal: signal ?? null }, transport);
  }
}

export async function prepareReplay(
  setup: TrainingRunCreatePayload,
  market: { exchange: string; market_type: string; symbol: string; display_interval?: string; progressive?: boolean; random_by_market?: boolean },
  onProgress: (job: PreparationJob) => void,
  signal?: AbortSignal,
  idempotencyKey: string = crypto.randomUUID(),
  transport: PreparationTransport = {},
): Promise<TrainingRunMutationResponse> {
  let initial = await preparationRequest<PreparationJob>("/replay", {
    method: "POST", headers: { "Content-Type": "application/json" }, signal: signal ?? null,
    body: JSON.stringify({ idempotency_key: idempotencyKey, setup, ...market }),
  }, transport);
  // A saved draft retains its submission key across restart. POST /replay
  // returns that durable job unchanged, including an old terminal failure.
  // This explicit submit may resume a retryable failure once; polling alone
  // must never restart jobs or create a second run with a new key.
  if (initial.state === "FAILED" && initial.error?.retryable && !initial.cancel_requested) {
    initial = await preparationRequest<PreparationJob>(`/${initial.id}/retry`, {
      method: "POST", signal: signal ?? null,
    }, transport);
  }
  const ready = await waitForPreparation(initial, onProgress, signal, transport, market.progressive === true);
  if (!ready.result?.run) throw new Error("Prepared training is missing its run");
  // READY is a historical preparation receipt. Its run can have been deleted
  // while a closed observer retained the submission key in the saved draft.
  const api = new ReplayV2ApiClient({
    ...(transport.fetcher ? { fetcher: transport.fetcher } : {}),
    ...(transport.basePath ? { basePath: transport.basePath.replace(/\/data-preparations\/?$/, "/replay") } : {}),
  });
  try {
    const current = await api.getRun(ready.result.run.run_id, signal);
    return { protocol: "replay.v3", created: true, run: current.run };
  } catch (error) {
    if (error instanceof ReplayV2ApiError && error.code === "TRAINING_RUN_NOT_FOUND") {
      throw new PreparedReplayDeletedError();
    }
    // Transport errors keep the original key: the outcome is still uncertain.
    throw error;
  }
}
