import assert from "node:assert/strict";
import test from "node:test";
import { projectSelectedVersion, readResearchReturn, saveResearchReturn, type ResearchSelectedVersion } from "../researchSelectedVersion.js";
import { createDefaultChartWorkspaceRecord } from "../../chart-workspace/chartWorkspaceLibrary.js";
import { applyControlWorkspaceCommand } from "../../chart-workspace/chartWorkspaceControl.js";
import { StrategyDraftStore, createMemoryStrategyDraftAdapter } from "../../backtest/chart-tester/StrategyDraftStore.js";
import { normalizeChartWorkspace } from "../../chart-workspace/chartWorkspaceStorage.js";

export function selectedFixture(): ResearchSelectedVersion {
  return { schema: "candlescope.research-selected-version/1", run_id: "bt_selected", config_hash: "sha256:" + "1".repeat(64),
    strategy_revision_id: "selected-old-revision", version_hash: "sha256:" + "2".repeat(64),
    program: { language: "python", name: "Selected older experiment", source_text: "# frozen older source", source_hash: "sha256:" + "3".repeat(64),
      revision_source_hash: "sha256:" + "4".repeat(64), compiled_hash: "sha256:" + "5".repeat(64), parameter_schema: [], libraries: {}, bundle_hash: "sha256:" + "6".repeat(64) },
    configuration: { strategy_revision_id: "selected-old-revision", exchange: "binance", market_type: "spot", symbol: "BTCUSDT", interval: "1m",
      fidelity_mode: "BAR_APPROX", source_event_kind: "BAR", account_model: "SPOT_CASH_V1", contract_data_mode: "LEGACY_FIXED_V1", funding_mode: "OFF",
      sizing_policy: "EQUITY_PERCENT_V1", output_mode: "TARGET_POSITION", gap_policy: "REJECT", execution_model_revision: "EXECUTION_REALISM_V2",
      order_end_policy: "CANCEL_AT_END", quick_preset_id: "CRYPTO_SPOT_STANDARD_V1", quick_preset_revision: "2", leverage: "1", participation_rate: "0.1",
      initial_balance: "5000", equity_percent: "20", taker_fee_bps: "3.5", maker_fee_bps: "3.5", slippage_bps: "2", parameters: { nested: { fast: 5 } },
      start_time_ms: 1700000040000, end_time_ms: 1700036040000, warmup_bars: 20, python_trusted_confirmed: true,
      // A reader may receive provenance/account-like metadata: never turn it
      // into current permissions, account state or a reusable run reference.
      account: { cash: "9500", positions: ["existing"] }, checkpoint: { sequence: 500 }, request_key: "research/existing" } };
}
test("explicit selected version produces independent inputs and no account, cursor or permission state", () => {
  const selected = selectedFixture(), before = structuredClone(selected);
  const value = projectSelectedVersion(selected);
  assert.equal(value.attachment.autoRun, false);
  assert.deepEqual(value.attachment.executionOverrides, { initialBalance: "5000", equityPercent: "20", leverage: "1", feeBps: "3.5", slippageBps: "2" });
  assert.deepEqual(value.attachment.initialization, { runId: "bt_selected", versionHash: selected.version_hash, outputMode: "TARGET_POSITION", warmupBars: 20 });
  assert.deepEqual(value.attachment.customRange, { startMs: 1700000040000, endMs: 1700036040000 });
  assert.deepEqual(selected, before);
  (value.attachment.parameters.nested as { fast: number }).fast = 99;
  assert.equal((selected.configuration.parameters as { nested: { fast: number } }).nested.fast, 5);
  for (const key of ["account", "checkpoint", "request_key", "python_trusted_confirmed"]) assert.equal(key in value.attachment, false);
});
for (const [field, value] of Object.entries({ maker_fee_bps: "2", max_notional: "100", leverage: "2", funding_mode: "HISTORICAL_REQUIRED",
  fidelity_mode: "TRADE_REPLAY", participation_rate: "0.2", start_time_ms: 1700000040001, output_mode: "SIGNAL", warmup_bars: 200001 })) {
  test(`unrepresentable ${field} refuses the selected version without modifying it`, () => {
    const selected = selectedFixture(); selected.configuration[field] = value;
    const before = structuredClone(selected);
    assert.throws(() => projectSelectedVersion(selected)); assert.deepEqual(selected, before);
  });
}
test("Pine and retired language data cannot be silently relabelled as qualified continuous Python", () => {
  for (const language of ["pine", "pyne"]) {
    const selected = selectedFixture(); Object.assign(selected.program, { language });
    assert.throws(() => projectSelectedVersion(selected), /language/);
    assert.equal(selected.program.language, language);
  }
});
test("decimal profile checks do not flatten distinct fees or participation through IEEE rounding", () => {
  const selected = selectedFixture(); selected.configuration.maker_fee_bps = "3.50000000000000000001";
  assert.throws(() => projectSelectedVersion(selected), /maker_fee_bps/);
  selected.configuration.maker_fee_bps = "3.5000";
  assert.equal(projectSelectedVersion(selected).attachment.executionOverrides!.feeBps, "3.5");
  selected.configuration.participation_rate = "0.10000000000000000001";
  assert.throws(() => projectSelectedVersion(selected), /participation_rate/);
});
test("draft is independent; atomic application replaces only the chosen chart at its exact revision", async () => {
  const store = new StrategyDraftStore(createMemoryStrategyDraftAdapter());
  const original = await store.save({ id: "draft-original12", displayName: "Old running chart", language: "python", source: "old live source", cursor: null });
  const research = await store.save({ id: "draft-research12", displayName: "Current research editor", language: "python", source: "later unsaved version", cursor: null });
  const selected = selectedFixture(), projected = projectSelectedVersion(selected);
  const copy = await store.save({ id: "draft-returned12", displayName: selected.program.name, language: selected.program.language, source: selected.program.source_text, cursor: null });
  const record = createDefaultChartWorkspaceRecord(1), document = record.document;
  const attachment = { ...projected.attachment, strategyDraftId: original.id };
  document.cells["cell-1"]!.strategyAttachment = attachment;
  const before = structuredClone(document);
  const command = { requestId: "return", workspaceId: record.id, windowId: "main-window", expectedRevision: document.revision,
    charts: [{ cellId: "cell-1", session: projected.session, indicators: document.cells["cell-1"]!.indicators,
      strategyAttachment: { ...projected.attachment, strategyDraftId: copy.id } }] };
  const applied = applyControlWorkspaceCommand(document, command, {});
  assert.equal(applied.document.revision, document.revision + 1);
  assert.equal(applied.document.cells["cell-1"]!.strategyAttachment!.strategyDraftId, copy.id);
  assert.equal(applied.document.cells["cell-1"]!.strategyTesterMode, "CANDLESCOPE");
  assert.equal(applied.document.cells["cell-1"]!.linkGroupId, null);
  assert.deepEqual(applied.document.cells["cell-2"], document.cells["cell-2"]);
  assert.deepEqual(document, before);
  assert.throws(() => applyControlWorkspaceCommand({ ...document, revision: document.revision + 1 }, command, {}), /REVISION_CONFLICT/);
  assert.equal((await store.load(original.id)).record?.source, original.source);
  assert.equal((await store.load(research.id)).record?.source, research.source);
  assert.equal((await store.load(copy.id)).record?.source, selected.program.source_text);
  const restored = normalizeChartWorkspace(JSON.parse(JSON.stringify(applied.document)));
  assert.deepEqual(restored.cells["cell-1"]!.strategyAttachment!.initialization, projected.attachment.initialization);
});
test("return link waits for durable pointer storage and contains no source or account snapshot", async () => {
  const values = new Map<string, string>(); let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const storage = { getItem(key: string) { return values.get(key) ?? null; }, async setItem(key: string, value: string) { await gate; values.set(key, value); } };
  const reference = { schema: 1 as const, runId: "bt_selected", versionHash: "sha256:" + "2".repeat(64), origin: { workspaceId: "w", cellId: "cell-1" } };
  let settled = false; const pending = saveResearchReturn(reference, storage).then((href) => { settled = true; return href; });
  await Promise.resolve(); assert.equal(settled, false); assert.equal(values.size, 0);
  release(); const href = await pending, id = new URL(href, "http://local").searchParams.get("research-version")!;
  assert.deepEqual(readResearchReturn(id, storage), reference);
  assert.ok([...values.values()][0]!.length < 300);
  assert.equal(readResearchReturn("invalid", storage), null);
});
