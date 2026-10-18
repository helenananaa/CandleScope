/** First-party bootstrap only. User source is sent as data after isolation. */
function workerMain() {
  const send = globalThis.postMessage.bind(globalThis);
  // The browser's opaque origin and CSP are the isolation boundary. These
  // removals also keep scripts from creating additional workers or transports.
  for (const key of ["Worker", "SharedWorker", "fetch", "XMLHttpRequest", "WebSocket", "EventSource", "importScripts", "WebTransport", "RTCPeerConnection"]) {
    Object.defineProperty(globalThis, key, { value: undefined, configurable: false, writable: false });
  }
  globalThis.onmessage = (event: MessageEvent) => {
    try {
      const { script, bars, params } = event.data as { script: string; bars: { time: number; close: number }[]; params: Record<string, unknown> };
      const lines: { name: string; values: (number | null)[]; pane: string; color: string }[] = [];
      const length = bars.length;
      const plot = (name: string, values: (number | null)[], options: { pane?: string; color?: string } = {}) => {
        if (lines.length >= 8 || typeof name !== "string" || !name.trim() || name.length > 80
          || !Array.isArray(values) || values.length !== length
          || values.some(value => value !== null && (typeof value !== "number" || !Number.isFinite(value)))) {
          throw new Error("plot requires a name and one finite number or null per input bar (maximum 8 plots)");
        }
        const pane = options.pane ?? "separate", color = options.color ?? "#a855f7";
        if (!["main", "separate"].includes(pane) || !/^#[\da-f]{6}$/i.test(color)) throw new Error("Invalid plot style");
        lines.push({ name, values: [...values], pane, color });
      };
      // This Function runs inside the dedicated isolated Worker, never React.
      // eslint-disable-next-line @typescript-eslint/no-implied-eval -- isolated Worker is this language's interpreter
      const compute = new Function("bars", "params", "plot", '"use strict";\n' + script) as (bars: unknown, params: unknown, plot: unknown) => unknown;
      const result = compute(bars, params, plot);
      if (result && typeof result === "object" && "then" in result) throw new Error("Frontend scripts must compute synchronously");
      if (!lines.length) throw new Error("Script did not produce a plot");
      const encoded = JSON.stringify({ lines });
      if (encoded.length > 1_048_576) throw new Error("Frontend script output is too large");
      send(encoded);
    } catch (error) {
      send(JSON.stringify({ error: error instanceof Error ? error.message.slice(0, 512) : "Frontend script failed" }));
    }
  };
}

/** Blob workers inherit this restrictive document CSP. No same-origin token. */
export function frontendScriptSandboxDocument(): string {
  const worker = JSON.stringify(`(${workerMain.toString()})();`).replaceAll("<", "\\u003c");
  return `<!doctype html><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' blob:; worker-src blob:; connect-src 'none'; base-uri 'none'; form-action 'none'"><script>
addEventListener('message', function start(event) {
  if (event.source !== parent || !event.ports[0]) return;
  removeEventListener('message', start);
  const port = event.ports[0];
  const url = URL.createObjectURL(new Blob([${worker}], {type: 'text/javascript'}));
  let worker;
  const stop = () => { if (worker) worker.terminate(); URL.revokeObjectURL(url); };
  port.onmessage = () => { stop(); port.postMessage('stopped'); port.close(); };
  addEventListener('pagehide', stop, {once: true});
  try {
    worker = new Worker(url);
    worker.onmessage = (reply) => {
      stop();
      port.postMessage(typeof reply.data === 'string' && reply.data.length <= 1048576
        ? reply.data : '{"error":"Invalid frontend script output"}');
      port.close();
    };
    worker.onerror = () => { stop(); port.postMessage('{"error":"Frontend script worker failed"}'); port.close(); };
    worker.postMessage(event.data);
  } catch (_) { stop(); port.postMessage('{"error":"Frontend script isolation unavailable"}'); port.close(); }
});
</script>`;
}
