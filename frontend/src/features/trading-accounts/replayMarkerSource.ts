import type {
  ExternalMarkerSnapshot,
  ExternalMarkerSource,
  ExternalSeriesMarker,
} from "../../chart-adapter/externalMarkerSource.js";
import type { EpochSeconds } from "../market-data/marketDataTypes.js";
import { addDecimalStrings } from "./liveChartOverlay.js";
import { floorTo, legsBefore, notesBefore } from "./quickReplayModel.js";
import type { JournalEntry, TradeLeg } from "./tradingTypes.js";

export interface ReplayMarkerColors {
  up: string;
  down: string;
  note: string;
}

export interface ReplayMarkerSource extends ExternalMarkerSource {
  update(input: {
    legs: readonly TradeLeg[];
    notes: readonly JournalEntry[];
    cursorSec: number;
    intervalSec: number;
    lastVisibleSec: number | null;
    labels: { buy: string; sell: string; note: string };
  }): void;
}

export interface FillMarkerGroup {
  time: number;
  side: TradeLeg["side"];
  /** Exact decimal sum of the grouped fills. */
  qty: string;
  /** Volume-weighted price, rounded to the finest precision among the fills. */
  price: number;
  count: number;
}

function decimals(value: string): number {
  return value.split(".")[1]?.length ?? 0;
}

/**
 * Same-side fills in one candle become one marker: lightweight-charts stacks
 * markers on a bar, so a scaled entry would otherwise print a column of labels.
 */
export function fillMarkerGroups(legs: readonly TradeLeg[], intervalSec: number): FillMarkerGroup[] {
  const groups = new Map<string, { time: number; side: TradeLeg["side"]; legs: TradeLeg[] }>();
  for (const leg of legs) {
    const time = floorTo(Math.floor(leg.tsMs / 1000), intervalSec);
    const key = `${time}:${leg.side}`;
    const group = groups.get(key);
    if (group) group.legs.push(leg);
    else groups.set(key, { time, side: leg.side, legs: [leg] });
  }
  return [...groups.values()].map(({ time, side, legs: grouped }) => {
    let qty = "0";
    let notional = 0;
    let digits = 0;
    for (const leg of grouped) {
      qty = addDecimalStrings(qty, leg.qty);
      notional += Number(leg.qty) * Number(leg.price);
      digits = Math.max(digits, decimals(leg.price));
    }
    const price = grouped.length === 1
      ? Number(grouped[0]!.price)
      : Number((notional / Number(qty)).toFixed(Math.min(digits, 8)));
    return { time, side, qty, price, count: grouped.length };
  });
}

/**
 * Fill and note markers, cut at the replay cursor like everything else. The
 * live chart reuses it with an unbounded cursor and its own id prefix.
 */
export function createReplayMarkerSource(
  colors: ReplayMarkerColors,
  idPrefix = "quick-replay",
): ReplayMarkerSource {
  let snapshot: ExternalMarkerSnapshot = { markers: [], revision: 0 };
  const listeners = new Set<() => void>();
  return {
    getSnapshot: () => snapshot,
    subscribe(listener) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    update({ legs, notes, cursorSec, intervalSec, lastVisibleSec, labels }) {
      const markers: ExternalSeriesMarker[] = [];
      const visible = (time: number) => lastVisibleSec !== null && time <= lastVisibleSec;
      for (const group of fillMarkerGroups(legsBefore(legs, cursorSec), intervalSec)) {
        if (!visible(group.time)) continue;
        const buy = group.side === "buy";
        const count = group.count > 1 ? ` ×${group.count}` : "";
        markers.push({
          id: `${idPrefix}:fill:${group.time}:${group.side}`,
          time: group.time as EpochSeconds,
          position: buy ? "belowBar" : "aboveBar",
          shape: buy ? "arrowUp" : "arrowDown",
          color: buy ? colors.up : colors.down,
          text: `${buy ? labels.buy : labels.sell} ${Number(group.qty)}${count} @ ${group.price}`,
          size: 1.2,
        });
      }
      for (const note of notesBefore(notes, cursorSec)) {
        const time = floorTo(Math.floor((note.marketTimeMs ?? note.createdAtMs) / 1000), intervalSec);
        if (!visible(time)) continue;
        markers.push({
          id: `${idPrefix}:note:${note.id}`,
          time: time as EpochSeconds,
          position: "aboveBar",
          shape: "circle",
          color: colors.note,
          text: labels.note,
          size: 0.8,
        });
      }
      markers.sort((left, right) => Number(left.time) - Number(right.time));
      snapshot = { markers, revision: snapshot.revision + 1 };
      for (const listener of listeners) listener();
    },
  };
}
