/**
 * Quick replay: a cursor over already-loaded candles.
 *
 * Nothing after the cursor reaches the chart. Candles, fill markers, notes,
 * position and P&L are all cut by the same `time < cursor` rule, so the exit
 * and post-exit notes are simply absent until the cursor passes them. The
 * cursor is always a step boundary in epoch seconds; a candle that opened at
 * `t` is complete once `t + interval <= cursor`, and a candle still forming at
 * the cursor is rebuilt from finer candles that closed before it.
 */
import type { JournalEntry, Trade, TradeLeg } from "./tradingTypes.js";

export interface ReplayBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ReplayEvent {
  kind: "fill" | "note" | "funding";
  timeMs: number;
  id: string;
}

export interface ReplayPosition {
  qty: number;
  avgEntry: number | null;
  realized: number;
  fees: number;
  funding: number;
  unrealized: number | null;
  mfe: number;
  mae: number;
  lastPrice: number | null;
}

export const STANDARD_STEPS = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;

export function floorTo(timeSec: number, stepSec: number): number {
  return Math.floor(timeSec / stepSec) * stepSec;
}

/** Bars visible at the cursor, with the forming bar rebuilt from finer bars. */
export function visibleBars(
  chartBars: readonly ReplayBar[],
  fineBars: readonly ReplayBar[] | null,
  cursorSec: number,
  intervalSec: number,
  stepSec: number,
): ReplayBar[] {
  const out: ReplayBar[] = [];
  for (const bar of chartBars) {
    if (bar.time + intervalSec <= cursorSec) out.push(bar);
    else break;
  }
  if (stepSec >= intervalSec || !fineBars) return out;
  const formingStart = floorTo(cursorSec, intervalSec);
  if (formingStart === cursorSec) return out;
  let partial: ReplayBar | null = null;
  for (const bar of fineBars) {
    if (bar.time < formingStart) continue;
    if (bar.time + stepSec > cursorSec) break;
    partial = partial === null
      ? { ...bar, time: formingStart }
      : {
          time: formingStart,
          open: partial.open,
          high: Math.max(partial.high, bar.high),
          low: Math.min(partial.low, bar.low),
          close: bar.close,
          volume: partial.volume + bar.volume,
        };
  }
  if (partial) out.push(partial);
  return out;
}

export function legsBefore(legs: readonly TradeLeg[], cursorSec: number): TradeLeg[] {
  return legs.filter((leg) => leg.tsMs < cursorSec * 1000);
}

/** Position, P&L and excursions as they stood at the cursor. */
export function positionAt(
  trade: Pick<Trade, "direction" | "legs" | "readonlySource">,
  bars: readonly ReplayBar[],
  cursorSec: number,
  intervalSec: number,
): ReplayPosition {
  const sign = trade.direction === "long" ? 1 : -1;
  let qty = 0;
  let cost = 0;
  let realized = 0;
  let fees = 0;
  let firstFillSec: number | null = null;
  let lastFillSec: number | null = null;
  let enteredQty = 0;
  let enteredCost = 0;
  for (const leg of legsBefore(trade.legs, cursorSec)) {
    const legQty = Number(leg.qty);
    const price = Number(leg.price);
    fees += Number(leg.fee);
    if (firstFillSec === null) firstFillSec = Math.floor(leg.tsMs / 1000);
    lastFillSec = Math.floor(leg.tsMs / 1000);
    if (leg.role === "open" || leg.role === "add") {
      qty += legQty;
      cost += legQty * price;
      enteredQty += legQty;
      enteredCost += legQty * price;
    } else {
      const avg = qty > 0 ? cost / qty : price;
      realized += (price - avg) * legQty * sign;
      cost -= avg * legQty;
      qty -= legQty;
    }
  }
  if (trade.readonlySource) {
    realized = trade.readonlySource.fills.filter((fill) => fill.tsMs < cursorSec * 1000)
      .reduce((sum, fill) => sum + Number(fill.realizedPnl), 0);
  }
  const funding = (trade.readonlySource?.fundingEvents ?? []).filter((event) => event.eventTimeMs < cursorSec * 1000)
    .reduce((sum, event) => sum + Number(event.amount), 0);
  const last = bars.at(-1) ?? null;
  const lastPrice = last ? last.close : null;
  const avgEntry = qty > 1e-12 ? cost / qty : null;
  const unrealized = avgEntry !== null && lastPrice !== null ? (lastPrice - avgEntry) * qty * sign : null;
  let mfe = 0;
  let mae = 0;
  const reference = enteredQty > 0 ? enteredCost / enteredQty : null;
  const flat = qty <= 1e-12;
  if (reference !== null && firstFillSec !== null) {
    for (const bar of bars) {
      // Candle-level estimate: entry and exit candles count in full.
      if (bar.time + intervalSec <= firstFillSec) continue;
      if (flat && lastFillSec !== null && bar.time > lastFillSec) continue;
      const favorable = sign > 0 ? bar.high - reference : reference - bar.low;
      const adverse = sign > 0 ? reference - bar.low : bar.high - reference;
      mfe = Math.max(mfe, favorable);
      mae = Math.max(mae, adverse);
    }
  }
  return { qty, avgEntry, realized, fees, funding, unrealized, mfe, mae, lastPrice };
}

export function replayEvents(trade: Trade, entries: readonly JournalEntry[]): ReplayEvent[] {
  const events: ReplayEvent[] = trade.legs.map((leg) => ({ kind: "fill", timeMs: leg.tsMs, id: leg.fillId }));
  for (const event of trade.readonlySource?.fundingEvents ?? []) {
    events.push({ kind: "funding", timeMs: event.eventTimeMs, id: event.billId });
  }
  for (const entry of entries) {
    events.push({ kind: "note", timeMs: entry.marketTimeMs ?? entry.createdAtMs, id: entry.id });
    if (entry.marketTimeMs === null) {
      for (const revision of entry.revisions ?? []) {
        if (revision.savedAtMs !== entry.createdAtMs) {
          events.push({ kind: "note", timeMs: revision.savedAtMs, id: `${entry.id}:${revision.revision}` });
        }
      }
    }
  }
  return events.sort((left, right) => left.timeMs - right.timeMs);
}

/** Smallest step-aligned cursor that reveals an event at `timeMs`. */
export function cursorRevealing(timeMs: number, stepSec: number): number {
  return floorTo(Math.floor(timeMs / 1000), stepSec) + stepSec;
}

export function nextEventCursor(events: readonly ReplayEvent[], cursorSec: number, stepSec: number): number | null {
  for (const event of events) {
    const reveal = cursorRevealing(event.timeMs, stepSec);
    if (reveal > cursorSec) return reveal;
  }
  return null;
}

export function previousEventCursor(events: readonly ReplayEvent[], cursorSec: number, stepSec: number): number | null {
  let found: number | null = null;
  for (const event of events) {
    const reveal = cursorRevealing(event.timeMs, stepSec);
    if (reveal < cursorSec) found = reveal;
  }
  return found;
}

/** Start just before the entry candle: the entry appears on the first step. */
export function initialCursor(trade: Pick<Trade, "openedAtMs">, intervalSec: number): number {
  return floorTo(Math.floor(trade.openedAtMs / 1000), intervalSec);
}

export function notesBefore<T extends { createdAtMs: number; marketTimeMs: number | null }>(
  entries: readonly T[],
  cursorSec: number,
): T[] {
  return entries.filter((entry) => (entry.marketTimeMs ?? entry.createdAtMs) < cursorSec * 1000);
}

export interface ReplayJournalEntry extends JournalEntry {
  historyUnavailable: boolean;
}

/** Original notes use save time; later review annotations stay in a separate list. */
export function journalAtCursor(entries: readonly JournalEntry[], cursorSec: number): {
  notes: ReplayJournalEntry[]; reviewNotes: JournalEntry[];
} {
  const cut = cursorSec * 1000;
  const notes: ReplayJournalEntry[] = [];
  const reviewNotes: JournalEntry[] = [];
  for (const entry of entries) {
    if (entry.marketTimeMs !== null) {
      if (entry.marketTimeMs < cut) reviewNotes.push({ ...entry,
        // Linking a note also updates entry metadata; it is not a text save.
        updatedAtMs: entry.revisions?.at(-1)?.savedAtMs ?? entry.updatedAtMs,
      });
      continue;
    }
    if (entry.createdAtMs >= cut) continue;
    const revision = entry.revisions?.filter((item) => item.savedAtMs < cut).at(-1);
    const historyUnavailable = !revision?.historyComplete;
    notes.push({ ...entry,
      fields: historyUnavailable ? {} : revision.fields,
      body: historyUnavailable ? "" : revision.body,
      updatedAtMs: revision?.savedAtMs ?? entry.createdAtMs,
      revisionCount: revision?.revision ?? 0,
      // These latest-only metadata are not historical facts.
      tags: [], fieldTiming: {}, revisions: [],
      snapshots: entry.snapshots.filter((snapshot) => snapshot.createdAtMs < cut),
      plan: entry.plan && entry.plan.lockedAtMs < cut ? entry.plan : null,
      historyUnavailable,
    });
  }
  return { notes, reviewNotes };
}

/** Load window: warm-up history before entry, a short tail after the exit. */
export function replayWindow(
  trade: Pick<Trade, "openedAtMs" | "closedAtMs">,
  intervalSec: number,
  nowMs: number,
  { warmupBars = 300, tailBars = 60 }: { warmupBars?: number; tailBars?: number } = {},
): { startSec: number; endSec: number } {
  const open = Math.floor(trade.openedAtMs / 1000);
  const close = Math.floor((trade.closedAtMs ?? nowMs) / 1000);
  const startSec = floorTo(open, intervalSec) - warmupBars * intervalSec;
  const endSec = Math.min(Math.floor(nowMs / 1000), floorTo(close, intervalSec) + tailBars * intervalSec);
  return { startSec, endSec };
}
