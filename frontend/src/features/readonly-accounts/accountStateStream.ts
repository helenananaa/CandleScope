import { AccountApiError, accountSession, record, validateAccountStatus, type AccountStatus } from "./accountApi.js";

/** A connection starts with a complete replacement. Cursors fence one account
 * database incarnation; heartbeats do not cause client or server status polls. */
export async function streamAccountState(signal: AbortSignal, update: (status: AccountStatus) => void): Promise<void> {
  signal.throwIfAborted();
  const session = accountSession();
  if (!session) throw new AccountApiError("DESKTOP_SESSION_REQUIRED");
  const response = await fetch(`${session.base}/events`, { signal,
    headers: { "X-CandleScope-Plugin-Session": session.sessionToken },
    credentials: "omit", cache: "no-store", redirect: "error" });
  if (!response.ok || !response.body || !response.headers.get("Content-Type")?.startsWith("application/x-ndjson")) {
    await response.body?.cancel().catch(() => {});
    throw new AccountApiError("ACCOUNT_STATE_STREAM_UNAVAILABLE");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let buffer = "", epoch: string | null = null, uid: string | null = null, sequence = -1;
  const limit = 8 * 1024 * 1024;
  const abort = () => { void reader.cancel().catch(() => {}); };
  signal.addEventListener("abort", abort, { once: true });
  const invalid = (): never => { throw new AccountApiError("ACCOUNT_RESPONSE_INVALID"); };
  const frame = (line: string) => {
    if (line.length > limit) invalid();
    let event: unknown;
    try { event = JSON.parse(line); } catch { return invalid(); }
    if (!record(event) || event.schema !== "candlescope.readonly-account-state/1") return invalid();
    if (event.type === "heartbeat") return;
    if (event.type !== "snapshot" || event.replacement !== true || !record(event.identity) || !record(event.cursor)) return invalid();
    const cursor = event.cursor, identity = event.identity;
    if (typeof cursor.epoch !== "string" || !/^[a-f0-9]{32}$/.test(cursor.epoch)
      || typeof cursor.sequence !== "number" || !Number.isSafeInteger(cursor.sequence) || cursor.sequence < sequence
      || identity.epoch !== cursor.epoch || identity.venue !== "okx"
      || (identity.venueUid !== null && typeof identity.venueUid !== "string")) return invalid();
    const state = validateAccountStatus(event.state);
    if ((epoch !== null && epoch !== cursor.epoch) || (uid !== null && uid !== identity.venueUid)
      || identity.venueUid !== (state.account?.venue_uid ?? null) || !record(event.state)
      || !record(event.state.cursor) || event.state.cursor.epoch !== cursor.epoch || event.state.cursor.sequence !== cursor.sequence) return invalid();
    epoch = cursor.epoch; sequence = cursor.sequence; uid = identity.venueUid;
    update(state);
  };
  try {
    while (true) {
      const { value, done } = await reader.read();
      signal.throwIfAborted();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let index: number;
      while ((index = buffer.indexOf("\n")) >= 0) {
        if (index > limit) invalid();
        const line = buffer.slice(0, index); buffer = buffer.slice(index + 1);
        if (line.trim()) frame(line);
        signal.throwIfAborted();
      }
      if (buffer.length > limit) invalid();
      if (done) throw new AccountApiError("ACCOUNT_STATE_STREAM_ENDED");
    }
  } finally {
    signal.removeEventListener("abort", abort);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
