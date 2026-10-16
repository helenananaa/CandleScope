import type {
  ExternalMarkerSnapshot,
  ExternalMarkerSource,
  ExternalSeriesMarker,
} from "../../chart-adapter/externalMarkerSource.js";
import type { EpochSeconds } from "../market-data/marketDataTypes.js";
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

/** Fill and note markers, cut at the replay cursor like everything else. */
export function createReplayMarkerSource(colors: ReplayMarkerColors): ReplayMarkerSource {
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
      for (const leg of legsBefore(legs, cursorSec)) {
        const time = floorTo(Math.floor(leg.tsMs / 1000), intervalSec);
        if (!visible(time)) continue;
        const buy = leg.side === "buy";
        markers.push({
          id: `quick-replay:fill:${leg.fillId}:${leg.role}`,
          time: time as EpochSeconds,
          position: buy ? "belowBar" : "aboveBar",
          shape: buy ? "arrowUp" : "arrowDown",
          color: buy ? colors.up : colors.down,
          text: `${buy ? labels.buy : labels.sell} ${Number(leg.qty)} @ ${Number(leg.price)}`,
          size: 1.2,
        });
      }
      for (const note of notesBefore(notes, cursorSec)) {
        const time = floorTo(Math.floor((note.marketTimeMs ?? note.createdAtMs) / 1000), intervalSec);
        if (!visible(time)) continue;
        markers.push({
          id: `quick-replay:note:${note.id}`,
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
