import { API_BASE } from "../../services/apiConfig.js";
import type { TrainingRunCreatePayload, TrainingRunMutationResponse } from "../replay/replayV2Types.js";
import type { ChartContextResolution } from "../backtest/backtestApi.js";
import type { BacktestRunRecord } from "../backtest/backtestTypes.js";
import type { NativeRun } from "../backtest/native/nativeBacktestApi.js";

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
    const message = typeof detail === "object" && detail !== null && "message" in detail && typeof detail.message === "string"
      ? detail.message : `Data preparation failed (${response.status})`;
    throw new Error(message);
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
      throw new Error(job.error?.message ?? job.state);
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
  market: { exchange: string; market_type: string; symbol: string; display_interval?: string; progressive?: boolean },
  onProgress: (job: PreparationJob) => void,
  signal?: AbortSignal,
  idempotencyKey: string = crypto.randomUUID(),
  transport: PreparationTransport = {},
): Promise<TrainingRunMutationResponse> {
  const initial = await preparationRequest<PreparationJob>("/replay", {
    method: "POST", headers: { "Content-Type": "application/json" }, signal: signal ?? null,
    body: JSON.stringify({ idempotency_key: idempotencyKey, setup, ...market }),
  }, transport);
  const ready = await waitForPreparation(initial, onProgress, signal, transport, market.progressive === true);
  if (!ready.result?.run) throw new Error("Prepared training is missing its run");
  return { protocol: "replay.v3", created: true, run: ready.result.run };
}
