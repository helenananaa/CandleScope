import type {} from "../../desktop/desktopWindowManager.js";

/** Where the key a source uses now comes from. */
export type CredentialOrigin = "saved" | "environment";

export interface DataSourceField {
  id: string;
  saved: boolean;
  /** At most the last four characters of the saved key. */
  savedHint: string | null;
  savedAtMs: number | null;
  savedError: string | null;
  environmentVariable: string;
  environmentSet: boolean;
  active: CredentialOrigin | null;
  activeHint: string | null;
}

export interface DataSourceStatus {
  id: string;
  name: string;
  signupUrl: string;
  fields: DataSourceField[];
}

export interface DataSourcesStatus {
  schemaVersion: 1;
  vaultAvailable: boolean;
  error: string | null;
  loaded: boolean;
  deletionPending: boolean;
  sources: DataSourceStatus[];
}

export interface CreditUsage { used: number | null; limit: number }

export interface DataSourceCheck {
  ok: true;
  source: CredentialOrigin | "mixed";
  checkedAtMs: number;
  usage: {
    plan: string | null;
    minuteCredits: CreditUsage;
    dailyCredits: CreditUsage | null;
    websocketSymbols: number;
  };
}

export class DataSourceApiError extends Error {
  constructor(readonly code: string, readonly retryAfterSeconds: number | null = null) {
    super(code);
    this.name = "DataSourceApiError";
  }
}

const HINT_MAX = 4;
const CODE = /^[A-Z][A-Z0-9_]{1,79}$/;

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function nullableString(value: unknown): value is string | null { return value === null || typeof value === "string"; }
function count(value: unknown): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0; }
function nullableCount(value: unknown): value is number | null { return value === null || count(value); }
/** A hint is never more than a few characters: a longer value would be a key. */
function hint(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && value.length >= 1 && value.length <= HINT_MAX);
}
function nullableCode(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && CODE.test(value));
}

/** "••••WXYZ" for a hint, "••••" without one. */
export function maskedKey(value: string | null): string {
  return `••••${value ?? ""}`;
}

export function dataSourceSession() {
  const session = typeof window === "undefined" ? null : window.candlescopeDesktop?.getPluginManagementSession?.();
  if (!session || session.sessionToken === session.csrfToken
    || ![session.sessionToken, session.csrfToken].every((value) => typeof value === "string" && value.length >= 32 && value.length <= 256)) return null;
  try {
    const url = new URL(session.apiBase);
    if (!/^(localhost|127\.0\.0\.1|\[::1\])$/.test(url.hostname)
      || !["http:", "https:"].includes(url.protocol) || url.username || url.password
      || url.pathname !== "/api/v2/plugins" || url.search || url.hash) return null;
    return { ...session, base: `${url.origin}/api/v1/data-sources` };
  } catch {
    return null;
  }
}

async function request(path: string, method: "GET" | "POST", userAction?: string, payload?: unknown): Promise<unknown> {
  const session = dataSourceSession();
  if (!session) throw new DataSourceApiError("DESKTOP_SESSION_REQUIRED");
  const headers: Record<string, string> = { "X-CandleScope-Plugin-Session": session.sessionToken };
  if (method === "POST") {
    headers["Content-Type"] = "application/json";
    headers["X-CandleScope-CSRF"] = session.csrfToken;
    headers["X-CandleScope-User-Action"] = `data-sources.${userAction ?? "change"}`;
  }
  let response: Response;
  try {
    response = await fetch(`${session.base}${path}`, {
      method, headers, credentials: "omit", cache: "no-store", redirect: "error",
      ...(method === "POST" ? { body: JSON.stringify(payload ?? {}) } : {}),
      signal: AbortSignal.timeout(30_000),
    });
  } catch {
    throw new DataSourceApiError("DATA_SOURCES_NETWORK_UNAVAILABLE");
  }
  const value: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = record(value) && record(value.error) ? value.error : null;
    const code = error && typeof error.code === "string" && CODE.test(error.code) ? error.code : "DATA_SOURCES_UNAVAILABLE";
    const retry = error && count(error.retryAfterSeconds) ? error.retryAfterSeconds : null;
    throw new DataSourceApiError(code, retry);
  }
  return value;
}

function validField(value: unknown): value is DataSourceField {
  return record(value) && typeof value.id === "string" && typeof value.saved === "boolean"
    && hint(value.savedHint) && nullableCount(value.savedAtMs) && nullableCode(value.savedError)
    && typeof value.environmentVariable === "string" && /^[A-Z][A-Z0-9_]{1,127}$/.test(value.environmentVariable)
    && typeof value.environmentSet === "boolean"
    && (value.active === null || value.active === "saved" || value.active === "environment")
    && hint(value.activeHint);
}

export function validateDataSourcesStatus(value: unknown): DataSourcesStatus {
  if (!record(value) || value.schemaVersion !== 1 || typeof value.vaultAvailable !== "boolean"
    || !nullableCode(value.error) || typeof value.loaded !== "boolean" || typeof value.deletionPending !== "boolean"
    || !Array.isArray(value.sources)
    || !value.sources.every((source: unknown) => record(source) && typeof source.id === "string"
      && typeof source.name === "string" && typeof source.signupUrl === "string"
      && Array.isArray(source.fields) && source.fields.every(validField))) {
    throw new DataSourceApiError("DATA_SOURCES_RESPONSE_INVALID");
  }
  return value as unknown as DataSourcesStatus;
}

function credits(value: unknown): value is CreditUsage {
  return record(value) && nullableCount(value.used) && count(value.limit);
}

export function validateDataSourceCheck(value: unknown): DataSourceCheck {
  if (!record(value) || value.ok !== true || !["saved", "environment", "mixed"].includes(String(value.source))
    || !count(value.checkedAtMs) || !record(value.usage) || !nullableString(value.usage.plan)
    || !credits(value.usage.minuteCredits) || (value.usage.dailyCredits !== null && !credits(value.usage.dailyCredits))
    || !count(value.usage.websocketSymbols)) {
    throw new DataSourceApiError("DATA_SOURCES_RESPONSE_INVALID");
  }
  return value as unknown as DataSourceCheck;
}

const segment = (value: string) => encodeURIComponent(value);

export async function getDataSources(): Promise<DataSourcesStatus> {
  return validateDataSourcesStatus(await request("", "GET"));
}

export async function saveDataSourceKey(source: string, field: string, value: string): Promise<DataSourcesStatus> {
  return validateDataSourcesStatus(await request(`/${segment(source)}/credentials/${segment(field)}`, "POST", "save", { value }));
}

export async function removeDataSourceKey(source: string, field: string): Promise<DataSourcesStatus> {
  return validateDataSourcesStatus(await request(`/${segment(source)}/credentials/${segment(field)}/remove`, "POST", "remove"));
}

export async function checkDataSource(source: string): Promise<DataSourceCheck> {
  return validateDataSourceCheck(await request(`/${segment(source)}/check`, "POST", "check"));
}
