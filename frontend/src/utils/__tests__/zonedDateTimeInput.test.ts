import assert from "node:assert/strict";
import test from "node:test";

import {
  formatZoneOffset,
  formatZonedDateTimeInput,
  isValidTimeZone,
  parseZonedDateTimeInput,
  zoneOffsetMs,
} from "../zonedDateTimeInput.js";

const iso = (timeMs: number | undefined) => (timeMs === undefined ? "" : new Date(timeMs).toISOString().slice(0, 19));

test("UTC input is unchanged", () => {
  assert.deepEqual(parseZonedDateTimeInput("2026-03-08T02:30:00", "UTC"), { timeMs: Date.UTC(2026, 2, 8, 2, 30), resolution: "exact" });
  assert.equal(formatZonedDateTimeInput(Date.UTC(2026, 2, 8, 2, 30), "UTC"), "2026-03-08T02:30:00");
  assert.equal(formatZoneOffset(Date.UTC(2026, 0, 1), "UTC"), "UTC");
});

test("a fixed-offset zone converts both ways", () => {
  const parsed = parseZonedDateTimeInput("2026-11-27T09:00", "Asia/Shanghai");
  assert.equal(iso(parsed?.timeMs), "2026-11-27T01:00:00");
  assert.equal(parsed?.resolution, "exact");
  assert.equal(formatZonedDateTimeInput(Date.UTC(2026, 10, 27, 1), "Asia/Shanghai"), "2026-11-27T09:00:00");
  assert.equal(formatZoneOffset(Date.UTC(2026, 10, 27), "Asia/Kathmandu"), "UTC+05:45");
});

test("daylight saving: New York spring-forward gap and fall-back overlap", () => {
  // 2026-03-08: 02:00 EST jumps to 03:00 EDT, so 02:30 never happens.
  assert.deepEqual(
    { ...parseZonedDateTimeInput("2026-03-08T02:30", "America/New_York"), at: iso(parseZonedDateTimeInput("2026-03-08T02:30", "America/New_York")?.timeMs) },
    { timeMs: Date.UTC(2026, 2, 8, 7, 30), resolution: "gap", at: "2026-03-08T07:30:00" },
  );
  assert.equal(formatZonedDateTimeInput(Date.UTC(2026, 2, 8, 7, 30), "America/New_York"), "2026-03-08T03:30:00");
  // Either side of the gap is exact and an hour of offset apart.
  assert.equal(iso(parseZonedDateTimeInput("2026-03-08T01:59:59", "America/New_York")?.timeMs), "2026-03-08T06:59:59");
  assert.equal(iso(parseZonedDateTimeInput("2026-03-08T03:00", "America/New_York")?.timeMs), "2026-03-08T07:00:00");
  assert.equal(formatZoneOffset(Date.UTC(2026, 2, 8, 6), "America/New_York"), "UTC−05:00");
  assert.equal(formatZoneOffset(Date.UTC(2026, 2, 8, 8), "America/New_York"), "UTC−04:00");

  // 2026-11-01: 02:00 EDT goes back to 01:00 EST, so 01:30 happens twice; the first one is used.
  const overlap = parseZonedDateTimeInput("2026-11-01T01:30", "America/New_York");
  assert.deepEqual(overlap, { timeMs: Date.UTC(2026, 10, 1, 5, 30), resolution: "overlap" });
  assert.equal(formatZonedDateTimeInput(Date.UTC(2026, 10, 1, 6, 30), "America/New_York"), "2026-11-01T01:30:00");
  assert.equal(parseZonedDateTimeInput("2026-11-01T02:30", "America/New_York")?.resolution, "exact");
});

test("daylight saving east of UTC: Berlin gap and overlap", () => {
  // 2026-03-29: 02:00 CET jumps to 03:00 CEST.
  const gap = parseZonedDateTimeInput("2026-03-29T02:15", "Europe/Berlin");
  assert.equal(gap?.resolution, "gap");
  assert.equal(formatZonedDateTimeInput(gap!.timeMs, "Europe/Berlin"), "2026-03-29T03:15:00");
  // 2026-10-25: 03:00 CEST goes back to 02:00 CET.
  const overlap = parseZonedDateTimeInput("2026-10-25T02:15", "Europe/Berlin");
  assert.deepEqual(overlap, { timeMs: Date.UTC(2026, 9, 25, 0, 15), resolution: "overlap" });
  assert.equal(zoneOffsetMs(overlap!.timeMs, "Europe/Berlin"), 2 * 3_600_000);
});

test("invalid values and zones are refused", () => {
  for (const value of ["", "2026-02-30T10:00", "2026-13-01T00:00", "2026-01-01 10:00", "x"]) {
    assert.equal(parseZonedDateTimeInput(value, "America/New_York"), null, value);
  }
  assert.equal(isValidTimeZone("America/New_York"), true);
  assert.equal(isValidTimeZone("Mars/Olympus"), false);
  assert.equal(parseZonedDateTimeInput("2026-01-01T00:00", "Mars/Olympus"), null);
  assert.equal(formatZonedDateTimeInput(-1, "UTC"), "");
});
