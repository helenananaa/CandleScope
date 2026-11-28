import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { chartTimeShortcutMessages } from "../../../i18n/catalogs/chartTimeShortcutMessages.js";
import {
  CHART_TIME_AMOUNT_SECONDS,
  CHART_TIME_LAST_VIEWED_KEY,
  CHART_TIME_RELATIVE_JUMPS,
  readLastViewed,
  relativeJumpTarget,
  RelativeJumpTracker,
  visibleCenterTimeMs,
  writeLastViewed,
} from "../chartTimeShortcuts.js";

function memoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
    values,
  };
}

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

test("rapid relative jumps add up from the pending target, and settle back to the view", () => {
  const tracker = new RelativeJumpTracker();
  const center = Date.UTC(2026, 10, 20, 12);
  const now = Date.UTC(2026, 10, 27);
  const first = relativeJumpTarget(tracker.base(center), -CHART_TIME_AMOUNT_SECONDS.day, now)!;
  const settleFirst = tracker.begin(first);
  // The view hasn't moved yet: the second click counts from the first target.
  const second = relativeJumpTarget(tracker.base(center), -CHART_TIME_AMOUNT_SECONDS.day, now)!;
  assert.equal(second, Date.UTC(2026, 10, 18, 12));
  const settleSecond = tracker.begin(second);
  settleFirst();
  assert.equal(tracker.base(center), second, "an older jump settling leaves the newer one pending");
  settleSecond();
  assert.equal(tracker.base(center), center);
  tracker.begin(second);
  tracker.reset();
  assert.equal(tracker.base(center), center, "a typed time or quick target ends the chain");
});

test("replay's ceiling is its revealed boundary, not now", () => {
  const boundary = Date.UTC(2024, 2, 1, 9);
  assert.equal(relativeJumpTarget(Date.UTC(2024, 2, 1, 6), CHART_TIME_AMOUNT_SECONDS.day, boundary), boundary);
});

test("last viewed survives a reload for the same slot and series only", () => {
  const storage = memoryStorage();
  writeLastViewed("ws\u0000cell-1", "BTCUSDT:1h", 1_700_000_000_000, storage);
  assert.equal(readLastViewed("ws\u0000cell-1", "BTCUSDT:1h", storage), 1_700_000_000_000);
  assert.equal(readLastViewed("ws\u0000cell-1", "ETHUSDT:1h", storage), null, "another series in the slot");
  assert.equal(readLastViewed("ws\u0000cell-2", "BTCUSDT:1h", storage), null, "another slot");
  writeLastViewed("ws\u0000cell-1", "ETHUSDT:1h", 1_700_000_360_000, storage);
  assert.equal(readLastViewed("ws\u0000cell-1", "BTCUSDT:1h", storage), null, "one entry per slot");
  for (let index = 0; index < 70; index += 1) writeLastViewed(`ws\u0000c${index}`, "k", index, storage);
  assert.equal((JSON.parse(storage.values.get(CHART_TIME_LAST_VIEWED_KEY)!) as unknown[]).length, 64, "bounded");
  assert.equal(readLastViewed("ws\u0000c69", "k", storage), 69);
  storage.setItem(CHART_TIME_LAST_VIEWED_KEY, "{not json");
  assert.equal(readLastViewed("ws\u0000c69", "k", storage), null);
  assert.equal(readLastViewed("a", "b", null), null);
});

test("the dates-hidden variant names no time in any language", () => {
  const hiddenKeys = ["chartTime.hiddenTitle", "chartTime.hiddenHint", "chartTime.moved", "chartTime.movedNearest", "chartTime.firstLoadedHidden", "chartTime.moving"] as const;
  for (const [locale, messages] of Object.entries(chartTimeShortcutMessages)) {
    for (const key of hiddenKeys) {
      assert.ok(messages[key]?.trim(), `${locale} ${key}`);
      assert.doesNotMatch(messages[key], /\{time\}/, `${locale} ${key}`);
    }
  }
  const dialog = readFileSync(new URL("../ChartTimeNavigationDialog.tsx", import.meta.url), "utf8");
  // No date field, zone or Go, and the time-bearing messages are swapped out.
  assert.match(dialog, /\{!hideDates && <>\s*<SegmentedControl/);
  assert.match(dialog, /\{!hideDates && <Button type="submit"/);
  assert.match(dialog, /if \(hideDates\) return;/);
  assert.match(dialog, /hideDates \? t\(own\.exact \? "chartTime\.moved" : "chartTime\.movedNearest"\)/);
  assert.match(dialog, /hideDates \? t\("chartTime\.firstLoadedHidden"\)/);
  assert.match(dialog, /hideDates \? undefined : t\("chartTime\.lastViewedAt"/);
});

test("the dialog offers the shortcuts only where a chart lends them, and both chart kinds do", () => {
  const dialog = readFileSync(new URL("../ChartTimeNavigationDialog.tsx", import.meta.url), "utf8");
  assert.match(dialog, /\{shortcuts && <>/);
  assert.match(dialog, /shortcuts\.jumpBy\(direction \* CHART_TIME_AMOUNT_SECONDS\[amount\]\)/);
  assert.match(dialog, /disabled=\{shortcuts\.lastViewedMs === null\}/);
  const cell = readFileSync(new URL("../../../app/LiveChartCell.tsx", import.meta.url), "utf8");
  assert.match(cell, /shortcuts=\{timeNavigation\.shortcuts\}/);
  const replay = readFileSync(new URL("../../replay/ReplayTrainingPageShell.tsx", import.meta.url), "utf8");
  assert.match(replay, /shortcuts=\{dateNavigation\.shortcuts\}/);
  const hook = readFileSync(new URL("../useChartTimeNavigation.ts", import.meta.url), "utf8");
  // Last viewed is recorded only after the chart actually moved.
  assert.match(hook, /result\.status === "located"\) remember\(before\)/);
  assert.match(hook, /relativeJumpTarget\(tracker\.base\(centerTimeMs\(\)\), seconds, ceilingMs \?\? Date\.now\(\)\)/);
});
