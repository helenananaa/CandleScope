import { useEffect, useRef, useSyncExternalStore } from "react";

/**
 * Whether the local backend this page talks to is up.
 *
 * The desktop host restarts a backend that exits unexpectedly on the same
 * endpoint and reports each phase here. The web build has no supervised
 * backend: it always reads as running.
 */
export type BackendPhase = "running" | "restarting" | "failed" | "stopped";

export interface BackendConnectionState {
  readonly phase: BackendPhase;
  /** Healthy starts so far; a higher value after an outage means the backend is back. */
  readonly generation: number;
  /** The automatic try in progress or waiting (1-based); 0 for a requested restart. */
  readonly attempt: number;
  readonly maxAttempts: number;
  readonly retryAt: string | null;
  readonly error: string | null;
}

export interface BackendStatusBridge {
  readonly backendStatus?: unknown;
  getBackendStatus?(): Promise<unknown>;
  onBackendStatus?(listener: (status: unknown) => void): () => void;
  restartBackend?(): Promise<unknown>;
}

const PHASES: ReadonlySet<string> = new Set(["running", "restarting", "failed", "stopped"]);

export const BACKEND_RUNNING: BackendConnectionState = Object.freeze({
  phase: "running", generation: 0, attempt: 0, maxAttempts: 0, retryAt: null, error: null,
});

function count(value: unknown): number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : 0;
}

export function parseBackendStatus(value: unknown): BackendConnectionState | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  if (typeof record.phase !== "string" || !PHASES.has(record.phase)) return null;
  return Object.freeze({
    phase: record.phase as BackendPhase,
    generation: count(record.generation),
    attempt: count(record.attempt),
    maxAttempts: count(record.maxAttempts),
    retryAt: typeof record.retryAt === "string" ? record.retryAt : null,
    error: typeof record.error === "string" ? record.error : null,
  });
}

export interface BackendConnectionStore {
  getSnapshot(): BackendConnectionState;
  subscribe(listener: () => void): () => void;
  restart(): Promise<void>;
  readonly supervised: boolean;
}

export function createBackendConnectionStore(bridge: BackendStatusBridge | null | undefined): BackendConnectionStore {
  const supervised = Boolean(bridge?.onBackendStatus);
  let current = parseBackendStatus(bridge?.backendStatus) ?? BACKEND_RUNNING;
  const listeners = new Set<() => void>();
  let detach: (() => void) | null = null;
  let events = 0;
  const accept = (value: unknown) => {
    const next = parseBackendStatus(value);
    // Events can overtake a slower status read; never step back a generation.
    if (!next || next.generation < current.generation) return;
    if (JSON.stringify(next) === JSON.stringify(current)) return;
    current = next;
    for (const listener of [...listeners]) listener();
  };
  return {
    supervised,
    getSnapshot: () => current,
    subscribe(listener) {
      listeners.add(listener);
      if (!detach && bridge?.onBackendStatus) {
        detach = bridge.onBackendStatus((value) => {
          events += 1;
          accept(value);
        });
        // Catch a change that happened before this page subscribed, unless
        // an event has already reported a newer state.
        const seen = events;
        void bridge.getBackendStatus?.().then((value) => {
          if (events === seen) accept(value);
        }, () => undefined);
      }
      return () => {
        listeners.delete(listener);
        if (listeners.size === 0 && detach) {
          detach();
          detach = null;
        }
      };
    },
    async restart() {
      if (!bridge?.restartBackend) return;
      accept(await bridge.restartBackend());
    },
  };
}

let defaultStore: BackendConnectionStore | null = null;

export function backendConnectionStore(): BackendConnectionStore {
  defaultStore ??= createBackendConnectionStore(globalThis.window?.candlescopeDesktop);
  return defaultStore;
}

export function isBackendLive(state: BackendConnectionState): boolean {
  return state.phase === "running";
}

export function useBackendConnection(store: BackendConnectionStore = backendConnectionStore()): BackendConnectionState {
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
}

/**
 * Calls `onRestored` once each time the backend is healthy again after an
 * outage this page saw. Returns an unsubscribe.
 */
export function watchBackendRestored(store: BackendConnectionStore, onRestored: () => void): () => void {
  let sawOutage = !isBackendLive(store.getSnapshot());
  return store.subscribe(() => {
    if (!isBackendLive(store.getSnapshot())) {
      sawOutage = true;
      return;
    }
    if (!sawOutage) return;
    sawOutage = false;
    onRestored();
  });
}

/**
 * Surfaces that read the backend only once, or poll slowly, use this to
 * refresh as soon as it is back instead of waiting for their next poll.
 */
export function useBackendRestored(
  onRestored: () => void,
  store: BackendConnectionStore = backendConnectionStore(),
): void {
  const callback = useRef(onRestored);
  callback.current = onRestored;
  useEffect(() => watchBackendRestored(store, () => callback.current()), [store]);
}
