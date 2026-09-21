/** Support events intentionally exclude raw messages, URLs, bodies and stacks. */
export interface SupportEvent {
  time: number;
  kind: "script_error" | "unhandled_rejection" | "request_failed";
  status?: number;
  area?: string;
  error_type?: string;
}
const events: SupportEvent[] = [];
const startedAt = Date.now();
let dropped = 0;
export function recordSupportEvent(event: Omit<SupportEvent, "time">, now = Date.now()): void {
  while (events.length && events[0]!.time < now - 3_600_000) events.shift();
  if (events.length >= 300) { events.shift(); dropped += 1; }
  events.push({ time: now, kind: event.kind, ...(event.status === undefined ? {} : { status: event.status }),
    ...(event.area && AREAS.has(event.area) ? { area: event.area } : {}),
    ...(event.error_type && ERROR_TYPES.has(event.error_type) ? { error_type: event.error_type } : {}) });
}
const AREAS = new Set(["klines", "market", "indicators", "settings", "exchanges", "symbols", "subscriptions", "replay", "backtests", "local", "plugins", "other"]);
const ERROR_TYPES = new Set(["Error", "TypeError", "RangeError", "ReferenceError", "SyntaxError", "URIError", "EvalError", "DOMException"]);
export function recordRequestFailure(url: string, status: number): void {
  let area = "other";
  try {
    const candidate = new URL(url, "http://localhost").pathname.split("/api/v1/")[1]?.split("/")[0] ?? "other";
    if (AREAS.has(candidate)) area = candidate;
  } catch { /* do not retain malformed URLs */ }
  recordSupportEvent({ kind: "request_failed", status, area });
}
export function frontendSupportLogs(minutes: number, now = Date.now()) {
  return { started_at: startedAt, capacity: 300, dropped_since_start: dropped,
    policy: "error metadata only; messages, URLs, bodies and stacks excluded",
    events: events.filter(event => event.time >= now - minutes * 60_000).map(event => ({ ...event })) };
}
if (typeof window !== "undefined") {
  window.addEventListener("error", event => recordSupportEvent({ kind: "script_error", error_type: event.error instanceof Error ? event.error.name : "Error" }));
  window.addEventListener("unhandledrejection", event => recordSupportEvent({ kind: "unhandled_rejection", error_type: event.reason instanceof Error ? event.reason.name : "Error" }));
}
