import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { t } from "../../../i18n/index.js";
import { nativeRunFeedback, type NativeFeedbackStatus } from "../../backtest/native/nativeDiagnostics.js";
import type { NativeRun } from "../../backtest/native/nativeBacktestApi.js";
import { StrategyResearchShell } from "../StrategyResearchShell.js";
import type { ChartStrategyTesterStatus } from "../../backtest/chart-tester/chartStrategyTesterState.js";

function footer(nativeStatus?: NativeFeedbackStatus, hasData = true, hostStatus?: ChartStrategyTesterStatus) {
  const html = renderToStaticMarkup(<StrategyResearchShell visualState="completed" nativeStatus={nativeStatus} hostStatus={hostStatus}
    source={hasData ? { schemaVersion: "candlescope.research-source/1", kind: "IMPORTED_DATASET", datasetId: "fixture", dataEpoch: "sha256:fixture", interval: "1m" } : null}
    libraryOpen={false} currentChartEnabled={false} onOpenLibrary={() => {}} onSelectCurrentChart={() => {}}
    pageExportRef={null} header={{}} runtimeMode="LIVE" intervalSelector={null} toolbar={null} exportOverlay={null}
    drawer={null} chart={null} analysis={null} script={null} result={null} extraSurfaces={null} />);
  return html.match(/<footer[^>]*data-testid="strategy-research-status"[^>]*>(.*?)<\/footer>/)?.[1];
}

test("selected failed native history overrides an earlier completed host run in the page footer", () => {
  const current = { state: "COMPLETED" } as NativeRun;
  const historical = { state: "FAILED", error: { message: "PYNE_SYNTAX_ERROR", details: {} } } as NativeRun;
  const feedback = nativeRunFeedback({ current, historical, error: "", busy: false, needsData: false });
  assert.equal(footer(feedback.status), t("strategy.status", { state: t("strategyReview.status.failed") }));
  assert.notEqual(footer(feedback.status), footer());
});

test("host execution state overrides a retained completed result", () => {
  for (const [status, key] of [
    ["RESOLVING", "chartTester.status.resolving"], ["QUEUED", "chartTester.status.queued"],
    ["RUNNING", "chartTester.status.running"], ["FAILED", "chartTester.status.failed"],
    ["NEEDS_DATA", "chartTester.status.needs_data"], ["UNSUPPORTED", "chartTester.status.unsupported"],
    ["STALE", "chartTester.status.stale"],
  ] as const) {
    assert.equal(footer(undefined, true, status), t("strategy.status", { state: t(key) }));
    assert.notEqual(footer(undefined, true, status), footer());
  }
  assert.equal(footer("running", true, "FAILED"), t("strategy.status", { state: t("strategyReview.status.running") }));
  assert.equal(footer(undefined, false, "FAILED"), t("strategy.status", { state: t("research.source.none") }));
});

test("native running, canceled and interrupted views cannot inherit completed footer status", () => {
  for (const state of ["RUNNING", "CANCELLED", "INTERRUPTED"] as const) {
    const feedback = nativeRunFeedback({ current: { state: "COMPLETED" } as NativeRun, historical: { state } as NativeRun,
      error: "", busy: false, needsData: false });
    assert.equal(footer(feedback.status), t("strategy.status", { state: t(`strategyReview.status.${feedback.status}`) }));
    assert.notEqual(footer(feedback.status), footer());
  }
});

test("host mode and an empty research source retain their own status", () => {
  assert.equal(footer(), t("strategy.status", { state: t("chartTester.status.completed") }));
  assert.equal(footer("failed", false), t("strategy.status", { state: t("research.source.none") }));
});
