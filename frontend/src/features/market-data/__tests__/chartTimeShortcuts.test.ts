import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  CHART_TIME_AMOUNT_SECONDS,
  CHART_TIME_RELATIVE_JUMPS,
  relativeJumpTarget,
  visibleCenterTimeMs,
} from "../chartTimeShortcuts.js";

test("the view centre comes from the visible time range in seconds", () => {
  assert.equal(visibleCenterTimeMs({ from: 1_700_000_000, to: 1_700_003_600 }), 1_700_001_800_000);
  assert.equal(visibleCenterTimeMs(null), null);
  assert.equal(visibleCenterTimeMs({ from: "x", to: 3 }), null);
  assert.equal(visibleCenterTimeMs({ from: { year: 2026 }, to: 3 }), null);
});

test("relative jumps move the centre by whole hours, days and weeks, and never past now", () => {
  const center = Date.UTC(2026, 10, 20, 12);
  const now = Date.UTC(2026, 10, 27, 8);
  assert.equal(relativeJumpTarget(center, -CHART_TIME_AMOUNT_SECONDS.day, now), Date.UTC(2026, 10, 19, 12));
  assert.equal(relativeJumpTarget(center, CHART_TIME_AMOUNT_SECONDS.hour, now), Date.UTC(2026, 10, 20, 13));
  assert.equal(relativeJumpTarget(center, -CHART_TIME_AMOUNT_SECONDS.week, now), Date.UTC(2026, 10, 13, 12));
  assert.equal(relativeJumpTarget(center, CHART_TIME_AMOUNT_SECONDS.week, now), now, "clamped to now");
  assert.equal(relativeJumpTarget(null, 3600, now), null);
  assert.equal(relativeJumpTarget(1000, -3600, now), null, "before the epoch");
  assert.deepEqual(CHART_TIME_RELATIVE_JUMPS.map(({ amount, direction }) => `${direction < 0 ? "-" : "+"}${amount}`),
    ["-week", "-day", "-hour", "+hour", "+day", "+week"]);
});

test("the dialog offers the shortcuts only where a chart lends them, and the live chart does", () => {
  const dialog = readFileSync(new URL("../ChartTimeNavigationDialog.tsx", import.meta.url), "utf8");
  assert.match(dialog, /\{shortcuts && <>/);
  assert.match(dialog, /shortcuts\.jumpBy\(direction \* CHART_TIME_AMOUNT_SECONDS\[amount\]\)/);
  assert.match(dialog, /disabled=\{shortcuts\.lastViewedMs === null\}/);
  const cell = readFileSync(new URL("../../../app/LiveChartCell.tsx", import.meta.url), "utf8");
  assert.match(cell, /shortcuts=\{timeNavigation\.shortcuts\}/);
  const hook = readFileSync(new URL("../useChartTimeNavigation.ts", import.meta.url), "utf8");
  // Last viewed is recorded only after the chart actually moved, and resets with the market.
  assert.match(hook, /result\.status === "located"\) setLastViewedMs\(before\)/);
  assert.match(hook, /useEffect\(\(\) => \{ setLastViewedMs\(null\); \}, \[sessionKey, workspaceId, cellId\]\)/);
});
