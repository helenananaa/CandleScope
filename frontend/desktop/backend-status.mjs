/**
 * The backend state every renderer sees. Only these fields cross IPC: no
 * command line, path, pid or log location reaches a page.
 */
const PHASES = new Set(["running", "restarting", "failed", "stopped"]);

function finiteOrNull(value) {
  return Number.isFinite(value) ? value : null;
}

export function backendStatusPayload(status) {
  const phase = PHASES.has(status?.phase) ? status.phase : "stopped";
  return {
    phase,
    generation: Number.isSafeInteger(status?.generation) ? status.generation : 0,
    attempt: Number.isSafeInteger(status?.attempt) ? status.attempt : 0,
    maxAttempts: Number.isSafeInteger(status?.maxAttempts) ? status.maxAttempts : 0,
    retryAt: typeof status?.retryAt === "string" ? status.retryAt : null,
    error: typeof status?.error === "string" ? status.error.slice(0, 500) : null,
    exit: status?.exit ? {
      code: finiteOrNull(status.exit.code),
      signal: typeof status.exit.signal === "string" ? status.exit.signal : null,
    } : null,
  };
}

/** The state shown when the desktop runs without a supervised backend. */
export const UNSUPERVISED_BACKEND_STATUS = Object.freeze(backendStatusPayload({ phase: "running", generation: 1 }));

/** Sends every supervisor phase change to the open pages; returns an unsubscribe. */
export function relayBackendStatus(supervisor, broadcast) {
  const listener = (status) => broadcast(backendStatusPayload(status));
  supervisor.on("status", listener);
  return () => supervisor.off("status", listener);
}
