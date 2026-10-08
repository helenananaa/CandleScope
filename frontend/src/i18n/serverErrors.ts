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

const CODE_PATTERN = /^[A-Z][A-Z0-9_]{2,127}$/;

function errorCode(reason: unknown): string | null {
  if (typeof reason !== "object" || reason === null) return null;
  const code = (reason as { code?: unknown }).code;
  return typeof code === "string" && CODE_PATTERN.test(code) ? code : null;
}

export function serverErrorKind(code: string): ServerErrorKind {
  return KIND_PATTERNS.find(([, pattern]) => pattern.test(code))?.[0] ?? "generic";
}

/**
 * Display text for a caught error. Coded backend errors get a localized summary
 * plus the original message; anything else keeps its message, or the fallback.
 */
export function describeError(reason: unknown, fallback: string): string {
  const message = reason instanceof Error ? reason.message : null;
  const code = errorCode(reason);
  if (code === null) return message ?? fallback;
  const summary = t(SUMMARY_KEYS[serverErrorKind(code)]);
  const detail = message && message !== code ? message : code;
  return t("serverError.withDetail", { summary, detail });
}
