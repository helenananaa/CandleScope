/** One physical read for identical concurrent chart-history requests.
 * No completed cache: each chart still validates the page against its own
 * generation, source identity, history epoch and revealed boundary.
 */
interface HistoryReply {
  readonly ok: boolean;
  readonly status: number;
  readonly payload: unknown;
}

interface SharedRead {
  readonly controller: AbortController;
  readonly promise: Promise<HistoryReply>;
  consumers: number;
  settled: boolean;
}

const pendingByFetcher = new WeakMap<typeof fetch, Map<string, SharedRead>>();
const canceled = () => new DOMException("history request canceled", "AbortError");

export function readReplayHistory(
  fetcher: typeof fetch,
  url: string,
  identityKey: string,
  signal: AbortSignal,
): Promise<HistoryReply> {
  if (signal.aborted) return Promise.reject(canceled());
  let pending = pendingByFetcher.get(fetcher);
  if (!pending) {
    pending = new Map();
    pendingByFetcher.set(fetcher, pending);
  }
  const reads = pending;
  const key = JSON.stringify([url, identityKey]);
  let entry = reads.get(key);
  if (!entry) {
    const controller = new AbortController();
    const promise = (async () => {
      const response = await fetcher(url, {
        method: "GET",
        headers: { Accept: "application/json" },
        credentials: "same-origin",
        signal: controller.signal,
      });
      // The parser creates consumer-owned bars; the raw JSON is never exposed
      // to chart stores or retained after the current read completes.
      const payload: unknown = response.ok
        ? await response.json()
        : await response.json().catch(() => null);
      return { ok: response.ok, status: response.status, payload };
    })();
    const created: SharedRead = { controller, promise, consumers: 0, settled: false };
    entry = created;
    reads.set(key, created);
    const finish = () => {
      created.settled = true;
      if (reads.get(key) === created) reads.delete(key);
    };
    void promise.then(finish, finish);
  }
  const read = entry;
  read.consumers += 1;
  return new Promise((resolve, reject) => {
    let released = false;
    const release = () => {
      if (released) return false;
      released = true;
      signal.removeEventListener("abort", abort);
      read.consumers -= 1;
      if (read.consumers === 0 && !read.settled) {
        if (reads.get(key) === read) reads.delete(key);
        read.controller.abort();
      }
      return true;
    };
    const abort = () => { if (release()) reject(canceled()); };
    signal.addEventListener("abort", abort, { once: true });
    void read.promise.then(
      (reply) => { if (release()) resolve(reply); },
      (error: unknown) => { if (release()) reject(error instanceof Error ? error : new Error(String(error))); },
    );
    if (signal.aborted) abort();
  });
}

/** Viewport demand must await the warmup page already updating its store.
 * Resolving a busy load as a no-op makes a contiguous fill falsely conclude
 * that the source boundary cannot move and permanently stop.
 */
export class ReplayHistoryLoadGate {
  private pending: { key: string | null; promise: Promise<void> } | null = null;

  run(key: string | null, load: (release: () => void) => Promise<void>): Promise<void> {
    if (this.pending?.key === key) return this.pending.promise;
    let resolve!: () => void;
    let reject!: (error: unknown) => void;
    const current = { key, promise: new Promise<void>((yes, no) => { resolve = yes; reject = no; }) };
    this.pending = current;
    const clear = () => { if (this.pending === current) this.pending = null; };
    // Install ownership before invoking load. Its final state publication can
    // synchronously re-enter this gate, or release it before its promise settles.
    try { void load(clear).then(resolve, reject); } catch (error) { reject(error); }
    void current.promise.then(clear, clear);
    return current.promise;
  }

  async runAfterCurrent(key: string | null, needed: () => boolean,
    load: (release: () => void) => Promise<void>): Promise<void> {
    while (needed()) {
      const pending = this.pending;
      if (pending?.key === key) {
        await pending.promise;
        continue;
      }
      await this.run(key, load);
      return;
    }
  }
}
