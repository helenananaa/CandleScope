import test from "node:test";
import assert from "node:assert/strict";
import { diagnosticLocation, nativeRunFeedback } from "../nativeDiagnostics.js";
import type { NativeRun } from "../nativeBacktestApi.js";
import { formatReportPercent } from "../nativeReportAnalytics.js";
test("engine diagnostics select the actual source location", () => {
  assert.deepEqual(diagnosticLocation("E_UNKNOWN_SYMBOL:Error:3:6: unknown symbol", "first\nsecond\nplot(missing)"), { line: 3, column: 6, offset: 18 });
  assert.equal(diagnosticLocation("Error:90:2: unknown", "short"), null);
  assert.equal(diagnosticLocation("unknown", "short"), null);
});
test("small nonzero drawdown is not displayed as zero", () => {
  assert.equal(formatReportPercent(0.001, "en"), "<0.01%");
  assert.equal(formatReportPercent(0, "en"), "0%");
  assert.equal(formatReportPercent(null, "en"), "—");
  assert.equal(formatReportPercent(1.234, "en"), "1.23%");
});

function run(state: string, error?: NativeRun["error"]): NativeRun {
  return { run_id: state, state, ...(error === undefined ? {} : { error }), created_at_ms: 0,
    runtime_identity: { engine: { package: "pine-compat-runtime", version: "0.4.1", code_sha256: "test" } } };
}
const failed = run("FAILED", { message: "native engine rejected the run",
  details: { diagnostics: [{ message: "PYNE_SYNTAX_ERROR: invalid syntax" }] } });
test("failed history retains its own status and nested diagnostics after a successful retry", () => {
  const feedback = nativeRunFeedback({ current: run("COMPLETED"), historical: failed, error: "", busy: false, needsData: false });
  assert.equal(feedback.status, "failed");
  assert.match(feedback.errorDetails, /PYNE_SYNTAX_ERROR: invalid syntax/);
});
test("successful history does not inherit a current failure or preparation error", () => {
  const feedback = nativeRunFeedback({ current: failed, historical: run("COMPLETED"), error: "request failed", busy: false,
    preparationState: "CANCELLED", needsData: true });
  assert.deepEqual(feedback, { status: "completed", errorDetails: "" });
});
test("cancelled and interrupted history stay distinct from the current successful result", () => {
  for (const [state, expected] of [["CANCELLED", "cancelled"], ["INTERRUPTED", "failed"]] as const) {
    const feedback = nativeRunFeedback({ current: run("COMPLETED"), historical: run(state), error: "", busy: false, needsData: false });
    assert.equal(feedback.status, expected);
  }
});
test("returning to current run restores current diagnostics and operation feedback", () => {
  const feedback = nativeRunFeedback({ current: failed, historical: null, error: "", busy: false, needsData: false });
  assert.equal(feedback.status, "failed");
  assert.match(feedback.errorDetails, /PYNE_SYNTAX_ERROR/);
  assert.deepEqual(nativeRunFeedback({ current: null, historical: null, error: "request failed", busy: false, needsData: false }),
    { status: "failed", errorDetails: "request failed" });
  assert.deepEqual(nativeRunFeedback({ current: null, historical: null, error: "", busy: true, needsData: false }),
    { status: "preparing", errorDetails: "" });
});
