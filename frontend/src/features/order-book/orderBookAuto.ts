import type { OrderBookBook } from "./orderBookTypes.js";

export const PRICE_MULTIPLIERS = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000] as const;

/** Partial depth cannot know liquidity beyond its Top-N boundary. */
export function partialStepScores(book: OrderBookBook, targetRows: number, rangeBps = 0): Map<number, number> {
  const tick = book.priceTickSize;
  if (!tick) return new Map();
  const scores = new Map<number, number>();
  for (const multiplier of PRICE_MULTIPLIERS) {
    if (multiplier > 10) break;
    const step = tick * multiplier;
    let score = 0;
    for (const [levels, isBid] of [[book.bids, true], [book.asks, false]] as const) {
      const near = levels[0]?.[0];
      if (!near) continue;
      const prices = levels.filter(([price]) => Math.abs(price - near) <= near * (rangeBps || 10) / 10_000);
      if (!prices.length) continue;
      const buckets = new Set(prices.map(([price]) => (isBid ? Math.floor : Math.ceil)(Math.round(price / tick) / multiplier)));
      // Count complete buckets toward the target; a partial edge remains visible as a lower bound.
      const count = multiplier > 1 ? Math.max(1, buckets.size - 1) : buckets.size;
      const target = Math.min(Math.max(2, targetRows), prices.length);
      const error = Math.log(count / target);
      score += Math.abs(error) * (error < 0 ? 3 : 1);
      const span = Math.max(...buckets) - Math.min(...buckets) + 1;
      if (prices.length > targetRows) score += 0.15 * (1 - buckets.size / span);
    }
    scores.set(step, score);
  }
  return scores;
}

export class AutoGroupingState {
  private step: number | null = null;
  private pending: number | null = null;
  private pendingSince = 0;
  private changedAt = 0;

  reset(): void { this.step = this.pending = null; }

  choose(scores: Map<number, number>, now: number, frozen = false): number | null {
    const best = [...scores].sort(([a, sa], [b, sb]) => sa - sb || a - b)[0]?.[0];
    if (best === undefined) { this.reset(); return null; }
    if (this.step === null || !scores.has(this.step)) {
      this.step = best;
      this.changedAt = now;
      this.pending = null;
    } else if (frozen || best === this.step || scores.get(this.step)! - scores.get(best)! < 0.25) {
      this.pending = null;
    } else if (this.pending !== best) {
      this.pending = best;
      this.pendingSince = now;
    } else if (now - this.pendingSince >= 2000 && now - this.changedAt >= 5000) {
      this.step = best;
      this.changedAt = now;
      this.pending = null;
    }
    return this.step;
  }
}
