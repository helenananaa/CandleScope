import type { IPriceLine, LineStyle, LineWidth } from "lightweight-charts";
import type { MainSeriesHandle, PerfEventRecorder } from "./chartAdapterTypes.js";

/** A horizontal line on the main series, labelled on the price axis. */
export interface ExternalPriceLine {
  id: string;
  price: number;
  color: string;
  title: string;
  style: "solid" | "dashed" | "dotted";
  width?: 1 | 2 | 3;
}

export interface ExternalPriceLineSnapshot {
  lines: readonly ExternalPriceLine[];
  revision: number;
}

export interface ExternalPriceLineSource {
  getSnapshot(): ExternalPriceLineSnapshot;
  subscribe(listener: () => void): () => void;
}

const LINE_STYLE: Readonly<Record<ExternalPriceLine["style"], LineStyle>> = {
  solid: 0,
  dotted: 1,
  dashed: 2,
};

type PriceLineTarget = Pick<MainSeriesHandle, "createPriceLine" | "removePriceLine">;

function lineOptions(line: ExternalPriceLine) {
  return {
    price: line.price,
    color: line.color,
    title: line.title,
    lineStyle: LINE_STYLE[line.style],
    lineWidth: (line.width ?? 1) as LineWidth,
    axisLabelVisible: true,
    lineVisible: true,
  };
}

/**
 * Native price lines do not widen autoscale, so a distant stop never squashes
 * the candles. Lines are diffed by id and updated in place.
 */
export function attachExternalPriceLineSource({
  source,
  targetSeries,
  recordPerfEvent,
}: {
  source: ExternalPriceLineSource;
  targetSeries: PriceLineTarget;
  recordPerfEvent?: PerfEventRecorder;
}): () => void {
  const attached = new Map<string, IPriceLine>();
  let lastRevision = -1;

  const render = () => {
    const snapshot = source.getSnapshot();
    if (snapshot.revision === lastRevision) return;
    lastRevision = snapshot.revision;
    const next = new Set<string>();
    for (const line of snapshot.lines) {
      if (!Number.isFinite(line.price) || next.has(line.id)) continue;
      next.add(line.id);
      const existing = attached.get(line.id);
      if (existing) existing.applyOptions(lineOptions(line));
      else attached.set(line.id, targetSeries.createPriceLine(lineOptions(line)));
    }
    for (const [id, priceLine] of attached) {
      if (next.has(id)) continue;
      try { targetSeries.removePriceLine(priceLine); } catch { /* series disposed */ }
      attached.delete(id);
    }
    recordPerfEvent?.("chart.externalPriceLines.update", {
      lines: attached.size,
      revision: snapshot.revision,
    });
  };

  render();
  const unsubscribe = source.subscribe(render);
  return () => {
    unsubscribe();
    for (const priceLine of attached.values()) {
      try { targetSeries.removePriceLine(priceLine); } catch { /* series disposed */ }
    }
    attached.clear();
  };
}

/** A minimal mutable source for producers that compute lines elsewhere. */
export interface WritablePriceLineSource extends ExternalPriceLineSource {
  setLines(lines: readonly ExternalPriceLine[]): void;
}

function sameLines(left: readonly ExternalPriceLine[], right: readonly ExternalPriceLine[]): boolean {
  if (left.length !== right.length) return false;
  return left.every((line, index) => {
    const other = right[index]!;
    return line.id === other.id
      && line.price === other.price
      && line.color === other.color
      && line.title === other.title
      && line.style === other.style
      && (line.width ?? 1) === (other.width ?? 1);
  });
}

export function createPriceLineSource(): WritablePriceLineSource {
  let snapshot: ExternalPriceLineSnapshot = { lines: [], revision: 0 };
  const listeners = new Set<() => void>();
  return {
    getSnapshot: () => snapshot,
    subscribe(listener) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    setLines(lines) {
      if (sameLines(snapshot.lines, lines)) return;
      snapshot = { lines: [...lines], revision: snapshot.revision + 1 };
      for (const listener of listeners) listener();
    },
  };
}
