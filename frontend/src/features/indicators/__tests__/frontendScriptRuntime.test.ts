import assert from "node:assert/strict";
import test from "node:test";
import { withFrontendScriptRuntime, FRONTEND_SCRIPT_LANGUAGE } from "../frontendScriptContract.js";
import { isWsHostedIndicator } from "../indicatorPayloadRuntime.js";
import { resolveLocalIndicatorExecution, buildIndicatorComputeJobKey } from "../indicatorComputeJobRuntime.js";
import { parseFrontendScriptOutput, validateFrontendScriptInput, frontendScriptPayload } from "../frontendScriptRuntime.js";
import { routeIndicatorComputeBatch } from "../frontendScriptBatch.js";
import { prepareProvidedBarsIndicator } from "../useProvidedBarsIndicatorRuntime.js";
import { createActiveIndicatorPersistence } from "../activeIndicatorStore.js";
import type { IndicatorComputeRequest } from "../indicatorTypes.js";

const request: IndicatorComputeRequest = { language: FRONTEND_SCRIPT_LANGUAGE, script: 'plot("close", bars.map(bar => bar.close))',
  ohlcv: [1, 2].map(time => ({ time, open: 10, high: 12, low: 9, close: 11, volume: 1 })) };

test("browser capability preserves backend languages and never advertises plugin JS as frontend execution", () => {
  const community = { id: "javascript", name: "Community JS", extensions: [".js"], aliases: [], runtimeId: "community.js", routeMode: "sidecar", available: true, features: [] };
  const original = { schemaVersion: 1, defaultLanguage: "javascript", languages: [community], runtimes: [] };
  const catalog = withFrontendScriptRuntime(original);
  assert.equal(catalog.defaultLanguage, "javascript");
  assert.equal(catalog.languages[0], community);
  assert.equal(withFrontendScriptRuntime(catalog).languages.length, 2);
  assert.equal(original.languages.length, 1);
});

test("restored frontend script uses browser ownership and provided replay bars", () => {
  const values = new Map<string, string>();
  const persistence = createActiveIndicatorPersistence("test", { getItem: key => values.get(key) ?? null, setItem: (key, value) => { values.set(key, value); } });
  persistence.save([{ id: "saved", language: request.language!, script: request.script! }]);
  const restored = persistence.load()[0]!;
  assert.equal(isWsHostedIndicator(restored), false);
  assert.equal(resolveLocalIndicatorExecution(restored).kind, "local");
  assert.equal(resolveLocalIndicatorExecution({ ...restored, engineName: "MA" }).kind, "invalid");
  assert.equal(prepareProvidedBarsIndicator(restored)?.language, FRONTEND_SCRIPT_LANGUAGE);
  assert.notEqual(buildIndicatorComputeJobKey({ indicator: restored, lifecycleKey: "before", params: {} }),
    buildIndicatorComputeJobKey({ indicator: restored, lifecycleKey: "rewound", params: {} }));
});

test("frontend input rejects nonfinite, oversized, duplicate and unordered bars", () => {
  validateFrontendScriptInput(request);
  for (const ohlcv of [[], [...request.ohlcv].reverse(), [request.ohlcv[0]!, request.ohlcv[0]!], [{ ...request.ohlcv[0]!, close: Infinity }]]) {
    assert.throws(() => validateFrontendScriptInput({ ...request, ohlcv }));
  }
  assert.throws(() => validateFrontendScriptInput({ ...request, script: "x".repeat(65_537) }));
});

test("untrusted output cannot choose timestamps, auxiliary actions or nonfinite values", () => {
  const encoded = (values: unknown[], extra = {}) => JSON.stringify({ lines: [{ name: "x", pane: "main", color: "#aabbcc", values, ...extra }], signals: [{ time: 999, side: "buy" }] });
  const payload = parseFrontendScriptOutput(encoded([null, 12], { data: [{ time: 999, value: 123 }] }), request);
  assert.deepEqual(payload.lines[0]!.data, [{ time: 2, value: 12 }]);
  assert.deepEqual(payload.signals, []);
  for (const bad of [encoded([1]), encoded(["10", 11]), encoded([1, 2], { pane: "unknown" }), encoded([1, 2], { color: "url(x)" }), "{" ]) {
    assert.throws(() => parseFrontendScriptOutput(bad, request));
  }
});

test("mixed batch never sends browser source to backend and retains per-item identity", async () => {
  const jobs = [{ clientId: "js", jobKey: "js1", request }, { clientId: "native", jobKey: "pine1", request: { ...request, language: "pine" } }];
  const calls: string[] = [], publications: string[] = [];
  const result = await routeIndicatorComputeBatch({ jobs, onResults: rows => publications.push(...rows.map(row => row.clientId)) }, async options => {
    calls.push(...options.jobs.map(job => job.request.language!));
    return { ok: true, results: options.jobs.map(job => ({ clientId: job.clientId, jobKey: job.jobKey, payload: frontendScriptPayload() })) };
  }, async () => frontendScriptPayload([], "syntax error"));
  assert.deepEqual(calls, ["pine"]);
  assert.deepEqual(result.results.map(row => row.clientId), ["js", "native"]);
  assert.equal(result.results[0]!.payload.error, "syntax error");
  assert.equal(result.results[1]!.payload.ok, true);
  assert.deepEqual(publications, ["js"]);
});
