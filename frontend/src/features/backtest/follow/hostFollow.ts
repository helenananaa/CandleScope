/**
 * FOLLOW for HOST-authority runs on the chart (ADR-BACKTEST-015 P4b).
 *
 * The backend keeps a chart's Python run current as bars close (`/strategy-follows`).
 * A chart cell holds that run through a lease: it renews the lease while the run is
 * shown and releases it when the cell lets go; a run no cell holds stops. If the backend
 * forgets the run (it restarted, or the lease lapsed while the page slept), the cell
 * holds it again and shows the new run once it has caught up.
 *
 * Each FOLLOW result is the FIXED run of the same input, continued over newer closed
 * bars (§3.4); when processed bars are revised the backend recomputes it on its own.
 */
export interface HeldFollow {
  followId: string;
  /** The first bar the run applies: the followed fixed run's start. */
  fromMs: number;
  leaseMs: number;
}

/** What the strategy data manager provides; the hold never addresses a route itself. */
export interface FollowHoldPorts {
  /** Create or join the run; `body` names the holding cell (`holder`). */
  hold(body: Record<string, unknown>, signal: AbortSignal): Promise<unknown>;
  renew(followId: string, holder: string, signal: AbortSignal): Promise<unknown>;
  release(followId: string, holder: string): Promise<void>;
  /** Resolves once the run has a result to show (it reached the chart's newest closed bar). */
  ready(followId: string, signal: AbortSignal): Promise<void>;
  /** Whether a failed renewal means the backend no longer has the run. */
  gone(failure: unknown): boolean;
  sleep?(ms: number, signal: AbortSignal): Promise<void>;
}

export class FollowContractError extends Error {
  constructor(message: string) {
    super(`strategy-follow: ${message}`);
    this.name = "FollowContractError";
  }
}

function count(value: unknown, name: string, minimum: number): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum) {
    throw new FollowContractError(`${name} must be an integer of at least ${minimum}`);
  }
  return value;
}

/** Validate a served hold reply. */
export function parseHeldFollow(value: unknown): HeldFollow {
  const body = value !== null && typeof value === "object" ? value as Record<string, unknown> : {};
  const followId = body.follow_id;
  if (typeof followId !== "string" || !/^fl_\S+$/.test(followId)) throw new FollowContractError("follow_id must be a FOLLOW run id");
  return { followId, fromMs: count(body.from_ms, "from_ms", 0), leaseMs: count(body.lease_ms, "lease_ms", 1000) };
}

function aborted(signal: AbortSignal): Error {
  return signal.reason instanceof Error ? signal.reason : new DOMException("The hold was released", "AbortError");
}

function abortableSleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(aborted(signal)); return; }
    const timer = setTimeout(() => { signal.removeEventListener("abort", stop); resolve(); }, ms);
    const stop = () => { clearTimeout(timer); reject(aborted(signal)); };
    signal.addEventListener("abort", stop, { once: true });
  });
}

/**
 * Hold the FOLLOW run for `body` until `signal` aborts. `onReady` reports each run the
 * hold shows, once it has a result. Renewals run at a third of the lease; a renewal
 * that fails for another reason is retried at the next one. Rejects when the backend
 * refuses the input (the caller keeps the fixed result); always releases what it holds.
 */
export async function holdFollow(ports: FollowHoldPorts, body: Record<string, unknown>, holder: string,
  onReady: (held: HeldFollow) => void, signal: AbortSignal): Promise<void> {
  const sleep = ports.sleep ?? abortableSleep;
  let held: HeldFollow | null = null;
  let watching: AbortController | null = null;
  const acquire = async () => {
    watching?.abort();
    held = null;
    const current = parseHeldFollow(await ports.hold({ ...body, holder }, signal));
    held = current;
    const watch = new AbortController();
    watching = watch;
    const stop = () => watch.abort(signal.reason);
    signal.addEventListener("abort", stop, { once: true });
    void ports.ready(current.followId, watch.signal).then(() => {
      if (!watch.signal.aborted && held === current) onReady(current);
    }, () => undefined).finally(() => signal.removeEventListener("abort", stop));
  };
  try {
    await acquire();
    for (;;) {
      await sleep(Math.max(1000, Math.floor(held!.leaseMs / 3)), signal);
      try {
        await ports.renew(held!.followId, holder, signal);
      } catch (failure) {
        if (signal.aborted) throw failure;
        if (ports.gone(failure)) await acquire();
      }
    }
  } finally {
    (watching as AbortController | null)?.abort();
    const last = held as HeldFollow | null;
    if (last) void ports.release(last.followId, holder).catch(() => undefined);
  }
}
