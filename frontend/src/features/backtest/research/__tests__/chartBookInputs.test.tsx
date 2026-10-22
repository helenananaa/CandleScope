import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { chartBookModes, parseChartBookFile, selectChartExecutionMode } from "../chartBookInputs.js";
import { editableResearchRunConfig } from "../externalProviderModel.js";
import { normalizeResearchRunDraft } from "../backtestResearchAdvancedModel.js";
import ResearchChartBookInputs from "../ResearchChartBookInputs.js";
import { structuralMock } from "../../../../test/testHelpers.js";
import type { BacktestResearchRuntime } from "../backtestResearchTypes.js";
import type { BacktestDataset, BacktestSnapshot } from "../../backtestApi.js";

const recorded = { symbol: "BTCUSDT", exchange: "binance", market_type: "usdm", provenance: { file: "captured" },
  events: [{ time_ms: 0, role: "ORDER_BOOK", payload: { snapshot: true, book_sequence: 1, bid: "9", ask: "11" } },
    { time_ms: 1, role: "TRADES", payload: { source_event_kind: "AGG_TRADE", source_sequence: 1, price: "10", qty: "1" } }] };

for (const mode of chartBookModes) test(`${mode} preserves frozen data and binds the actual chart source kind`, () => {
  const draft = selectChartExecutionMode({ fidelity_mode: "AGG_TRADE_EXECUTION", execution_model_revision: "EXECUTION_REALISM_V2",
    participation_rate: "0.2", execution_data: recorded, signal_clock: "old", bar_builder: "old" }, mode);
  assert.equal(draft.source_event_kind, "TRADE_AND_L2");
  assert.equal(draft.execution_data, undefined);
  assert.equal(draft.signal_clock, undefined);
  assert.equal(draft.execution_model_revision, null);
  assert.equal(draft.participation_rate, null);
  const value = parseChartBookFile(JSON.stringify(recorded));
  const normalized = normalizeResearchRunDraft({ draft: { ...draft, execution_data: value },
    dataset: structuralMock<BacktestDataset>({ dataset_id: "chart", interval: "1m" }),
    snapshot: structuralMock<BacktestSnapshot>({ data_epoch: "epoch", snapshot_hash: "frozen-book" }),
    revisionId: "pine", session: { exchange: "binance", marketType: "usdm", symbol: "BTCUSDT", interval: "1m" },
    startTimeMs: 0, endTimeMs: 59999 });
  assert.equal(normalized.source_event_kind, "TRADE_AND_L2");
  assert.equal(normalized.snapshot_hash, "frozen-book");
  assert.deepEqual(normalized.execution_data, recorded);
  assert.equal(selectChartExecutionMode(normalized, "BAR_APPROX").execution_data, undefined);
});

test("file parsing rejects malformed market identity, unsafe timestamps and raw print relabeling", () => {
  for (const value of [null, [], { ...recorded, provenance: {} }, { ...recorded, exchange: null },
    { ...recorded, events: [{ ...recorded.events[1], time_ms: true }] },
    { ...recorded, events: [{ ...recorded.events[1], payload: { source_event_kind: "RAW_TRADE", source_sequence: 1 } }] },
    { ...recorded, events: [{ ...recorded.events[1], payload: { source_event_kind: "AGG_TRADE", source_sequence: Number.MAX_SAFE_INTEGER + 1 } }] }])
    assert.throws(() => parseChartBookFile(JSON.stringify(value)));
});

test("editing a completed Pine Run preserves its data and removes Host-derived execution fields", () => {
  const editable = editableResearchRunConfig({ execution_data: recorded, pine_runtime_identity: "frozen-engine",
    strategy_source: "compiled-envelope", chart_book_data_hash: "derived", pine_realtime_ticks: true,
    pine_order_runtime_identity: {}, host_policy_revision: "derived", risk_policy: "derived", fill_policy: "derived" });
  assert.deepEqual(editable, { execution_data: recorded });
});

test("advanced Pine chart research exposes a physical file control only when book execution is selected", () => {
  const runtime = structuralMock<BacktestResearchRuntime>({ view: { advancedEnabled: true, selectedTask: "PRECISE_EXECUTION",
    selectedRevisionId: "pine", revisions: [{ revision_id: "pine", language: "PINE_ENGINE" }], runDraftText: JSON.stringify({ fidelity_mode: "BOOK_DEPTH" }),
    session: { exchange: "binance", marketType: "usdm", symbol: "BTCUSDT", interval: "1m" },
    capabilities: { fidelity_modes: [...chartBookModes] } }, actions: {} });
  const html = renderToStaticMarkup(<ResearchChartBookInputs runtime={runtime} />);
  assert.match(html, /type="file"/);
  assert.match(html, /BOOK_ASSISTED/);
  assert.match(html, /BOOK_DEPTH/);
  assert.match(html, /BOOK_SAMPLED/);
  const native = { ...runtime, view: { ...runtime.view, runDraftText: '{"fidelity_mode":"BAR_APPROX"}' } };
  assert.doesNotMatch(renderToStaticMarkup(<ResearchChartBookInputs runtime={native} />), /type="file"/);
  const disabled = { ...runtime, view: { ...runtime.view, advancedEnabled: false } };
  assert.equal(renderToStaticMarkup(<ResearchChartBookInputs runtime={disabled} />), "");
});
