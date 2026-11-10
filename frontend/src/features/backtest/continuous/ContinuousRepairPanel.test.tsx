import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "../../../i18n/index.js";
import type { ContinuousStrategyDataManager } from "../../market-data/manager/continuousStrategyDataManager.js";
import ContinuousRepairPanel from "./ContinuousRepairPanel.js";
import type { ContinuousView } from "./continuousView.js";
import type { ContinuousRepair } from "./continuousTypes.js";
import { resultKinds } from "./continuousTypes.js";

const identity = { id: "one", generation: 1, revision: 2, checkpoint_revision: 2, sequence: 25, event_time_ms: 1499999, data_revision: "old" };
const view: ContinuousView = { identity, run: { ...identity, phase: "REPAIR_REQUIRED" }, stale: true, summary: {},
  counts: Object.fromEntries(resultKinds.map((kind) => [kind, 0])) as ContinuousView["counts"] };
const manager = new Proxy({}, { get() { throw new Error("Rendering must not execute a repair"); } }) as ContinuousStrategyDataManager;
const repair: ContinuousRepair = { id: "job", run_id: "one", request_key: "saved/key", phase: "PREPARING", target_revision: 3,
  base_identity: identity, plan_id: "a".repeat(64), resume_after: false, from_ms: 600000, through_ms: 1499999, original_from_ms: 0,
  anchor_sequence: 10, full_reinitialization: false, expanded_range_reason: null, progress: { sequence: 15 }, error: null, updated_at_ms: 1 };

test("rendering a stale account offers preview, never implicit consent or execution", () => {
  setLocale("en");
  const html = renderToStaticMarkup(<ContinuousRepairPanel manager={manager} view={view} repair={null} active available />);
  assert.match(html, /Preview repair range/); assert.match(html, /saved code and settings/);
  assert.doesNotMatch(html, /Confirm and repair/); assert.doesNotMatch(html, /checked=""/);
});
test("pending repair shows suffix progress while offline renders disabled mutation controls", () => {
  setLocale("en");
  const html = renderToStaticMarkup(<ContinuousRepairPanel manager={manager} view={view} repair={repair} active available={false} />);
  assert.match(html, /value="5"/); assert.match(html, /max="15"/); assert.match(html, /5 of 15 bars/);
  assert.match(html, /read-only/); assert.match(html, /disabled=""[^>]*>Cancel repair/);
  assert.doesNotMatch(html, /Preview repair range/);
});
