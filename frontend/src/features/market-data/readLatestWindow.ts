import type { KlineFetchResult } from "./klineContracts.js";
import { hasVerifiedCoverage, isKlineResultRepairPending } from "./quality/klineQualityPolicy.js";
import { recordPerfEvent } from "../../runtime/performance/perfMarks.js";

/** Keep one explicit navigation owner while a superseded/pending read settles. */
export async function readLatestWindow<T extends KlineFetchResult & { stale?: boolean; active?: boolean }>({ read, ownsRequest, signal }: {
  read: () => Promise<T>;
  ownsRequest: () => boolean;
  signal: AbortSignal;
}): Promise<T | null> {
  for (let attempt = 0; attempt < 3 && !signal.aborted && ownsRequest(); attempt += 1) {
    const result = await read();
    const owned = !signal.aborted && ownsRequest();
    const verified = hasVerifiedCoverage(result, "history");
    recordPerfEvent("chart.latestWindow.read", { attempt: attempt + 1, owned, verified,
      stale: result.stale, active: result.active, rows: result.data?.length ?? 0,
      state: result.history_state, retryable: result.retryable, storageRevision: result.storage_revision });
    if (!owned || result.stale || result.active === false) return null;
    if (verified && result.data?.length) return result;
    if (attempt === 2 || result.retryable === false || !isKlineResultRepairPending(result)) return null;
    // A server cooldown owns later recovery; this short UI action cannot poll it.
    if (result.retry_at_ms != null && result.retry_at_ms > Date.now() + 250) return null;
    await new Promise<void>(resolve => {
      const finish = () => { clearTimeout(timer); signal.removeEventListener("abort", finish); resolve(); };
      const timer = setTimeout(finish, 250);
      signal.addEventListener("abort", finish, { once: true });
    });
  }
  return null;
}
