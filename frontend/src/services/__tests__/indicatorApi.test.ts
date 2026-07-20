import assert from "node:assert/strict";
import test from "node:test";
import { createServer, type ViteDevServer } from "vite";
import type * as IndicatorApiModule from "../indicatorApi.js";

let server: ViteDevServer;
let computeIndicatorRange: typeof IndicatorApiModule.computeIndicatorRange;
let computeIndicatorRangeBatch: typeof IndicatorApiModule.computeIndicatorRangeBatch;
let fetchScriptRuntimes: typeof IndicatorApiModule.fetchScriptRuntimes;
let analyzeIndicatorScript: typeof IndicatorApiModule.analyzeIndicatorScript;

test.before(async () => {
  server = await createServer({ appType: "custom", server: { middlewareMode: true } });
  const module = await server.ssrLoadModule(
    "/src/services/indicatorApi.js",
  ) as typeof IndicatorApiModule;
  ({
    computeIndicatorRange,
    computeIndicatorRangeBatch,
    fetchScriptRuntimes,
    analyzeIndicatorScript,
  } = module);
});

test.after(async () => {
  await server?.close();
});

test("range preserves a typed HTTP 202 payload and forwards AbortSignal", async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => { globalThis.fetch = originalFetch; });
  const controller = new AbortController();
  let capturedOptions: RequestInit | undefined;
  globalThis.fetch = async (_url, options) => {
    capturedOptions = options;
    return new Response(JSON.stringify({
      ok: false,
      code: "INDICATOR_RANGE_NOT_READY",
      detail: { backfillRequestIds: ["request-1"], waitedMs: 2500 },
    }), {
      status: 202,
      headers: { "Content-Type": "application/json" },
    });
  };

  const payload = await computeIndicatorRange({
    clientId: "vol",
    exchange: "binance",
    marketType: "spot",
    symbol: "BTCUSDT",
    interval: "1m",
    name: "VOL",
    start: 100,
    end: 200,
    signal: controller.signal,
  });
  assert.equal(payload.code, "INDICATOR_RANGE_NOT_READY");
  assert.equal(payload.__httpStatus, 202);
  assert.equal(capturedOptions?.signal, controller.signal);
});

test("batch serializes requests while keeping signal in fetch options", async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => { globalThis.fetch = originalFetch; });
  const controller = new AbortController();
  let capturedOptions: RequestInit | undefined;
  globalThis.fetch = async (_url, options) => {
    capturedOptions = options;
    return new Response(JSON.stringify({
      ok: true,
      results: [{ clientId: "vol", payload: { ok: true } }],
    }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  await computeIndicatorRangeBatch({
    requests: [{
      clientId: "vol",
      exchange: "binance",
      marketType: "spot",
      symbol: "BTCUSDT",
      interval: "1m",
      start: 100,
      end: 200,
    }],
    signal: controller.signal,
  });
  assert.equal(capturedOptions?.signal, controller.signal);
  const body = capturedOptions?.body;
  if (typeof body !== "string") throw new Error("Expected serialized request body");
  assert.deepEqual(JSON.parse(body), {
    requests: [{
      clientId: "vol",
      exchange: "binance",
      marketType: "spot",
      symbol: "BTCUSDT",
      interval: "1m",
      start: 100,
      end: 200,
    }],
  });
});

test("range rejects malformed indicator output points", async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async () => new Response(JSON.stringify({
    ok: true,
    lines: [{ outputName: "ma", data: [{ time: 100, value: "bad" }] }],
  }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });

  await assert.rejects(
    computeIndicatorRange({
      clientId: "ma-1",
      exchange: "binance",
      marketType: "spot",
      symbol: "BTCUSDT",
      interval: "1m",
      name: "MA",
      start: 100,
      end: 200,
    }),
    /indicator\.range\.lines\[0\]\.data\[0\]\.value/,
  );
});

test("batch rejects malformed nested payload envelopes", async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async () => new Response(JSON.stringify({
    ok: true,
    results: [{ clientId: "ma-1", payload: "not-an-object" }],
  }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });

  await assert.rejects(
    computeIndicatorRangeBatch({ requests: [] }),
    /indicator\.rangeBatch\.results\[0\]\.payload/,
  );
});

test("runtime discovery parses versions, availability, and capabilities", async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => { globalThis.fetch = originalFetch; });
  const controller = new AbortController();
  let capturedOptions: RequestInit | undefined;
  globalThis.fetch = async (_url, options) => {
    capturedOptions = options;
    return new Response(JSON.stringify({
      schemaVersion: 1,
      default: "pyne",
      items: [{
        id: "pine-compat",
        label: "Pine-compatible",
        language: "Pine Script",
        package: "pine-compat-runtime",
        available: true,
        version: "0.2.0",
        sourcePath: "C:/runtime",
        reason: null,
        capabilities: { analysis: true, closedBarsOnly: true },
      }],
    }), { status: 200, headers: { "Content-Type": "application/json" } });
  };

  const catalog = await fetchScriptRuntimes(controller.signal);

  assert.equal(capturedOptions?.signal, controller.signal);
  assert.equal(catalog.items[0]?.version, "0.2.0");
  assert.equal(catalog.items[0]?.capabilities.closedBarsOnly, true);
});

test("script analysis sends exact chart context and parses host diagnostics", async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => { globalThis.fetch = originalFetch; });
  let capturedOptions: RequestInit | undefined;
  globalThis.fetch = async (_url, options) => {
    capturedOptions = options;
    return new Response(JSON.stringify({
      schemaVersion: 1,
      runtime: "pine-compat",
      ok: false,
      nativeExecutable: true,
      executable: false,
      diagnostics: [{
        code: "PINE_HOST_CAPABILITY_UNSUPPORTED",
        severity: "error",
        message: "request.security is not hosted",
        span: { line: 3, column: 6 },
        hint: "Use chart-local data.",
      }],
      inputs: [],
      compatibility: {},
      hostCompatibility: { executable: false },
      dependencies: [],
      meta: {},
    }), { status: 200, headers: { "Content-Type": "application/json" } });
  };

  const analysis = await analyzeIndicatorScript({
    runtime: "pine-compat",
    script: "plot(request.security('AAPL', 'D', close))",
    exchange: "binance",
    marketType: "futures",
    symbol: "BTCUSDT",
    interval: "1h",
  });

  const body = capturedOptions?.body;
  if (typeof body !== "string") throw new Error("Expected serialized request body");
  assert.deepEqual(JSON.parse(body), {
    runtime: "pine-compat",
    script: "plot(request.security('AAPL', 'D', close))",
    exchange: "binance",
    market_type: "futures",
    symbol: "BTCUSDT",
    interval: "1h",
  });
  assert.equal(analysis.nativeExecutable, true);
  assert.equal(analysis.executable, false);
  assert.deepEqual(analysis.diagnostics[0]?.span, { line: 3, column: 6 });
});

test("runtime discovery rejects descriptors that omit availability", async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async () => new Response(JSON.stringify({
    schemaVersion: 1,
    default: "pyne",
    items: [{
      id: "pyne",
      label: "Pyne",
      language: "Python",
      package: "pyne-runtime",
      capabilities: {},
    }],
  }), { status: 200, headers: { "Content-Type": "application/json" } });

  await assert.rejects(fetchScriptRuntimes(), /items\[0\]\.available/);
});
