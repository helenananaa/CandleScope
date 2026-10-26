import type { ChartSurfaceActions } from "../../chart-adapter/useChartSurfaceRuntime.js";
import type { DrawingRuntimeExportLease, DrawingRuntimeExportPrepareOptions } from "../drawings/useDrawingRuntime.js";

export interface ExportDrawingLease extends DrawingRuntimeExportLease {
  readonly pageTargetsKey?: string;
}

export type PreparePageDrawingExport = (
  active: DrawingRuntimeExportLease,
  options: DrawingRuntimeExportPrepareOptions,
) => Promise<ExportDrawingLease>;

/** Visible cells keep separate drawing barriers; a page capture owns all of them. */
export class PageDrawingExportRegistry {
  private readonly surfaces = new Map<string, ChartSurfaceActions>();

  register(id: string, surface: ChartSurfaceActions): () => void {
    this.surfaces.set(id, surface);
    return () => { if (this.surfaces.get(id) === surface) this.surfaces.delete(id); };
  }

  async prepare(
    activeId: string,
    active: DrawingRuntimeExportLease,
    options: DrawingRuntimeExportPrepareOptions,
  ): Promise<ExportDrawingLease> {
    const members = [...this.surfaces.entries()].sort(([a], [b]) => a.localeCompare(b));
    const leases: Array<readonly [string, DrawingRuntimeExportLease]> = [[activeId, active]];
    let restored = false;
    const restore = async () => {
      if (restored) return;
      restored = true;
      const results = await Promise.allSettled(leases.map(([, lease]) => lease.restore()));
      const failures = results.flatMap<unknown>((result) => result.status === "rejected" ? [result.reason as unknown] : []);
      if (failures.length) throw new AggregateError(failures, "Page drawing restoration failed");
    };
    const membershipMatches = () => members.length === this.surfaces.size
      && members.every(([id, surface]) => this.surfaces.get(id) === surface);
    try {
      const results = await Promise.allSettled(members.filter(([id]) => id !== activeId).map(async ([id, surface]) => {
        options.signal?.throwIfAborted();
        const lease = await surface.prepareExport(options);
        if (!lease) throw new Error("Page chart is not ready for export");
        leases.push([id, lease]);
      }));
      const failures = results.flatMap<unknown>((result) => result.status === "rejected" ? [result.reason as unknown] : []);
      if (failures.length) throw new AggregateError(failures, "Page drawing preparation failed");
      options.signal?.throwIfAborted();
      if (!members.some(([id]) => id === activeId) || !membershipMatches()) {
        throw new Error("Page charts changed during export");
      }
      const pageTargetsKey = JSON.stringify(leases.sort(([a], [b]) => a.localeCompare(b)).map(([id, lease]) => [
        id, lease.receipt.scopeKey, lease.receipt.documentRevision,
        "kind" in lease.receipt.scene && lease.receipt.scene.kind === "hidden-frame",
      ]));
      return Object.freeze({
        leaseId: active.leaseId,
        receipt: active.receipt,
        pageTargetsKey,
        revalidate: async () => {
          if (restored || !membershipMatches()) return false;
          const valid = await Promise.all(leases.map(([, lease]) => lease.revalidate()));
          return membershipMatches() && valid.every(Boolean);
        },
        restore,
      });
    } catch (error) {
      try { await restore(); } catch (restoreError) {
        throw new AggregateError([error, restoreError], "Page drawing preparation and restoration failed");
      }
      throw error;
    }
  }
}
