import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { CandleScopeStrategyTesterPanel as ChartStrategyTesterPanel } from "../ChartStrategyTesterPanel.js";
import {
  loadChartStrategyPanelPreferences,
  loadDetachedChartStrategy,
  resolveChartStrategyRunMode,
  saveDetachedChartStrategy,
  saveChartStrategyPanelPreferences,
} from "../chartStrategyPanelPreferences.js";
import { StrategyDraftStore, createMemoryStrategyDraftAdapter } from "../StrategyDraftStore.js";
import { createChartStrategyTesterState } from "../chartStrategyTesterState.js";
import { CHART_STRATEGY_TEMPLATES } from "../chartStrategyTesterUiModel.js";
import { t, type MessageKey } from "../../../../i18n/index.js";

const attachment = {
  schemaVersion: 1 as const,
  strategyDraftId: "draft-1",
  strategyRevisionId: null,
  displayName: "SMA Cross",
  language: "pine" as const,
  parameters: {},
  rangeMode: "ALL_AVAILABLE" as const,
  customRange: null,
  fidelityPreference: "FAST" as const,
  quickPresetId: "CRYPTO_SPOT_STANDARD_V1",
  autoRun: false,
};

const session = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };

test("first open lists templates and recents on one screen, with no blank editor, tabs or premature Run button", () => {
  const html = renderToStaticMarkup(
    <ChartStrategyTesterPanel
      cellScope="workspace\u0000cell-1"
      session={{ exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" }}
      attachment={null}
      draftStore={new StrategyDraftStore(createMemoryStrategyDraftAdapter())}
      onAttachmentChange={() => undefined}
      onEntryStateChange={() => undefined}
      onRunRequest={() => undefined}
      runState={createChartStrategyTesterState(null, "workspace\u0000cell-1")}
      resolution={null}
      sourceDiagnostics={[]}
      pendingDataDraftRevision={null}
      onPrepareData={() => undefined}
      onStopObserving={() => undefined}
      onResumeObserving={() => undefined}
      onSourceDirty={() => undefined}
      onClose={() => undefined}
    />,
  );

  assert.match(html, /data-chart-strategy-panel="true"/);
  for (const key of ["continuous.history", "continuous.historyLive", "continuous.liveOnly"] as const) assert.ok(html.includes(t(key)));
  for (const template of CHART_STRATEGY_TEMPLATES) assert.ok(html.includes(t(template.nameKey)));
  assert.match(html, /chart-strategy-start-footer"><button/);
  assert.match(html, /href="\/strategy\.html\?mode=precise"/);
  assert.doesNotMatch(html, /data-chart-strategy-editor/);
  assert.doesNotMatch(html, /chart-strategy-run-button/);
  assert.doesNotMatch(html, /保存 revision|创建 Run/);
  assert.doesNotMatch(html, /<(?:input|select|textarea)[^>]+(?:dataset|snapshot|run|revision)/i);
  assert.doesNotMatch(html, /role="tab"/);
});

test("an attached strategy offers the same four views in result-first order", () => {
  const html = renderToStaticMarkup(
    <ChartStrategyTesterPanel
      cellScope="workspace\u0000cell-1"
      session={session}
      attachment={attachment}
      draftStore={new StrategyDraftStore(createMemoryStrategyDraftAdapter())}
      onAttachmentChange={() => undefined}
      onEntryStateChange={() => undefined}
      onRunRequest={() => undefined}
      runState={createChartStrategyTesterState({ session, attachment, draftContentRevision: 1 }, "workspace\u0000cell-1")}
      resolution={null}
      sourceDiagnostics={[]}
      pendingDataDraftRevision={null}
      onPrepareData={() => undefined}
      onStopObserving={() => undefined}
      onResumeObserving={() => undefined}
      onSourceDirty={() => undefined}
      onClose={() => undefined}
    />,
  );
  const tabs = [...html.matchAll(/role="tab"[^>]*>([^<]+)</g)].map((match) => match[1]);
  assert.deepEqual(tabs, ["overview", "trades", "script", "settings"].map((tab) => t(`chartTester.tab.${tab}` as MessageKey)));
  assert.match(html, /chart-strategy-run-button/);
});

test("stop observing appears only after a backend Run ID exists", () => {
  const inputs = { session, attachment, draftContentRevision: 1 };
  const resolving = {
    ...createChartStrategyTesterState(inputs, "workspace\u0000cell-1"),
    status: "RESOLVING" as const,
  };
  const queued = {
    ...resolving,
    status: "QUEUED" as const,
    activeRunId: "bt_queued",
  };
  const render = (runState: typeof resolving | typeof queued) => renderToStaticMarkup(
    <ChartStrategyTesterPanel
      cellScope="workspace\u0000cell-1"
      session={session}
      attachment={attachment}
      draftStore={new StrategyDraftStore(createMemoryStrategyDraftAdapter())}
      onAttachmentChange={() => undefined}
      onEntryStateChange={() => undefined}
      onRunRequest={() => undefined}
      runState={runState}
      resolution={null}
      sourceDiagnostics={[]}
      pendingDataDraftRevision={null}
      onPrepareData={() => undefined}
      onStopObserving={() => undefined}
      onResumeObserving={() => undefined}
      onSourceDirty={() => undefined}
      onClose={() => undefined}
    />,
  );

  assert.doesNotMatch(render(resolving), /data-testid="chart-strategy-stop-observing"/);
  assert.match(render(queued), /data-testid="chart-strategy-stop-observing"/);
});

test("a paused auto-run reason is visible and actionable without exposing Run identity", () => {
  const html = renderToStaticMarkup(
    <ChartStrategyTesterPanel
      cellScope="workspace\u0000cell-1"
      session={session}
      attachment={{ ...attachment, autoRun: true, fidelityPreference: "PRECISE" }}
      draftStore={new StrategyDraftStore(createMemoryStrategyDraftAdapter())}
      onAttachmentChange={() => undefined}
      onEntryStateChange={() => undefined}
      onRunRequest={() => undefined}
      runState={createChartStrategyTesterState({
        session,
        attachment: { ...attachment, autoRun: true, fidelityPreference: "PRECISE" },
        draftContentRevision: 1,
      }, "workspace\u0000cell-1")}
      resolution={null}
      sourceDiagnostics={[]}
      pendingDataDraftRevision={null}
      autoRunPauseReason="PRECISE_REQUIRES_MANUAL"
      onPrepareData={() => undefined}
      onStopObserving={() => undefined}
      onResumeObserving={() => undefined}
      onSourceDirty={() => undefined}
      onClose={() => undefined}
    />,
  );
  assert.match(html, /data-auto-run-pause="PRECISE_REQUIRES_MANUAL"/);
  assert.doesNotMatch(html, /bt_[A-Za-z0-9_-]+/);
});

test("panel height and active tab persist by cell scope without cross-cell copying", () => {
  const values = new Map<string, string>();
  const storage = {
    getItem(key: string) { return values.get(key) ?? null; },
    setItem(key: string, value: string) { values.set(key, value); },
  };
  saveChartStrategyPanelPreferences("workspace\u0000cell-1", {
    height: 444,
    activeTab: "trades",
  }, storage);
  assert.deepEqual(loadChartStrategyPanelPreferences("workspace\u0000cell-1", storage), {
    height: 444,
    activeTab: "trades",
  });
  assert.deepEqual(loadChartStrategyPanelPreferences("workspace\u0000cell-2", storage), {
    height: 383,
    activeTab: "script",
  });
});

test("an empty continuous chart can attach a strategy or restore its own saved settings", () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  const values = new Map<string, string>();
  const storage = {
    getItem(key: string) { return values.get(key) ?? null; },
    setItem(key: string, value: string) { values.set(key, value); },
  };
  Object.defineProperty(globalThis, "localStorage", { value: storage, configurable: true });
  try {
    const cellScope = "workspace\u0000cell-1";
    const saved = { ...attachment, parameters: { size: 20 }, rangeMode: "CUSTOM" as const, customRange: { startMs: 0, endMs: 60000 } };
    assert.equal(saveDetachedChartStrategy(cellScope, saved), true);
    saveChartStrategyPanelPreferences(cellScope, { height: 400, activeTab: "script", runMode: "LIVE_ONLY" });
    assert.deepEqual(loadDetachedChartStrategy(cellScope), saved);
    assert.equal(loadDetachedChartStrategy("workspace\u0000cell-2"), null);
    const html = renderToStaticMarkup(
      <ChartStrategyTesterPanel
        cellScope={cellScope}
        session={session}
        attachment={null}
        draftStore={new StrategyDraftStore(createMemoryStrategyDraftAdapter())}
        onAttachmentChange={() => undefined}
        onEntryStateChange={() => undefined}
        onRunRequest={() => undefined}
        runState={createChartStrategyTesterState(null, cellScope)}
        resolution={null}
        sourceDiagnostics={[]}
        pendingDataDraftRevision={null}
        onPrepareData={() => undefined}
        onStopObserving={() => undefined}
        onResumeObserving={() => undefined}
        onSourceDirty={() => undefined}
        onClose={() => undefined}
      />,
    );
    assert.match(html, /value="LIVE_ONLY" selected/);
    assert.ok(html.includes(t("continuous.restoreAttachment", { name: saved.displayName })));
    assert.ok(html.includes(t("chartTester.start.template")));
    assert.doesNotMatch(html, /data-continuous-account/);
  } finally {
    if (descriptor) Object.defineProperty(globalThis, "localStorage", descriptor);
    else Reflect.deleteProperty(globalThis, "localStorage");
  }
});

test("a selected research version defaults to history plus live in the target chart", () => {
  const initialization = {
    runId: "bt_selected",
    versionHash: `sha256:${"a".repeat(64)}`,
    outputMode: "SIGNAL" as const,
    warmupBars: 20,
  };
  const selected = {
    ...attachment,
    language: "python" as const,
    strategyDraftId: "returned-version",
    initialization: { ...initialization, preferredRunMode: "HISTORY_LIVE" as const },
  };
  const otherDraftPreference = { runMode: "LIVE_ONLY" as const, runModeDraftId: "existing-draft" };
  assert.equal(resolveChartStrategyRunMode({}, selected), "HISTORY_LIVE");
  assert.equal(resolveChartStrategyRunMode(otherDraftPreference, selected), "HISTORY_LIVE");
  assert.equal(resolveChartStrategyRunMode({ ...otherDraftPreference, runModeDraftId: "returned-version" }, selected), "LIVE_ONLY");
  assert.equal(resolveChartStrategyRunMode({ runModeDraftId: "returned-version" }, selected), "HISTORY");
  assert.equal(resolveChartStrategyRunMode(otherDraftPreference, { ...selected, initialization }), "LIVE_ONLY");
});
