import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  CHART_TIME_ZONE_MODE_KEY,
  chartTimeLabel,
  chartTimeZone,
  readChartTimeZoneMode,
  writeChartTimeZoneMode,
} from "../chartTimeZoneMode.js";

class MemoryStorage {
  readonly values = new Map<string, string>();
  getItem(key: string) { return this.values.get(key) ?? null; }
  setItem(key: string, value: string) { this.values.set(key, value); }
  removeItem(key: string) { this.values.delete(key); }
}

function withStorage<T>(storage: unknown, run: () => T): T {
  const previous = (globalThis as { localStorage?: unknown }).localStorage;
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: storage });
  try {
    return run();
  } finally {
    if (previous === undefined) delete (globalThis as { localStorage?: unknown }).localStorage;
    else Object.defineProperty(globalThis, "localStorage", { configurable: true, value: previous });
  }
}

test("Go to date stays UTC unless local time was chosen, and remembers the choice", () => {
  const storage = new MemoryStorage();
  withStorage(storage, () => {
    assert.equal(readChartTimeZoneMode(), "utc");
    writeChartTimeZoneMode("local");
    assert.equal(storage.getItem(CHART_TIME_ZONE_MODE_KEY), "local");
    assert.equal(readChartTimeZoneMode(), "local");
    storage.setItem(CHART_TIME_ZONE_MODE_KEY, "Mars/Olympus");
    assert.equal(readChartTimeZoneMode(), "utc");
  });
  withStorage({ getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } }, () => {
    assert.equal(readChartTimeZoneMode(), "utc");
    assert.doesNotThrow(() => writeChartTimeZoneMode("local"));
  });
  assert.equal(chartTimeZone("utc", "Asia/Shanghai"), "UTC");
  assert.equal(chartTimeZone("local", "Asia/Shanghai"), "Asia/Shanghai");
});

test("located times name their offset, which follows daylight saving", () => {
  assert.equal(chartTimeLabel(Date.UTC(2026, 10, 1, 5, 30), "America/New_York"), "2026-11-01 01:30:00 UTC−04:00");
  assert.equal(chartTimeLabel(Date.UTC(2026, 10, 1, 6, 30), "America/New_York"), "2026-11-01 01:30:00 UTC−05:00");
  assert.equal(chartTimeLabel(Date.UTC(2026, 10, 1, 6, 30), "UTC"), "2026-11-01 06:30:00 UTC");
});

test("the dialog labels its input with the zone and reports DST adjustments", () => {
  const source = readFileSync(new URL("../ChartTimeNavigationDialog.tsx", import.meta.url), "utf8");
  assert.match(source, /<SegmentedControl label=\{t\("chartTime\.zone"\)\}/);
  assert.match(source, /t\("chartTime\.inputZoned", \{ zone: localZone \}\) : t\("chartTime\.input"\)/);
  assert.match(source, /parseZonedDateTimeInput\(value, zone\)/);
  assert.match(source, /"chartTime\.gap"/);
  assert.match(source, /"chartTime\.overlap"/);
});
