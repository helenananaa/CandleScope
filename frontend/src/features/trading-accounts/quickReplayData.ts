import { fetchKlinesRange } from "../../services/api.js";
import type { ReplayBar } from "./quickReplayModel.js";

const MAX_PAGES = 6;
const MAX_ATTEMPTS = 6;

export class ReplayHistoryPendingError extends Error {
  constructor() { super("Replay history is still being prepared"); }
}

function waitForRetry(ms: number, signal?: AbortSignal): Promise<void> {
  signal?.throwIfAborted();
  return new Promise((resolve, reject) => {
    const abort = () => { clearTimeout(timer); reject(signal?.reason); };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", abort, { once: true });
  });
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
  signal?: AbortSignal,
  dependencies = { fetchRange: fetchKlinesRange, wait: waitForRetry },
): Promise<{ bars: ReplayBar[]; truncated: boolean }> {
  const byTime = new Map<number, ReplayBar>();
  let pageEnd = endSec;
  let truncated = false;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    let response;
    for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
      signal?.throwIfAborted();
      response = await dependencies.fetchRange(
        input.symbol,
        input.interval,
        startSec,
        pageEnd,
        input.marketType,
        input.exchange,
        { repair: "wait", waitMs: 4_000, strict: false, ...(signal ? { signal } : {}) },
      );
      signal?.throwIfAborted();
      const pending = response.history_state === "pending" || response.retryable === true
        || response.all_rows_final === false
        || (!response.truncated && response.complete === false && response.history_state !== "exhausted");
      if (!pending) break;
      if (attempt === MAX_ATTEMPTS - 1) throw new ReplayHistoryPendingError();
      const retryMs = typeof response.retry_at_ms === "number" ? response.retry_at_ms - Date.now() : 1_000;
      await dependencies.wait(Math.min(5_000, Math.max(1_000, retryMs)), signal);
    }
    if (!response) throw new ReplayHistoryPendingError();
    for (const row of response.data) {
      byTime.set(row.time, {
        time: row.time,
        open: row.open,
        high: row.high,
        low: row.low,
        close: row.close,
        volume: row.volume,
      });
    }
    const next = response.next_end_ms;
    if (!response.truncated || typeof next !== "number" || next / 1000 <= startSec) {
      truncated = false;
      break;
    }
    pageEnd = Math.floor(next / 1000);
    truncated = true;
  }
  const bars = [...byTime.values()].sort((left, right) => left.time - right.time);
  return { bars, truncated };
}
