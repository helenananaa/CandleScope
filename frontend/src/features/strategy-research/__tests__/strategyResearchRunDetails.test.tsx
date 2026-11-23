import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { t } from "../../../i18n/index.js";
import type { ChartStrategyResultBundle } from "../../backtest/chart-tester/chartStrategyResultCache.js";
import { StrategyDataManager, type StrategyDataApi } from "../../market-data/manager/strategyDataManager.js";
import { StrategyResearchRunDetails } from "../StrategyResearchRunDetails.js";

const result = {
  run: { run_id: "bt_details", state: "COMPLETED" },
  config: { start_time_ms: 1_000, end_time_ms: 2_000 },
  report: { data_quality: { source_quality: "exchange_bars" }, fill_model: { kind: "NEXT_OPEN" } },
} as unknown as ChartStrategyResultBundle;

test("a run's details offer its signal trace, export and data quality; the replay review waits for the server's flags", () => {
  const html = renderToStaticMarkup(<StrategyResearchRunDetails result={result} manager={{} as never} />);
  for (const key of ["research.results.tab.trace", "research.results.trace", "research.run.export", "research.results.tab.quality"] as const) {
    assert.ok(html.includes(t(key)), key);
  }
  assert.doesNotMatch(html, /strategy-research-review-bridge/, "no replay review until the backend says it is available");
});

test("the strategy manager reaches the run's export, trace and replay review, and says when the backend lacks them", async () => {
  const calls: string[] = [];
  const api = {
    async exportRun(runId: string) { calls.push(`export ${runId}`); return { run_id: runId }; },
    async getSignalTrace(runId: string, after: number, limit: number) { calls.push(`trace ${runId} ${after} ${limit}`); return { items: [], next_after: 0, has_more: false }; },
    async createReviewBridge(runId: string, start: number, end: number) { calls.push(`bridge ${runId} ${start}-${end}`); return { bridgeId: "b1", state: "BLINDED" }; },
    async revealReviewBridge(id: string) { calls.push(`reveal ${id}`); return { state: "REVEALED" }; },
  } as unknown as StrategyDataApi;
  const manager = new StrategyDataManager(api);
  await manager.exportRun("bt_details");
  await manager.loadSignalTrace("bt_details");
  assert.deepEqual(await manager.createReviewBridge("bt_details", 1_000, 2_000), { bridgeId: "b1", state: "BLINDED" });
  await manager.revealReviewBridge("b1");
  assert.deepEqual(calls, ["export bt_details", "trace bt_details 0 1000", "bridge bt_details 1000-2000", "reveal b1"]);
  await assert.rejects(new StrategyDataManager({} as StrategyDataApi).exportRun("bt_details"), /unavailable/i);
});

test("running again sends only the settings that changed, and never the input or the strategy", async () => {
  const { changedSettings, derivableSettings } = await import("../runDerivation.js");
  const config = { dataset_id: "local-a", snapshot_hash: "sha256:x", strategy_revision_id: "srv2", parameters: { fast: 3 },
    fidelity_mode: "BAR_APPROX", taker_fee_bps: "10", latency_ms: null };
  const original = derivableSettings(config);
  assert.deepEqual(original, { parameters: { fast: 3 }, fidelity_mode: "BAR_APPROX", taker_fee_bps: "10" },
    "only changeable settings the run has; the input and strategy are not offered");
  assert.deepEqual(changedSettings(original, JSON.stringify({ ...original, parameters: { fast: 5 }, taker_fee_bps: "4" })),
    { parameters: { fast: 5 }, taker_fee_bps: "4" });
  assert.deepEqual(changedSettings(original, JSON.stringify(original)), {});
  assert.equal(changedSettings(original, "{ broken"), null);
  assert.equal(changedSettings(original, "[1]"), null);
  const html = renderToStaticMarkup(<StrategyResearchRunDetails result={result} manager={{} as never} onRunCreated={() => undefined} />);
  assert.match(html, /data-testid="strategy-research-rerun"/);
  assert.ok(html.includes(t("researchResult.rerun")));
  const sent: unknown[] = [];
  const manager = new StrategyDataManager({ async deriveRun(runId: string, overrides: unknown, key: string) {
    sent.push([runId, overrides, typeof key]); return { run_id: "bt_derived" };
  } } as unknown as StrategyDataApi);
  assert.equal((await manager.deriveRun("bt_details", { taker_fee_bps: "4" })).run_id, "bt_derived");
  assert.deepEqual(sent, [["bt_details", { taker_fee_bps: "4" }, "string"]]);
});

test("a named version opens as its editor text; a served wrong version or language is refused", async () => {
  const hash = "sha256:" + "a".repeat(64);
  const served = { schema: "candlescope.strategy-version-draft/1", version_hash: hash, language: "python", source: "class Strategy: ...", libraries: {} };
  let reply: unknown = served;
  const manager = new StrategyDataManager({ async getStrategyVersionDraft() { return reply; } } as unknown as StrategyDataApi);
  assert.deepEqual(await manager.loadStrategyVersionDraft(hash),
    { version_hash: hash, language: "python", source: "class Strategy: ...", libraries: {} });
  reply = { ...served, version_hash: "sha256:" + "b".repeat(64) };
  await assert.rejects(manager.loadStrategyVersionDraft(hash), /asked for/);
  reply = { ...served, language: "builtin" };
  await assert.rejects(manager.loadStrategyVersionDraft(hash), /pine or python/);
});
