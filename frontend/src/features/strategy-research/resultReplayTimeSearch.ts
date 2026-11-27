/**
 * Go to date for strategy-result replay (PL-6). The replay's cursor counts
 * frozen input events; the backend projects a frame per cursor and reports
 * the time of the last revealed event. There is no time → cursor lookup, so
 * the cursor is found through the engine's own frames: the largest cursor
 * whose revealed time is at or before the target. Event times never go
 * down, so a search over cursors is valid. Interpolation lands in a few
 * probes on regular bar inputs; every other probe bisects, so gaps and
 * clusters still finish in O(log n).
 */
export interface ResultReplayCursorMatch {
  readonly cursor: number;
  /** Time the replay reveals at that cursor, epoch ms. */
  readonly timeMs: number;
  /** False when the target lies before the first event or after the last bar it can reach. */
  readonly exact: boolean;
  readonly probes: number;
}

export const RESULT_REPLAY_SEARCH_PROBES = 48;

export async function findResultReplayCursor(
  targetMs: number,
  total: number,
  timeAt: (cursor: number) => Promise<number | null>,
  { toleranceMs = 0, maxProbes = RESULT_REPLAY_SEARCH_PROBES }: { toleranceMs?: number; maxProbes?: number } = {},
): Promise<ResultReplayCursorMatch | null> {
  if (!Number.isSafeInteger(total) || total < 1 || !Number.isFinite(targetMs)) return null;
  let probes = 0;
  const probe = async (cursor: number): Promise<number> => {
    if (probes >= maxProbes) throw new Error("Result replay date search did not converge");
    probes += 1;
    const time = await timeAt(cursor);
    if (time === null || !Number.isFinite(time)) throw new Error("Result replay frame has no time");
    return time;
  };
  const match = (cursor: number, timeMs: number, before = false): ResultReplayCursorMatch => ({
    cursor, timeMs, probes, exact: !before && targetMs - timeMs <= toleranceMs,
  });

  let lo = 1;
  let loTime = await probe(lo);
  // Before the first event: the nearest bar is the first one.
  if (targetMs < loTime) return match(lo, loTime, true);
  let hi = total;
  let hiTime = lo === hi ? loTime : await probe(hi);
  if (targetMs >= hiTime) return match(hi, hiTime);
  // Invariant: time(lo) <= target < time(hi).
  let bisect = false;
  while (hi - lo > 1) {
    let guess: number;
    if (bisect || hiTime <= loTime) {
      guess = lo + Math.floor((hi - lo) / 2);
    } else {
      const ratio = (targetMs - loTime) / (hiTime - loTime);
      guess = Math.min(hi - 1, Math.max(lo + 1, lo + Math.floor(ratio * (hi - lo))));
    }
    const span = hi - lo;
    const time = await probe(guess);
    if (time <= targetMs) { lo = guess; loTime = time; } else { hi = guess; hiTime = time; }
    // Interpolation that failed to halve the span is followed by a bisection.
    bisect = !bisect && (hi - lo) * 2 > span;
  }
  return match(lo, loTime);
}
