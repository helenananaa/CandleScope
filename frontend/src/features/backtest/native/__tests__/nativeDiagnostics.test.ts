import test from "node:test";
import assert from "node:assert/strict";
import { diagnosticLocation } from "../nativeDiagnostics.js";
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
