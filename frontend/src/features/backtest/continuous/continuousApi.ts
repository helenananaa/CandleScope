import { API_BASE } from "../../../services/apiConfig.js";
import { StrategyRunStreamError } from "../backtestRunStream.js";
import type { ContinuousApi, ContinuousPacket } from "./continuousTypes.js";

const MAX_BYTES = 1024 * 1024;
function fail(code: string, message: string): never { throw new StrategyRunStreamError(code, message); }

async function read<T>(response: Response): Promise<T> {
  const reader = response.body?.getReader();
  if (!reader) return fail("CONTINUOUS_RESPONSE_INVALID", "Missing strategy response");
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let bytes = 0, wire = "";
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      bytes += next.value.byteLength;
      if (bytes > MAX_BYTES) fail("BUDGET_EXCEEDED", "Strategy response exceeds the view budget");
      wire += decoder.decode(next.value, { stream: true });
    }
    wire += decoder.decode();
  } finally { await reader.cancel(); reader.releaseLock(); }
  const value = JSON.parse(wire) as { error?: { code?: unknown; message?: unknown } };
  if (!response.ok) fail(typeof value.error?.code === "string" ? value.error.code : "CONTINUOUS_HTTP_FAILED",
    typeof value.error?.message === "string" ? value.error.message : `Strategy HTTP ${response.status}`);
  return value as T;
}

/** Transport only. Execution and subscriptions are owned by StrategyDataManager. */
export function createContinuousApi(base: string): ContinuousApi {
  // Keep request body ownership local; never store editor source in a view cache.
  const call = async <T>(path: string, signal: AbortSignal, body?: unknown, key?: string): Promise<T> => read<T>(await fetch(base + path, {
    method: body === undefined ? "GET" : "POST", signal, cache: "no-store",
    headers: { ...(body === undefined ? {} : { "Content-Type": "application/json" }), ...(key ? { "Idempotency-Key": key } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  }));
  return {
    capabilities: (signal) => call("/capabilities", signal),
    editorParameters: (source, signal) => call("/editor-parameters", signal, { source_text: source }),
    create: (key, body, signal) => call("/runs", signal, body, key),
    request: (key, signal) => call(`/requests/${encodeURIComponent(key)}`, signal),
    catalog: (signal) => call("/runs", signal),
    status: (id, signal) => call(`/runs/${encodeURIComponent(id)}`, signal),
    initial: (id, signal) => call(`/runs/${encodeURIComponent(id)}/initial`, signal),
    page: (id, body, signal) => call(`/runs/${encodeURIComponent(id)}/results/query`, signal, body),
    control: (key, body, signal) => call(`/requests/${encodeURIComponent(key)}/control`, signal, body),
    autoRepair: (id, signal) => call(`/runs/${encodeURIComponent(id)}/repair/automatic`, signal),
    setAutoRepair: (id, body, signal) => call(`/runs/${encodeURIComponent(id)}/repair/automatic`, signal, body),
    repairPreview: (id, body, signal) => call(`/runs/${encodeURIComponent(id)}/repair/preview`, signal, body),
    repair: (id, key, body, signal) => call(`/runs/${encodeURIComponent(id)}/repairs`, signal, body, key),
    repairStatus: (key, signal) => call(`/repairs/${encodeURIComponent(key)}`, signal),
    latestRepair: (id, signal) => call(`/runs/${encodeURIComponent(id)}/repairs/latest`, signal),
    cancelRepair: (key, expected, signal) => call(`/repairs/${encodeURIComponent(key)}/cancel`, signal, { expected }),
    stream(id, after, signal, accept) {
      signal.throwIfAborted();
      const url = new URL(`${base}/runs/${encodeURIComponent(id)}/stream`, globalThis.location?.href ?? "http://localhost");
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      url.searchParams.set("protocol", "continuous.v1");
      if (after) url.searchParams.set("after", JSON.stringify(after));
      return new Promise<void>((resolve, reject) => {
        const socket = new WebSocket(url);
        let settled = false;
        let timer = setTimeout(() => finish(new StrategyRunStreamError("CONTINUOUS_DISCONNECTED", "Strategy connection timed out")), 30000);
        const finish = (failure?: unknown) => {
          if (settled) return;
          settled = true; clearTimeout(timer); signal.removeEventListener("abort", abort);
          socket.onopen = null; socket.onmessage = null; socket.onclose = null; socket.onerror = null;
          socket.close();
          if (failure) reject(failure instanceof Error ? failure : new Error(String(failure))); else resolve();
        };
        const abort = () => finish(signal.reason ?? new DOMException("Aborted", "AbortError"));
        signal.addEventListener("abort", abort, { once: true });
        const alive = () => {
          clearTimeout(timer);
          timer = setTimeout(() => finish(new StrategyRunStreamError("CONTINUOUS_DISCONNECTED", "Strategy heartbeat timed out")), 90000);
        };
        socket.onopen = () => {
          try { alive(); accept({ protocol: "continuous.v1", type: "connected" }); }
          catch (failure) { finish(failure); }
        };
        socket.onmessage = (event) => {
          try {
            if (typeof event.data !== "string" || event.data.length > MAX_BYTES || new TextEncoder().encode(event.data).length > MAX_BYTES)
              fail("BUDGET_EXCEEDED", "Strategy message exceeds the view budget");
            const packet = JSON.parse(event.data) as ContinuousPacket;
            if (packet.protocol !== "continuous.v1") fail("PROTOCOL_UNSUPPORTED", "Unexpected strategy protocol");
            alive();
            if (packet.type === "error") fail(packet.error?.code ?? "CONTINUOUS_STREAM_FAILED", packet.error?.message ?? "Strategy stream failed");
            accept(packet);
            if (packet.terminal) finish();
          } catch (failure) { finish(failure); }
        };
        socket.onclose = () => finish(new StrategyRunStreamError("CONTINUOUS_DISCONNECTED", "Strategy view disconnected"));
        socket.onerror = () => finish(new StrategyRunStreamError("CONTINUOUS_DISCONNECTED", "Strategy view disconnected"));
        if (signal.aborted) abort();
      });
    },
  };
}

const configured = String(import.meta.env?.VITE_BACKTEST_API_BASE ?? "").trim().replace(/\/$/, "");
export const defaultContinuousApi = createContinuousApi(`${configured || `${API_BASE}/backtests`}/continuous`);
