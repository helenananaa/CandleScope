import { API_BASE } from "../../services/apiConfig.js";
import { frontendSupportLogs } from "./supportLog.js";
import { APP_BUILD, APP_VERSION } from "../../shared/appVersion.js";
import { supportArchive } from "./supportArchive.js";
export { APP_BUILD, APP_VERSION } from "../../shared/appVersion.js";

export const SUPPORT_REPOSITORY = "https://github.com/helenananaa/CandleScope";
export interface BackendSupport {
  schema_version: 1;
  version: string;
  data_engine: "active" | "not_initialized";
  logs: {
    started_at: number;
    capacity: number;
    dropped_since_start: number;
    events: { time: number; level: string; source: string; line: number; has_exception: boolean; exception_type?: string }[];
  };
}
const record = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

/** Reconstruct an allowlisted payload: never forward arbitrary server fields. */
export function parseBackendSupport(value: unknown): BackendSupport {
  if (!record(value) || value.schema_version !== 1 || typeof value.version !== "string"
    || !/^\d+\.\d+\.\d+(?:[-+][\w.-]+)?$/.test(value.version)
    || !["active", "not_initialized"].includes(String(value.data_engine)) || !record(value.logs)) throw new Error("Invalid support response");
  const logs = value.logs;
  if (!finite(logs.started_at) || !finite(logs.capacity) || !finite(logs.dropped_since_start)
    || !Array.isArray(logs.events) || logs.events.length > 500) throw new Error("Invalid support logs");
  const events = logs.events.map(event => {
    if (!record(event) || !finite(event.time) || !finite(event.line)
      || typeof event.source !== "string" || event.source.length > 200
      || !/^[\w/-]+\.py$/.test(event.source) || event.source.startsWith("/")
      || !["WARNING", "ERROR", "CRITICAL"].includes(String(event.level))
      || typeof event.has_exception !== "boolean") throw new Error("Invalid support event");
    const exceptionType = typeof event.exception_type === "string" && ["ValueError", "TypeError", "RuntimeError", "KeyError", "IndexError", "TimeoutError", "ConnectionError", "OSError", "FileNotFoundError", "PermissionError", "AssertionError", "MemoryError", "ImportError", "Other"].includes(event.exception_type) ? event.exception_type : undefined;
    return { time: event.time, line: event.line, source: event.source, level: String(event.level), has_exception: event.has_exception,
      ...(exceptionType ? { exception_type: exceptionType } : {}) };
  });
  return { schema_version: 1, version: value.version, data_engine: value.data_engine as BackendSupport["data_engine"],
    logs: { started_at: logs.started_at, capacity: logs.capacity, dropped_since_start: logs.dropped_since_start, events } };
}

export async function fetchBackendSupport(minutes: number, signal?: AbortSignal): Promise<BackendSupport> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, 5000);
  try {
    const response = await fetch(`${API_BASE}/support/diagnostics?minutes=${minutes}`, { signal: controller.signal, cache: "no-store" });
    if (!response.ok) throw new Error("Support endpoint unavailable");
    return parseBackendSupport(await response.json());
  } finally { clearTimeout(timer); signal?.removeEventListener("abort", abort); }
}

export function environmentInfo(backend: BackendSupport | null) {
  const ua = typeof navigator === "undefined" ? "" : navigator.userAgent;
  const browser = /(?:Firefox|Edg|Chrome|Version)\/([\d.]+)/.exec(ua)?.[0] ?? "unknown";
  const os = /Windows NT [\d.]+|Android [\d.]+|Mac OS X [\d_]+|Linux|iPhone OS [\d_]+/.exec(ua)?.[0] ?? "unknown";
  return { application: "CandleScope", frontend_version: APP_VERSION, build: APP_BUILD,
    backend_version: backend?.version ?? "unavailable", backend_connection: backend ? "reachable" : "unavailable",
    data_engine: backend?.data_engine ?? "unknown", os, browser,
    shell: /Electron\/[\d.]+/.exec(ua)?.[0] ?? "web",
    timezone_offset_minutes: new Date().getTimezoneOffset() };
}

export function createSupportBundle(minutes: number, backend: BackendSupport | null) {
  return { schema_version: 1, generated_at: new Date().toISOString(), range_minutes: minutes,
    environment: environmentInfo(backend), frontend: frontendSupportLogs(minutes), backend,
    missing: backend ? [] : ["backend diagnostics unavailable (offline, incompatible version, or request failed)"],
    privacy: "Metadata only. No raw log messages, request/response bodies, credentials, strategy source, account data, databases or storage contents.",
    coverage: "Current page and backend process only; bounded recent warning/error events. No historical log files or full console capture." };
}

export function issueUrl(environment: ReturnType<typeof environmentInfo>): string {
  const body = `### Problem / 问题描述\n\n### Steps to reproduce / 复现步骤\n1. \n2. \n3. \n\n### Expected and actual result / 预期与实际结果\n\n### Time and timezone / 发生时间与时区\n\n### Environment / 环境信息\n\n\`\`\`json\n${JSON.stringify(environment, null, 2)}\n\`\`\`\n\n### Attachments / 附件\nAttach the diagnostic ZIP and optional screenshots after reviewing their contents.\n请检查内容后附上诊断 ZIP 和可选截图。\n`;
  return `${SUPPORT_REPOSITORY}/issues/new?${new URLSearchParams({ body })}`;
}

export function downloadSupportBundle(bundle: ReturnType<typeof createSupportBundle>): void {
  const url = URL.createObjectURL(new Blob([supportArchive(JSON.stringify(bundle, null, 2))], { type: "application/zip" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `candlescope-diagnostics-${bundle.generated_at.replace(/[:.]/g, "-")}.zip`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
