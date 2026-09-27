import { useEffect, useMemo } from "react";
import {
  ReplayRuntimeLifecycle,
  useReplayLifecycleRuntime,
  type ReplayLifecycleLease,
  type ReplayRuntime,
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

export function createReplayChartRuntimePool(clientInstanceId: string) {
  return new ReplayChartResourcePool((sessionId) => new ReplayRuntimeLifecycle({
    entry: { kind: "adapter", sessionId },
    clientInstanceId,
  }));
}

export function useSharedReplayChartRuntime(
  pool: ReplayChartResourcePool<ReplayRuntimeLifecycle>,
  sessionId: string,
): ReplayRuntime {
  const lifecycle = useMemo(() => pool.get(sessionId), [pool, sessionId]);
  useEffect(() => pool.retain(sessionId), [pool, sessionId]);
  return useReplayLifecycleRuntime(lifecycle);
}
