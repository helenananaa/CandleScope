import type { SurfaceViewportSnapshot } from "../chart-representation/chartRepresentationTypes.js";
import type { IntervalString } from "../../utils/intervals.js";
import { intervalsSemanticallyEquivalent } from "../../utils/intervals.js";
import { resolveChartLinkTargetsForChannel } from "../chart-workspace/chartWorkspaceLinkModel.js";
import type { ChartWorkspaceDocument } from "../chart-workspace/chartWorkspaceTypes.js";

export interface ReplayIntervalViewportTransfer {
  readonly snapshot: SurfaceViewportSnapshot;
  readonly targetInterval: IntervalString;
}

/** Capture receiving surfaces before the workspace dispatch can detach their refs. */
export class ReplayIntervalViewportTransfers {
  private readonly receivers = new Map<string, (interval: IntervalString) => void>();

  register(cellId: string, prepare: (interval: IntervalString) => void): () => void {
    this.receivers.set(cellId, prepare);
    return () => { if (this.receivers.get(cellId) === prepare) this.receivers.delete(cellId); };
  }

  prepare(document: ChartWorkspaceDocument, sourceCellId: string, interval: IntervalString): void {
    for (const { cellId } of resolveChartLinkTargetsForChannel(document, sourceCellId, "interval")) {
      const current = document.cells[cellId]?.session.interval;
      if (current && !intervalsSemanticallyEquivalent(current, interval)) this.receivers.get(cellId)?.(interval);
    }
  }

  prepareDocumentChange(before: ChartWorkspaceDocument, after: ChartWorkspaceDocument): void {
    for (const cell of Object.values(after.cells)) {
      const previous = before.cells[cell.id]?.session;
      const next = cell.session;
      // A different market owns a different surface. Never transplant its view.
      if (previous && previous.exchange === next.exchange && previous.marketType === next.marketType
        && previous.symbol === next.symbol && !intervalsSemanticallyEquivalent(previous.interval, next.interval)) {
        this.receivers.get(cell.id)?.(next.interval);
      }
    }
  }
}
