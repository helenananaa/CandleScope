import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "../../../i18n/index.js";
import type { ContinuousStrategyDataManager } from "../../market-data/manager/continuousStrategyDataManager.js";
import { resultKinds } from "./continuousTypes.js";
import type { ContinuousView } from "./continuousView.js";
import ContinuousAccountView from "./ContinuousAccountView.js";
import { SavedContinuousAccounts } from "./SavedContinuousAccounts.js";

test("committed account renderer keeps exact values and asks only for bounded matching-identity rows", () => {
  setLocale("en");
  const identity = { id: "saved", generation: 3, revision: 8, checkpoint_revision: 7, sequence: 25, event_time_ms: 1499999, data_revision: "epoch" };
  const view: ContinuousView = { identity, run: { ...identity, phase: "REPAIR_REQUIRED" }, stale: true,
    summary: { valuation: { equity: "10000.123456789012345678" }, account: { position_qty: "0.000000000123456789" } },
    counts: Object.fromEntries(resultKinds.map((kind) => [kind, 0])) as ContinuousView["counts"] };
  const reads: string[] = [];
  const manager = { rows(id: string, kind: string, point: unknown, limit: number) {
    assert.equal(id, identity.id); assert.equal(point, identity); reads.push(kind);
    assert.equal(limit, kind === "fills" ? 100 : 200);
    return kind === "fills" ? [{ event_time_ms: 60000, side: "BUY", qty: "0.123456789012345678", price: "100.000000000001" }] : [{ equity: "1" }, { equity: "2" }];
  } } as ContinuousStrategyDataManager;
  const html = renderToStaticMarkup(<ContinuousAccountView manager={manager} view={view} />);
  assert.match(html, /10000\.123456789012345678/); assert.match(html, /0\.000000000123456789/);
  assert.match(html, /0\.123456789012345678/); assert.match(html, /100\.000000000001/);
  assert.match(html, /1970-01-01 00:01:00 UTC/); assert.match(html, /data-continuous-account="saved"/);
  assert.deepEqual(reads, ["fills", "equity_curve"]);
});

test("readonly entry initially renders no execution controls and performs no work during render", () => {
  setLocale("en");
  const manager = new Proxy({}, { get() { throw new Error("No operation during render"); } }) as ContinuousStrategyDataManager;
  const html = renderToStaticMarkup(<SavedContinuousAccounts manager={manager} />);
  assert.match(html, /Read-only accounts saved in this profile/); assert.match(html, /Refresh account list/);
  assert.doesNotMatch(html, /Initialize a new run|Confirm and repair|Stop run|<input/);
});
