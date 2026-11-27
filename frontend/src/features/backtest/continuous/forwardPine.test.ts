import assert from "node:assert/strict";
import test from "node:test";
import { forwardSupport, pineForwardInputs } from "./forwardPine.js";

test("forward runs accept Python and Pine on the chart's own bars (B-333b)", () => {
  assert.deepEqual(forwardSupport("python", undefined), { supported: true });
  assert.deepEqual(forwardSupport("python", { transform: "heikin_ashi" }), { supported: true });
  assert.deepEqual(forwardSupport("pine", undefined), { supported: true });
  assert.deepEqual(forwardSupport("pine", { transform: "heikin_ashi" }), { supported: false, reason: "PINE_SIGNAL_CHART" });
  for (const language of [undefined, "", "pyne", "builtin"]) {
    assert.deepEqual(forwardSupport(language, undefined), { supported: false, reason: "LANGUAGE" }, String(language));
  }
});

test("a Pine forward run sends libraries apart from its parameters, as a chart run reads them", () => {
  const library = '//@version=6\nlibrary("Twice")\nexport twice(float x) => x * 2\n';
  assert.deepEqual(pineForwardInputs({ length: 3, __pineLibraries: { "local/Twice/1": library }, __pineInputs: { contexts: [] } }),
    { parameters: { length: 3 }, libraries: { "local/Twice/1": library } });
  // Edited library text wins over the saved mapping, as in chartStrategyRunRequest.
  assert.deepEqual(pineForwardInputs({ __pineLibraries: { "local/Old/1": library }, __pineLibrariesText: JSON.stringify({ "local/New/1": library }) }),
    { parameters: {}, libraries: { "local/New/1": library } });
  assert.deepEqual(pineForwardInputs({}), { parameters: {}, libraries: {} });
  assert.throws(() => pineForwardInputs({ __pineLibrariesText: "[1]" }), /import-path/);
});
