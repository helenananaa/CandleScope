import { validateKlineDomain } from "../../utils/klineDomainPolicy.js";
import type { KlineApi } from "../market-data/klineContracts.js";
import type { MarketDataManager } from "../market-data/manager/marketDataManager.js";
import { toEpochSeconds } from "../market-data/marketDataTypes.js";
import { hasFinalityEvidence } from "../market-data/quality/klineQualityPolicy.js";
import type { ReplayBar } from "./quickReplayModel.js";

const MAX_PAGES = 6;
const MAX_ATTEMPTS = 6;

export class ReplayHistoryPendingError extends Error {
  constructor() { super("Replay history is still being prepared"); }
}

function waitForRetry(ms: number, signal?: AbortSignal): Promise<void> {
  signal?.throwIfAborted();
  return new Promise((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      reject(signal?.reason instanceof Error ? signal.reason : new DOMException("Replay cancelled", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", abort, { once: true });
  });
}

interface ReplayHistoryReader {
  fetchRange: KlineApi["fetchKlinesRange"];
  wait(ms: number, signal?: AbortSignal): Promise<void>;
}

/** The replay owns only its request observer and detached candle copies. The
 * workspace manager retains ownership of shared cache and live transports. */
export function createManagedReplayHistoryReader(
  manager: Pick<MarketDataManager, "read" | "fetchKlinesRange"> | null,
): ReplayHistoryReader {
  return {
    wait: waitForRetry,
    fetchRange: async (symbol, interval, start, end, marketType, exchange, options) => {
      options.signal?.throwIfAborted();
      if (!manager) throw new Error("Replay market data manager is unavailable");
      const series = { symbol, interval, marketType, exchange };
      const cached = manager.read(series, { from: start, to: end }).complete;
      return manager.fetchKlinesRange(symbol, interval, start, end, marketType, exchange, {
        ...options,
        repair: cached ? "none" : "wait",
        strict: false,
        clientContext: { cacheMode: cached ? "prefer-cache" : "network-only" },
      });
    },
  };
}

/**
 * Wait for cold history repair before publishing a bounded candle window.
 * Pages walk backwards from the end because
 * the range endpoint truncates to the newest rows first.
 */
export async function loadReplayBars(
  input: { exchange: string; marketType: string; symbol: string; interval: string },
  startSec: number,
  endSec: number,
  signal: AbortSignal | undefined,
  dependencies: ReplayHistoryReader,
): Promise<{ bars: ReplayBar[]; truncated: boolean }> {
  const start = toEpochSeconds(startSec);
  const end = toEpochSeconds(endSec);
  if (start === null || end === null || !Number.isSafeInteger(start) || !Number.isSafeInteger(end)
    || start < 0 || start > end) throw new RangeError("Invalid replay history range");
  const byTime = new Map<number, ReplayBar>();
  let pageEnd = end;
  let truncated = false;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    let response;
    for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
      signal?.throwIfAborted();
      response = await dependencies.fetchRange(
        input.symbol,
        input.interval,
        start,
        pageEnd,
        input.marketType,
        input.exchange,
        { repair: "wait", waitMs: 4_000, strict: false, ...(signal ? { signal } : {}) },
      );
      signal?.throwIfAborted();
      const pending = response.history_state === "pending" || response.retryable === true
        || response.all_rows_final === false
        || ((response.data?.length ?? 0) > 0 && !hasFinalityEvidence(response))
        || (!response.truncated && response.complete === false && response.history_state !== "exhausted");
      if (!pending) break;
      if (attempt === MAX_ATTEMPTS - 1) throw new ReplayHistoryPendingError();
      const retryMs = typeof response.retry_at_ms === "number" ? response.retry_at_ms - Date.now() : 1_000;
      await dependencies.wait(Math.min(5_000, Math.max(1_000, retryMs)), signal);
    }
    if (!response) throw new ReplayHistoryPendingError();
    for (const row of response.data ?? []) {
      if (validateKlineDomain(row) || row.time < start || row.time > pageEnd) {
        throw new Error("Replay history contains an invalid candle");
      }
      byTime.set(row.time, {
        time: row.time,
        open: row.open!,
        high: row.high!,
        low: row.low!,
        close: row.close!,
        volume: row.volume!,
      });
    }
    const next = response.next_end_ms;
    if (!response.truncated) {
      truncated = false;
      break;
    }
    truncated = true;
    if (typeof next !== "number") break;
    const nextEnd = toEpochSeconds(Math.floor(next / 1000));
    if (nextEnd === null || nextEnd < start || nextEnd >= pageEnd) throw new ReplayHistoryPendingError();
    pageEnd = nextEnd;
  }
  const bars = [...byTime.values()].sort((left, right) => left.time - right.time);
  return { bars, truncated };
}
