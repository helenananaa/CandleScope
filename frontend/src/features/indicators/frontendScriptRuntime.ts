import type { IndicatorComputeRequest, IndicatorLine, IndicatorPayloadEnvelope } from "./indicatorTypes.js";
import { frontendScriptSandboxDocument } from "./frontendScriptSandbox.js";

export const FRONTEND_SCRIPT_MAX_BARS = 50_000;
const MAX_MESSAGE = 1_048_576;

export function frontendScriptPayload(lines: IndicatorLine[] = [], error?: string): IndicatorPayloadEnvelope {
  return { ok: !error, ...(error ? { error } : {}), lines,
    series: [], annotations: [], fills: [], legacyFills: [], markers: [], hlines: [],
    bgcolors: [], barcolors: [], signals: [], param_schema: [] };
}

export function validateFrontendScriptInput(request: IndicatorComputeRequest): void {
  if (typeof request.script !== "string" || !request.script.trim() || request.script.length > 65_536) {
    throw new Error("Frontend script must contain 1–65536 characters");
  }
  if (!Array.isArray(request.ohlcv) || !request.ohlcv.length || request.ohlcv.length > FRONTEND_SCRIPT_MAX_BARS) {
    throw new Error(`Frontend scripts support at most ${FRONTEND_SCRIPT_MAX_BARS} input bars`);
  }
  let previous = -Infinity;
  for (const bar of request.ohlcv) {
    if (![bar.time, bar.open, bar.high, bar.low, bar.close, bar.volume].every(value => typeof value === "number" && Number.isFinite(value))
      || !Number.isSafeInteger(bar.time) || bar.time <= previous || bar.volume < 0
      || bar.high < Math.max(bar.open, bar.close, bar.low) || bar.low > Math.min(bar.open, bar.close)) {
      throw new Error("Frontend script input must be ordered, finite OHLCV bars");
    }
    previous = bar.time;
  }
  if (JSON.stringify(request.params ?? {}).length > 32_768) throw new Error("Frontend script parameters are too large");
}

/** Validate untrusted output independently of the worker's plot helper. */
export function parseFrontendScriptOutput(encoded: unknown, request: IndicatorComputeRequest): IndicatorPayloadEnvelope {
  if (typeof encoded !== "string" || encoded.length > MAX_MESSAGE) throw new Error("Invalid frontend script output");
  const parsed: unknown = JSON.parse(encoded);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Invalid frontend script output");
  const value = parsed as Record<string, unknown>;
  if (typeof value.error === "string") return frontendScriptPayload([], value.error.slice(0, 512));
  if (!Array.isArray(value.lines) || !value.lines.length || value.lines.length > 8) throw new Error("Invalid frontend script plots");
  const names = new Set<string>();
  const lines: IndicatorLine[] = value.lines.map((raw: unknown) => {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("Invalid frontend script plot");
    const line = raw as Record<string, unknown>;
    if (typeof line?.name !== "string" || !line.name.trim() || line.name.length > 80 || names.has(line.name)
      || !["main", "separate"].includes(String(line.pane)) || typeof line.color !== "string" || !/^#[\da-f]{6}$/i.test(line.color)
      || !Array.isArray(line.values) || line.values.length !== request.ohlcv.length) throw new Error("Invalid frontend script plot");
    names.add(line.name);
    const data = line.values.flatMap((item: unknown, index: number) => {
      if (item === null) return [];
      if (typeof item !== "number" || !Number.isFinite(item)) throw new Error("Invalid frontend script value");
      return [{ time: request.ohlcv[index]!.time, value: item }];
    });
    return { name: line.name, outputName: line.name, type: "line", pane: String(line.pane), color: line.color, data };
  });
  return frontendScriptPayload(lines);
}

function abortError(): DOMException { return new DOMException("Frontend script cancelled", "AbortError"); }

function isolatedCompute(request: IndicatorComputeRequest, signal?: AbortSignal): Promise<IndicatorPayloadEnvelope> {
  if (signal?.aborted) return Promise.reject(abortError());
  validateFrontendScriptInput(request);
  return new Promise((resolve, reject) => {
    const frame = document.createElement("iframe");
    frame.hidden = true;
    frame.title = "Frontend indicator isolation";
    frame.setAttribute("sandbox", "allow-scripts");
    frame.referrerPolicy = "no-referrer";
    const channel = new MessageChannel();
    let settled = false;
    let connected = false;
    const finish = (result?: IndicatorPayloadEnvelope, error?: Error, workerStopped = false) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      const release = () => {
        channel.port1.close(); channel.port2.close(); frame.remove();
        if (error) reject(error); else resolve(result!);
      };
      if (connected && !workerStopped) {
        // Drain the trusted bootstrap's termination acknowledgement before
        // releasing the slot. If its document failed, destroying that owner
        // remains the bounded cleanup path.
        const cleanup = setTimeout(release, 250);
        channel.port1.onmessage = () => { clearTimeout(cleanup); release(); };
        channel.port1.postMessage("stop");
      } else release();
    };
    const abort = () => finish(undefined, abortError());
    const timer = setTimeout(() => finish(frontendScriptPayload([], "Frontend script exceeded the 2 second execution limit")), 2_000);
    signal?.addEventListener("abort", abort, { once: true });
    channel.port1.onmessage = event => {
      try { finish(parseFrontendScriptOutput(event.data, request), undefined, true); }
      catch (error) { finish(frontendScriptPayload([], error instanceof Error ? error.message : "Invalid frontend script output"), undefined, true); }
    };
    frame.onload = () => {
      if (settled) return;
      connected = true;
      frame.contentWindow?.postMessage({ script: request.script, bars: request.ohlcv, params: request.params ?? {} }, "*", [channel.port2]);
    };
    frame.srcdoc = frontendScriptSandboxDocument();
    document.body.append(frame);
  });
}

let running = 0;
const waiting: (() => void)[] = [];

/** Two workers total, including different charts; cancelled queued work never starts. */
export async function computeFrontendScript(request: IndicatorComputeRequest, signal?: AbortSignal): Promise<IndicatorPayloadEnvelope> {
  if (signal?.aborted) throw abortError();
  if (waiting.length >= 32) return frontendScriptPayload([], "Frontend script queue is full");
  await new Promise<void>((resolve, reject) => {
    const abort = () => {
      const index = waiting.indexOf(enter);
      if (index !== -1) waiting.splice(index, 1);
      reject(abortError());
    };
    const enter = () => {
      signal?.removeEventListener("abort", abort);
      running++; resolve();
    };
    if (running < 2) enter();
    else { waiting.push(enter); signal?.addEventListener("abort", abort, { once: true }); }
  });
  try {
    return await isolatedCompute(request, signal);
  } catch (error) {
    if (signal?.aborted) throw abortError();
    return frontendScriptPayload([], error instanceof Error ? error.message : "Frontend script failed");
  } finally {
    running--;
    waiting.shift()?.();
  }
}
