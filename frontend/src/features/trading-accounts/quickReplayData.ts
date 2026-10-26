import { fetchKlinesRange } from "../../services/api.js";
import type { ReplayBar } from "./quickReplayModel.js";

const MAX_PAGES = 6;

/**
 * Load a bounded candle window once. Pages walk backwards from the end because
 * the range endpoint truncates to the newest rows first.
 */
export async function loadReplayBars(
  input: { exchange: string; marketType: string; symbol: string; interval: string },
  startSec: number,
  endSec: number,
  signal?: AbortSignal,
): Promise<{ bars: ReplayBar[]; truncated: boolean }> {
  const byTime = new Map<number, ReplayBar>();
  let pageEnd = endSec;
  let truncated = false;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const response = await fetchKlinesRange(
      input.symbol,
      input.interval,
      startSec,
      pageEnd,
      input.marketType,
      input.exchange,
      { repair: "wait", waitMs: 4_000, strict: false, ...(signal ? { signal } : {}) },
    );
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
