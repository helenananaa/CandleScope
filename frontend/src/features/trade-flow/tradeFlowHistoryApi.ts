import { API_BASE } from "../../services/apiConfig.js";
import { preparationRequest, waitForPreparation } from "../data-preparation/api.js";
import type { PreparationJob } from "../data-preparation/api.js";
import type { TradeFlowIdentity } from "./tradeFlowTypes.js";

const MINUTE_MS = 60_000;
export const TRADE_HISTORY_MINUTES = 60;

export interface TradeHistoryMinute {
  bucket_start_ms: number;
  agg_trade_count: number;
  volume_delta_base: number;
  is_complete: boolean;
  is_final: boolean;
}

export interface TradeHistoryPage {
  data: TradeHistoryMinute[];
  complete: boolean;
  has_more: boolean;
}

interface TradeHistoryPreparation {
  status: "preparation" | "unavailable" | "local";
  job: PreparationJob | null;
}

export function supportsTradeHistoryArchive(identity: TradeFlowIdentity): boolean {
  return identity.exchange === "binance" && identity.marketType === "futures";
}

function scope(identity: TradeFlowIdentity, startMs: number) {
  return {
    exchange: identity.exchange, market_type: identity.marketType, symbol: identity.symbol,
    start_ms: startMs, end_ms: startMs + (TRADE_HISTORY_MINUTES - 1) * MINUTE_MS,
  };
}

export async function readTradeHistory(
  identity: TradeFlowIdentity, startMs: number, signal: AbortSignal,
): Promise<TradeHistoryPage> {
  const query = new URLSearchParams(Object.entries({
    ...scope(identity, startMs), limit: TRADE_HISTORY_MINUTES,
  }).map(([name, value]) => [name, String(value)]));
  const response = await fetch(`${API_BASE}/trade-flow/history?${query}`, { signal });
  if (!response.ok) throw new Error(`TradeFlow history read failed (${response.status})`);
  return await response.json() as TradeHistoryPage;
}

export async function fillTradeHistory(
  identity: TradeFlowIdentity,
  startMs: number,
  idempotencyKey: string,
  onProgress: (job: PreparationJob) => void,
  signal: AbortSignal,
): Promise<"unavailable" | "readback"> {
  const initial = await preparationRequest<TradeHistoryPreparation>("/trade-flow-history", {
    method: "POST", signal, headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...scope(identity, startMs), idempotency_key: idempotencyKey }),
  });
  if (initial.status === "unavailable") return "unavailable";
  let job = initial.job;
  if (job?.state === "FAILED" && job.error?.retryable && !job.cancel_requested) {
    job = await preparationRequest<PreparationJob>(`/${job.id}/retry`, { method: "POST", signal });
  }
  if (job) await waitForPreparation(job, onProgress, signal);
  return "readback";
}
