import assert from "node:assert/strict";
import test from "node:test";

import {
  alertIndicatorFieldKey,
  alertIndicatorFieldLabel,
  canonicalAlertField,
  isAlertIndicatorField,
  labelForSource,
  parseAlertIndicatorField,
  referencedAlertIndicatorFields,
  createConditionNode,
  createGroupNode,
} from "../alertRuleModel.js";
import {
  alertIndicatorOptions,
  alertIndicatorSpecs,
  coerceAlertIndicatorParam,
} from "../alertIndicatorCatalog.js";
import type { IndicatorRegistrySpec } from "../../indicators/indicatorTypes.js";

// Mirrors /api/v1/indicators/registry for the builtins the alert editor offers.
const REGISTRY: IndicatorRegistrySpec[] = [
  {
    name: "RSI", display_name: "RSI", description: "", category: "", inputs: [], outputs: ["rsi"],
    params: {}, is_builtin: true,
    paramSchema: [
      { key: "period", label: "Period", type: "int", default: 14, min: 2, max: 100 },
      { key: "source", label: "Source", type: "string", default: "close", options: ["open", "high", "low", "close", "hl2"] },
      { key: "color", label: "Color", type: "color", default: "#a855f7" },
    ],
  },
  {
    name: "BOLL", display_name: "BOLL", description: "", category: "", inputs: [], outputs: ["middle", "upper", "lower"],
    params: {}, is_builtin: true,
    paramSchema: [
      { key: "period", label: "Period", type: "int", default: 20, min: 2, max: 200 },
      { key: "mult", label: "Multiplier", type: "float", default: 2, min: 0.5, max: 5, step: 0.5 },
      { key: "source", label: "Source", type: "string", default: "close", options: ["close"] },
      { key: "color_upper", label: "Upper", type: "color", default: "#ef4444" },
    ],
  },
  {
    name: "VOL", display_name: "VOL", description: "", category: "", inputs: [], outputs: ["vol"],
    params: {}, is_builtin: true, paramSchema: [{ key: "up_color", type: "color", default: "#22c55e" }],
  },
  {
    name: "MyScript", display_name: "Mine", description: "", category: "", inputs: [], outputs: ["x"],
    params: {}, is_builtin: false, paramSchema: [],
  },
];

test("keys match the backend's canonical spelling, including aliases", () => {
  // Same strings as backend/tests/test_alerts_indicator_fields.py.
  assert.equal(canonicalAlertField("rsi"), "ind:RSI:rsi:period=14,source=close");
  assert.equal(canonicalAlertField("macdHist"), "ind:MACD:hist:fast=12,signal=9,slow=26,source=close");
  assert.equal(canonicalAlertField("ma20"), "ind:MA:ma:period=20,source=close");
  assert.equal(canonicalAlertField("close"), "close");
  assert.equal(
    alertIndicatorFieldKey({ name: "BOLL", output: "upper", params: { source: "close", period: 20, mult: 2.5 } }),
    "ind:BOLL:upper:mult=2.5,period=20,source=close",
  );
});

test("parsing round-trips keys and restores numeric parameters", () => {
  const key = "ind:BOLL:upper:mult=2.5,period=20,source=close";
  const field = parseAlertIndicatorField(key);
  assert.deepEqual(field, { name: "BOLL", output: "upper", params: { mult: 2.5, period: 20, source: "close" } });
  assert.equal(alertIndicatorFieldKey(field!), key);
  assert.equal(parseAlertIndicatorField("close"), null);
  assert.equal(parseAlertIndicatorField("ind:RSI"), null);
  assert.equal(parseAlertIndicatorField("ind:RSI:rsi:period"), null);
  assert.ok(isAlertIndicatorField("rsi") && isAlertIndicatorField(key) && !isAlertIndicatorField("volume"));
});

test("labels read like chart legends", () => {
  assert.equal(labelForSource("ind:RSI:rsi:period=7,source=close"), "RSI(7)");
  assert.equal(labelForSource("ind:RSI:rsi:period=7,source=hl2"), "RSI(7, hl2)");
  assert.equal(labelForSource("ind:MACD:dea:fast=8,signal=5,slow=21,source=close"), "MACD(8, 21, 5) dea");
  assert.equal(labelForSource("ind:BOLL:upper:mult=2.5,period=20,source=close"), "BOLL(20, 2.5) upper");
  assert.equal(labelForSource("ind:VOL:vol:"), "VOL");
  assert.equal(labelForSource("rsi"), "RSI(14)");
  assert.equal(alertIndicatorFieldLabel({ name: "EMA", output: "ema", params: { period: 200, source: "close" } }), "EMA(200)");
});

test("registry builtins become source options without display parameters", () => {
  const specs = alertIndicatorSpecs(REGISTRY);
  assert.deepEqual(specs.map((spec) => spec.name), ["BOLL", "RSI", "VOL"]);
  assert.deepEqual(specs.find((spec) => spec.name === "RSI")!.params.map((param) => param.key), ["period", "source"]);
  assert.deepEqual(alertIndicatorOptions(specs), [
    { value: "ind:BOLL:middle:mult=2,period=20,source=close", label: "BOLL(20, 2) middle" },
    { value: "ind:BOLL:upper:mult=2,period=20,source=close", label: "BOLL(20, 2) upper" },
    { value: "ind:BOLL:lower:mult=2,period=20,source=close", label: "BOLL(20, 2) lower" },
    { value: "ind:RSI:rsi:period=14,source=close", label: "RSI(14)" },
    { value: "ind:VOL:vol:", label: "VOL" },
  ]);
});

test("parameter input keeps the last valid value until the schema accepts it", () => {
  const [, rsi] = alertIndicatorSpecs(REGISTRY);
  const period = rsi!.params.find((param) => param.key === "period")!;
  const source = rsi!.params.find((param) => param.key === "source")!;
  assert.equal(coerceAlertIndicatorParam(period, "7"), 7);
  assert.equal(coerceAlertIndicatorParam(period, ""), null);
  assert.equal(coerceAlertIndicatorParam(period, "1"), null);
  assert.equal(coerceAlertIndicatorParam(period, "7.5"), null);
  assert.equal(coerceAlertIndicatorParam(source, "hl2"), "hl2");
  assert.equal(coerceAlertIndicatorParam(source, "vwap"), null);
});

test("test inputs list every indicator the draft references once", () => {
  const rsi7 = "ind:RSI:rsi:period=7,source=close";
  const group = createGroupNode({
    children: [
      createConditionNode({ left: rsi7 }),
      createConditionNode({ left: "close", rightType: "indicator", rightValue: "ma20" }),
      createConditionNode({ left: rsi7, rightType: "number", rightValue: "30" }),
    ],
  });
  assert.deepEqual(referencedAlertIndicatorFields(group), [rsi7, "ma20"]);
});
