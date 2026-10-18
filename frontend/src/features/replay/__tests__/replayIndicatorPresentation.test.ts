import assert from "node:assert/strict";
import test from "node:test";
import { replayIndicatorPresentation } from "../replayIndicatorPresentation.js";
import type { IndicatorRuntime } from "../../indicators/indicatorRuntimeContract.js";
import type { IndicatorDefinition } from "../../indicators/indicatorTypes.js";
import { buildIndicatorPaneData } from "../../indicators/indicatorPaneProjection.js";

const idle = { active: 0, phase: null, prepared: null, target: null } as const;
const preparing = { active: 1, phase: "prefix", prepared: 1250, target: 2000, fraction: 0.25 } as const;
function view(activeIndicators: IndicatorDefinition[]): IndicatorRuntime["view"] {
  return { activeIndicators, ...buildIndicatorPaneData(activeIndicators), markers: [], fills: [], hlines: [], bgcolors: [], barcolors: [],
    signals: [], paramSchemas: {} };
}

test("known panes exist before output and keep the output's identity and order when ready", () => {
  const definitions = ["RSI", "MACD", "VOL", "ATR"].map(engineName => ({ id: engineName.toLowerCase(), engineName, name: engineName }));
  const initial = replayIndicatorPresentation(view(definitions), idle, false);
  assert.deepEqual(initial.view.subPanes.map(pane => pane.id), ["separate-rsi", "separate-macd", "volume-vol", "separate-atr"]);
  assert.ok(initial.view.subPanes.every(pane => pane.statusText && pane.lines.length === 0));
  const ready = replayIndicatorPresentation(view(definitions.map((definition, i) => ({ ...definition,
    lines: [{ pane: i === 2 ? "volume" : "separate", data: [{ time: 1, value: 42 }] }] }))), idle, false);
  assert.deepEqual(ready.view.subPanes.map(pane => pane.id), initial.view.subPanes.map(pane => pane.id));
  assert.equal(ready.statusText, null);
  assert.ok(ready.view.subPanes.every(pane => !pane.statusText && pane.lines[0]!.data![0]!.value === 42));
});

test("progress is determinate only for one calculation and cannot invent script placement", () => {
  const rsi = { id: "rsi", engineName: "RSI" };
  assert.match(replayIndicatorPresentation(view([rsi]), preparing, true).statusText!, /25%/);
  const script = { id: "script", name: "RSI", script: "plot(close)", paneTarget: "sub" as const };
  const multiple = replayIndicatorPresentation(view([rsi, script]), preparing, true);
  assert.doesNotMatch(multiple.statusText!, /%/);
  assert.equal(multiple.view.subPanes.length, 1);
  const scriptOnly = replayIndicatorPresentation(view([script]), idle, true);
  assert.ok(scriptOnly.statusText); assert.equal(scriptOnly.view.subPanes.length, 0);
  assert.equal(replayIndicatorPresentation(view([script]), idle, false).statusText, null);
  assert.equal(replayIndicatorPresentation(view([{ id: "ma", engineName: "MA" }]), idle, true).view.subPanes.length, 0);
});

test("failure remains visible, while hiding or deleting a study removes its preparation pane", () => {
  const failed = { id: "rsi", engineName: "RSI", error: "History unavailable" };
  const result = replayIndicatorPresentation(view([failed]), idle, false);
  assert.equal(result.view.subPanes[0]!.statusText, failed.error);
  assert.match(result.statusText!, /History unavailable/);
  for (const definitions of [[], [{ ...failed, visible: false }]]) {
    const hidden = replayIndicatorPresentation(view(definitions), idle, false);
    assert.equal(hidden.view.subPanes.length, 0); assert.equal(hidden.statusText, null);
  }
});

test("a slow sibling cannot mask a ready pane or claim its progress", () => {
  const rsi = { id: "rsi", engineName: "RSI", lines: [{ pane: "separate", data: [{ time: 1, value: 42 }] }] };
  const ma = { id: "ma", engineName: "MA" };
  const result = replayIndicatorPresentation(view([rsi, ma]), { ...preparing, pendingIds: ["ma"] }, true);
  assert.ok(result.statusText);
  assert.equal(result.view.subPanes[0]!.statusText, null);
  assert.equal(result.view.subPanes[0]!.lines[0]!.data![0]!.value, 42);
  assert.ok(replayIndicatorPresentation(view([rsi]), { ...preparing, pendingIds: ["rsi"] }, true).view.subPanes[0]!.statusText);
});
