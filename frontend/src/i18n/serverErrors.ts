import { t, type MessageKey } from "./index.js";

/**
 * Backend errors carry a stable machine code (e.g. TRAINING_RUN_NOT_FOUND) and an
 * English diagnostic message. Show a localized summary chosen from the code and
 * keep the server text as detail, so non-English users get a readable reason
 * while support still sees the exact backend wording.
 */
type ServerErrorKind = "notFound" | "conflict" | "invalid" | "unavailable" | "timeout" | "forbidden" | "network" | "generic";

const KIND_PATTERNS: ReadonlyArray<readonly [ServerErrorKind, RegExp]> = [
  ["network", /TRANSPORT|NETWORK|FETCH_FAILED|CONNECTION/],
  ["timeout", /TIMEOUT|DEADLINE|TIMED_OUT/],
  ["notFound", /NOT_FOUND|MISSING|UNKNOWN_(?:RUN|JOB|SESSION|PLUGIN|DATASET)/],
  ["conflict", /CONFLICT|STALE|REVISION|ALREADY|BUSY|IN_PROGRESS/],
  ["forbidden", /FORBIDDEN|DENIED|UNAUTHORI[SZ]ED|LOCKED|READ_ONLY|NOT_CONTROLLER|PERMISSION/],
  ["unavailable", /UNAVAILABLE|DISABLED|NOT_READY|NOT_ENABLED|OFFLINE/],
  ["invalid", /INVALID|VALIDATION|MALFORMED|UNSUPPORTED|OUT_OF_RANGE|TOO_(?:LARGE|MANY|LONG)/],
];

const SUMMARY_KEYS: Record<ServerErrorKind, MessageKey> = {
  notFound: "serverError.notFound",
  conflict: "serverError.conflict",
  invalid: "serverError.invalid",
  unavailable: "serverError.unavailable",
  timeout: "serverError.timeout",
  forbidden: "serverError.forbidden",
  network: "serverError.network",
  generic: "serverError.generic",
};

/**
 * Codes with a message of their own. It replaces both the generic summary and the English
 * server text, which would only repeat it.
 */
const CODE_KEYS: Readonly<Partial<Record<string, MessageKey>>> = {
  HISTORY_ORIGIN_UNAVAILABLE: "serverError.code.historyOriginUnavailable",
  SUBSCRIBE_FAILED: "serverError.code.subscribeFailed",
  // The web version (browser/host) answers desktop-only routes and its library downloads with these.
  DESKTOP_REQUIRED: "serverError.code.desktopRequired",
  LIBRARY_SOURCE_UNSUPPORTED: "serverError.code.librarySourceUnsupported",
  LIBRARY_RANGE_INVALID: "serverError.code.libraryRangeInvalid",
  LIBRARY_RANGE_TOO_LARGE: "serverError.code.libraryRangeTooLarge",
  LIBRARY_DOWNLOAD_ENDED: "serverError.code.libraryDownloadEnded",
};

const CODE_PATTERN = /^[A-Z][A-Z0-9_]{2,127}$/;

/** HTTP statuses of uncoded backend errors, by the summary they get. */
const STATUS_KINDS: Readonly<Record<number, ServerErrorKind>> = {
  400: "invalid", 401: "forbidden", 403: "forbidden", 404: "notFound", 408: "timeout", 409: "conflict",
  410: "notFound", 412: "conflict", 422: "invalid", 423: "forbidden", 502: "unavailable", 503: "unavailable", 504: "timeout",
};

/** Uncoded backend messages that mean a local service has not finished starting. */
const STARTING_MESSAGE = /\bnot (?:yet )?initiali[sz]ed\b|尚未初始化/i;

/** What browsers say when a request never reached the local service (Chromium, Firefox, Safari). */
const NETWORK_MESSAGE = /^(?:Failed to fetch|NetworkError when attempting to fetch resource\.?|Load failed|Network request failed)$/i;

function errorCode(reason: unknown): string | null {
  if (typeof reason !== "object" || reason === null) return null;
  const code = (reason as { code?: unknown }).code;
  return typeof code === "string" && CODE_PATTERN.test(code) ? code : null;
}

function httpStatus(reason: unknown): number | null {
  if (typeof reason !== "object" || reason === null) return null;
  const status = (reason as { status?: unknown }).status;
  return typeof status === "number" && Number.isInteger(status) && status >= 400 && status <= 599 ? status : null;
}

/** The error's message; a JSON detail such as {"code": …, "message": …} is reduced to its message. */
function errorMessage(reason: unknown): string | null {
  const message = reason instanceof Error ? reason.message : null;
  if (!message?.startsWith("{")) return message || null;
  try {
    const parsed: unknown = JSON.parse(message);
    const inner = typeof parsed === "object" && parsed !== null ? (parsed as { message?: unknown }).message : null;
    return typeof inner === "string" && inner.trim() ? inner : message;
  } catch {
    return message;
  }
}

export function serverErrorKind(code: string): ServerErrorKind {
  return KIND_PATTERNS.find(([, pattern]) => pattern.test(code))?.[0] ?? "generic";
}

/** Summary kind for an uncoded HTTP error. */
export function httpStatusKind(status: number): ServerErrorKind {
  return STATUS_KINDS[status] ?? "generic";
}

/**
 * Display text for a caught error. A code with its own message shows only that; other coded
 * backend errors get a localized summary plus the original message. Uncoded failures get a
 * summary too: a service still starting, a request that never reached the local service, or an
 * HTTP status (plus the backend's message). Anything else keeps its message, or the fallback.
 */
export function describeError(reason: unknown, fallback: string): string {
  const message = errorMessage(reason);
  const code = errorCode(reason);
  if (code !== null) {
    const own = CODE_KEYS[code];
    if (own) return t(own);
    const summary = t(SUMMARY_KEYS[serverErrorKind(code)]);
    // Errors built as "CODE: message" already carry the code; a bare HTTP status adds nothing to the summary.
    const text = message?.startsWith(`${code}:`) ? message.slice(code.length + 1).trim() : message;
    if (text && /^HTTP \d{3}$/.test(text)) return summary;
    const detail = text && text !== code ? text : code;
    return t("serverError.withDetail", { summary, detail });
  }
  if (message && STARTING_MESSAGE.test(message)) return t("serverError.starting");
  if (reason instanceof TypeError && message && NETWORK_MESSAGE.test(message)) return t("serverError.network");
  const status = httpStatus(reason);
  if (status !== null) {
    const summary = t(SUMMARY_KEYS[httpStatusKind(status)]);
    return message && message !== `HTTP ${status}` ? t("serverError.withDetail", { summary, detail: message }) : summary;
  }
  return message ?? fallback;
}
