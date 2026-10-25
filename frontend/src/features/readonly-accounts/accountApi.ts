import type {} from "../../desktop/desktopWindowManager.js";

export type FactKind = "fills" | "orders" | "bills";
export type Fact = Record<string, unknown>;
export interface AccountStatus {
  available: boolean;
  serviceError?: string | null;
  account: { status: string; error_code: string | null; venue_uid: string; last_success_ms: number | null; enabled: number } | null;
  counts: Record<string, number>;
  scans: { kind: string; start_ms: number; end_ms: number; complete: number; pages: number }[];
  coverage: { kind: string; start_ms: number; end_ms: number }[];
  gaps: { kind: string; start_ms: number; end_ms: number; reason: string }[];
  snapshots: Record<string, { receivedMs: number; data: unknown }>;
  stream: { state: string; lastReceivedMs: number | null; error: string | null };
  reconciliation: string;
}
export interface JournalVersion {
  noteId: string;
  version: number;
  recordedMs: number;
  eventMs: number;
  fillId: string | null;
  payload: { text: string; tags: string[]; kind: "plan" | "note" | "review" };
}
export interface FactPage {
  items: Fact[];
  next: { beforeTime: number; beforeId: string } | null;
}

export class AccountApiError extends Error {
  constructor(readonly code: string) {
    super(code);
    this.name = "AccountApiError";
  }
}

export function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function nullableString(value: unknown): boolean { return value === null || typeof value === "string"; }
function nullableTime(value: unknown): boolean { return value === null || (typeof value === "number" && Number.isSafeInteger(value) && value >= 0); }
function range(value: unknown): boolean {
  return record(value) && ["fills", "orders", "bills"].includes(String(value.kind))
    && typeof value.start_ms === "number" && typeof value.end_ms === "number"
    && Number.isSafeInteger(value.start_ms) && Number.isSafeInteger(value.end_ms) && value.start_ms <= value.end_ms;
}
function journalVersion(value: unknown): value is JournalVersion {
  return record(value) && typeof value.noteId === "string" && /^[a-f0-9]{32}$/.test(value.noteId)
    && typeof value.version === "number" && Number.isSafeInteger(value.version) && value.version > 0
    && typeof value.recordedMs === "number" && nullableTime(value.recordedMs)
    && typeof value.eventMs === "number" && nullableTime(value.eventMs) && nullableString(value.fillId)
    && record(value.payload) && typeof value.payload.text === "string" && Array.isArray(value.payload.tags)
    && value.payload.tags.every((tag: unknown) => typeof tag === "string") && ["plan", "note", "review"].includes(String(value.payload.kind));
}

export function accountSession() {
  const session = typeof window === "undefined" ? null : window.candlescopeDesktop?.getPluginManagementSession?.();
  if (!session || session.sessionToken === session.csrfToken
    || ![session.sessionToken, session.csrfToken].every((value) => typeof value === "string" && value.length >= 32 && value.length <= 256)) return null;
  try {
    const url = new URL(session.apiBase);
    if (!/^(localhost|127\.0\.0\.1|\[::1\])$/.test(url.hostname)
      || !["http:", "https:"].includes(url.protocol) || url.username || url.password
      || url.pathname !== "/api/v2/plugins" || url.search || url.hash) return null;
    return { ...session, base: `${url.origin}/api/v1/readonly-accounts` };
  } catch {
    return null;
  }
}

async function request(path: string, method = "GET", payload?: unknown, signal?: AbortSignal): Promise<unknown> {
  const session = accountSession();
  if (!session) throw new AccountApiError("DESKTOP_SESSION_REQUIRED");
  const headers: Record<string, string> = { "X-CandleScope-Plugin-Session": session.sessionToken };
  if (method === "POST") {
    headers["Content-Type"] = "application/json";
    headers["X-CandleScope-CSRF"] = session.csrfToken;
    headers["X-CandleScope-User-Action"] = `account.${path.slice(1)}`;
  }
  let response: Response;
  try {
    response = await fetch(`${session.base}${path}`, {
      method, headers, credentials: "omit", cache: "no-store", redirect: "error",
      ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
      signal: signal ?? AbortSignal.timeout(30_000),
    });
  } catch {
    throw new AccountApiError("ACCOUNT_NETWORK_UNAVAILABLE");
  }
  const value: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = record(value) && record(value.error) ? value.error.code : null;
    throw new AccountApiError(typeof error === "string" && /^[A-Z][A-Z0-9_]{1,79}$/.test(error) ? error : "ACCOUNT_UNAVAILABLE");
  }
  return value;
}

export async function getAccountStatus(signal?: AbortSignal): Promise<AccountStatus> {
  const value = await request("/status", "GET", undefined, signal);
  if (!record(value) || value.schemaVersion !== 1 || value.readOnly !== true || value.venue !== "okx"
    || typeof value.available !== "boolean" || !record(value.snapshots) || !record(value.counts)
    || (value.serviceError !== undefined && !nullableString(value.serviceError))
    || !Array.isArray(value.scans) || !Array.isArray(value.coverage) || !Array.isArray(value.gaps)
    || !value.scans.every((scan: unknown) => range(scan) && record(scan) && typeof scan.pages === "number" && (scan.complete === 0 || scan.complete === 1))
    || !value.coverage.every(range) || !value.gaps.every((gap: unknown) => range(gap) && record(gap) && typeof gap.reason === "string")
    || !Object.values(value.counts).every((count) => typeof count === "number" && Number.isSafeInteger(count) && count >= 0)
    || typeof value.reconciliation !== "string"
    || !Object.values(value.snapshots).every((snapshot) => record(snapshot) && typeof snapshot.receivedMs === "number" && nullableTime(snapshot.receivedMs))
    || !record(value.stream) || typeof value.stream.state !== "string" || !nullableTime(value.stream.lastReceivedMs) || !nullableString(value.stream.error)
    || (value.account !== null && (!record(value.account) || typeof value.account.status !== "string"
      || typeof value.account.venue_uid !== "string" || !nullableString(value.account.error_code)
      || !nullableTime(value.account.last_success_ms) || (value.account.enabled !== 0 && value.account.enabled !== 1)))) {
    throw new AccountApiError("ACCOUNT_RESPONSE_INVALID");
  }
  return value as unknown as AccountStatus;
}

export async function getAccountFacts(kind: FactKind, before: FactPage["next"] = null, signal?: AbortSignal): Promise<FactPage> {
  if (!["fills", "orders", "bills"].includes(kind)) throw new AccountApiError("FACT_QUERY_INVALID");
  const query = new URLSearchParams({ limit: "100" });
  if (before) {
    query.set("before_time", String(before.beforeTime));
    query.set("before_id", before.beforeId);
  }
  const value = await request(`/facts/${kind}?${query}`, "GET", undefined, signal);
  if (!record(value) || !Array.isArray(value.items) || !value.items.every(record)
    || (value.next !== null && (!record(value.next) || typeof value.next.beforeTime !== "number"
      || !nullableTime(value.next.beforeTime) || typeof value.next.beforeId !== "string"))) throw new AccountApiError("ACCOUNT_RESPONSE_INVALID");
  return value as unknown as FactPage;
}

export async function connectAccount(credentials: { apiKey: string; secret: string; password: string }): Promise<void> {
  await request("/connect", "POST", credentials);
}
export async function disconnectAccount(forget: boolean): Promise<void> {
  await request("/disconnect", "POST", { forget });
}
export async function resyncAccount(): Promise<void> {
  await request("/resync", "POST", {});
}
export async function getJournal(signal?: AbortSignal): Promise<JournalVersion[]> {
  const rows: JournalVersion[] = [];
  const cursors = new Set<string>();
  let query = "";
  for (let page = 0; page < 100; page++) {
    const value = await request(`/journal${query}`, "GET", undefined, signal);
    if (!record(value) || !Array.isArray(value.versions) || !value.versions.every(journalVersion)) throw new AccountApiError("ACCOUNT_RESPONSE_INVALID");
    rows.push(...value.versions);
    if (value.next === null) return rows;
    if (!record(value.next) || typeof value.next.recordedMs !== "number" || !nullableTime(value.next.recordedMs)
      || typeof value.next.noteId !== "string" || !/^[a-f0-9]{32}$/.test(value.next.noteId)
      || typeof value.next.version !== "number" || !Number.isSafeInteger(value.next.version) || value.next.version < 1) throw new AccountApiError("ACCOUNT_RESPONSE_INVALID");
    query = `?${new URLSearchParams({ before_recorded_ms: String(value.next.recordedMs), before_note_id: value.next.noteId, before_version: String(value.next.version) })}`;
    if (cursors.has(query)) throw new AccountApiError("JOURNAL_CURSOR_STALLED");
    cursors.add(query);
  }
  throw new AccountApiError("JOURNAL_HISTORY_LIMIT");
}
export async function saveJournal(note: {
  noteId: string; baseVersion: number; text: string; tags: string[];
  kind: JournalVersion["payload"]["kind"]; eventMs: number; fillId?: string;
}): Promise<JournalVersion> {
  const value = await request("/journal", "POST", note);
  if (!journalVersion(value)) throw new AccountApiError("ACCOUNT_RESPONSE_INVALID");
  return value;
}
