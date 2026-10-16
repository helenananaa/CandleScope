import assert from "node:assert/strict";
import test from "node:test";

import {
  applyActiveIndicatorUpdate,
  applyIndicatorScriptUpdate,
  reconcilePersistedIndicatorDefinitions,
} from "../activeIndicatorStore.js";
import { mergeIndicatorLines } from "../indicatorPayloadRuntime.js";
import { buildIndicatorComputeJobKey, createIndicatorComputeJobCoordinator } from "../indicatorComputeJobRuntime.js";

test("a changed program cannot retain removed plots when its first range patch arrives", () => {
  const old = {
    id: "custom", script: "plot(close, 'Old')", language: "pyne", error: "old error",
    paramSchema: [{ key: "old", type: "int", default: 20 }],
    lines: [{ id: "old", name: "Old", data: [{ time: 1, value: 10 }] }],
  };
  const updated = applyIndicatorScriptUpdate(old, "plot(close, 'New')", "pyne");
  const incoming = [{ id: "new", name: "New", data: [{ time: 2, value: 11 }] }];
  assert.deepEqual(mergeIndicatorLines(updated.lines, incoming), incoming);
  assert.equal(updated.error, undefined);
  assert.equal(updated.paramSchema, undefined);
  assert.equal(old.lines.length, 1);
  assert.equal(applyIndicatorScriptUpdate(old, old.script, old.language).lines, old.lines);
  assert.deepEqual(applyIndicatorScriptUpdate(old, old.script, "pine").lines, []);
  assert.equal(applyIndicatorScriptUpdate(old, "bad", "pine", undefined, () => null), old);
});

test("unchanged durable indicator definitions retain live runtime fields", () => {
  const current = [{
    id: "ma",
    name: "MA",
    params: { period: 20 },
    lines: [{ name: "MA", data: [{ time: 1, value: 2 }] }],
  }];
  const reconciled = reconcilePersistedIndicatorDefinitions(current, [{
    id: "ma",
    name: "MA",
    params: { period: 20 },
  }]);
  assert.equal(reconciled, current);
});

test("an external durable edit replaces stale live indicator definitions", () => {
  const current = [{ id: "ma", name: "MA", params: { period: 20 } }];
  const persisted = [
    { id: "ma", name: "MA", params: { period: 50 } },
    { id: "rsi", name: "RSI", params: { period: 14 } },
  ];
  const reconciled = reconcilePersistedIndicatorDefinitions(current, persisted);
  assert.deepEqual(reconciled, persisted);
  assert.notEqual(reconciled, persisted);
});

test("controlled runtime line updates stay live without becoming workspace edits", () => {
  const current = [{
    id: "boll",
    name: "BOLL",
    params: { period: 20 },
    lines: [],
  }];
  const line = { name: "Middle", data: [{ time: 1, value: 100 }] };
  const update = applyActiveIndicatorUpdate(current, (indicators) => indicators.map((indicator) => ({
    ...indicator,
    lines: [line],
  })));

  assert.equal(update.durableChanged, false);
  assert.deepEqual(update.indicators[0]?.lines, [line]);
  assert.notEqual(update.indicators, current);
});

test("controlled definition edits are marked for workspace persistence", () => {
  const current = [{ id: "ma", name: "MA", params: { period: 20 }, lines: [] }];
  const update = applyActiveIndicatorUpdate(current, (indicators) => indicators.map((indicator) => ({
    ...indicator,
    params: { period: 50 },
  })));

  assert.equal(update.durableChanged, true);
  assert.deepEqual(update.indicators[0]?.params, { period: 50 });
});

test("workspace metadata replacement recomputes an acknowledged job whose visible output was cleared", async () => {
  const definition = { id: "rsi", engineName: "RSI", executionTarget: "local" as const, params: { period: 14 } };
  const key = buildIndicatorComputeJobKey({ indicator: definition, lifecycleKey: "ltc-7m", params: definition.params });
  const coordinator = createIndicatorComputeJobCoordinator();
  const jobs = [{ jobKey: key }];
  let calls = 0;
  const execute = async () => { calls++; return [{ jobKey: key, value: 55.907 }]; };
  await coordinator.schedule({ lifecycleKey: "ltc-7m", jobs, execute });
  let force = false;
  const current = [{ ...definition, lines: [{ name: "RSI", data: [{ time: 100, value: 55.907 }] }] }];
  assert.equal(reconcilePersistedIndicatorDefinitions(current, [definition], undefined, () => { force = true; }), current);
  assert.equal(force, false);
  const incoming = { ...definition, bindingId: "linked-restored" };
  const restored = reconcilePersistedIndicatorDefinitions(current, [incoming], undefined, () => { force = true; });
  assert.equal(restored[0]!.lines, undefined);
  assert.equal(buildIndicatorComputeJobKey({ indicator: incoming, lifecycleKey: "ltc-7m", params: incoming.params }), key);
  const response = await coordinator.schedule({ lifecycleKey: "ltc-7m", jobs, execute, force });
  assert.equal(calls, 2);
  assert.equal(response.results[0]!.value, 55.907);
  coordinator.dispose();
});
