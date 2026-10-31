import { useEffect, useMemo } from "react";
import {
  ReplayRuntimeLifecycle,
  useReplayLifecycleRuntime,
  type ReplayLifecycleLease,
  type ReplayRuntime,
  type ReplayRuntimeLifecycleOptions,
} from "./useReplayRuntime.js";

/** One resource per distinct track adapter, regardless of chart count/interval. */
export class ReplayChartResourcePool<T extends ReplayLifecycleLease> {
  private readonly entries = new Map<string, { resource: T; leases: number; retirement: object | null }>();

  constructor(private readonly create: (sessionId: string) => T) {}

  get(sessionId: string): T {
    let entry = this.entries.get(sessionId);
    if (!entry) {
      entry = { resource: this.create(sessionId), leases: 0, retirement: null };
      this.entries.set(sessionId, entry);
    }
    return entry.resource;
  }

  retain(sessionId: string): () => void {
    this.get(sessionId);
    const entry = this.entries.get(sessionId)!;
    entry.retirement = null;
    if (entry.leases++ === 0) entry.resource.start();
    let released = false;
    return () => {
      if (released) return;
      released = true;
      if (--entry.leases !== 0) return;
      const retirement = {};
      entry.retirement = retirement;
      // StrictMode setup/cleanup/setup must not terminally dispose a live lease.
      queueMicrotask(() => {
        if (entry.leases !== 0 || entry.retirement !== retirement) return;
        entry.resource.dispose();
        if (this.entries.get(sessionId) === entry) this.entries.delete(sessionId);
      });
    };
  }
}

export function createReplayChartRuntimePool(clientInstanceId: string,
  dependencies: Pick<ReplayRuntimeLifecycleOptions, "api" | "streamFactory" | "dataManager" | "runId"> = {}) {
  return new ReplayChartResourcePool((sessionId) => new ReplayRuntimeLifecycle({
    ...dependencies,
    entry: { kind: "adapter", sessionId },
    clientInstanceId,
    controllerMode: "observe",
  }));
}

export function useSharedReplayChartRuntime(
  pool: ReplayChartResourcePool<ReplayRuntimeLifecycle>,
  sessionId: string,
  controller = false,
): ReplayRuntime {
  const lifecycle = useMemo(() => pool.get(sessionId), [pool, sessionId]);
  useEffect(() => retainReplayChartRuntime(pool, sessionId, controller), [pool, sessionId, controller]);
  return useReplayLifecycleRuntime(lifecycle);
}

/** Used by both the selected run controller and its chart-only consumers. */
export function retainReplayChartRuntime(pool: ReplayChartResourcePool<ReplayRuntimeLifecycle>,
  sessionId: string, controller = false): () => void {
  const releaseController = controller ? pool.get(sessionId).retainController() : undefined;
  const release = pool.retain(sessionId);
  return () => { releaseController?.(); release(); };
}
