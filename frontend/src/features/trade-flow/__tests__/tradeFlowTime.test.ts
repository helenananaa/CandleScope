import assert from "node:assert/strict";
import test from "node:test";
import { getLocale, setLocale } from "../../../i18n/index.js";
import { formatLastTradeTime, formatTapeTime } from "../tradeFlowTime.js";

// 2026-01-02 03:04:05.067 UTC: 12:04 in Tokyo, 22:04 the day before in New York.
const TRADE_MS = Date.UTC(2026, 0, 2, 3, 4, 5, 67);

function systemTime(value: number): string {
  return new Date(value).toLocaleTimeString("en-GB", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

test("tape times follow the chart timezone setting and keep milliseconds", () => {
  const previous = getLocale();
  try {
    setLocale("en");
    assert.equal(formatTapeTime(TRADE_MS, "UTC"), "03:04:05.067");
    assert.equal(formatTapeTime(TRADE_MS, "Asia/Tokyo"), "12:04:05.067");
    assert.equal(formatTapeTime(TRADE_MS, "America/New_York"), "22:04:05.067");
    // Tokyo and New York are 14 hours apart, so at least one is not the system zone.
    assert.notEqual(formatTapeTime(TRADE_MS, "Asia/Tokyo"), formatTapeTime(TRADE_MS, "America/New_York"));
  } finally {
    setLocale(previous);
  }
});

test("Local, no setting, or an unknown zone show system time instead of failing", () => {
  const previous = getLocale();
  try {
    setLocale("en");
    const local = `${systemTime(TRADE_MS)}.067`;
    assert.equal(formatTapeTime(TRADE_MS, "Local"), local);
    assert.equal(formatTapeTime(TRADE_MS), local);
    assert.equal(formatTapeTime(TRADE_MS, "Not/A_Zone"), local);
    assert.match(formatLastTradeTime(TRADE_MS, "Not/A_Zone"), /\d{2}:\d{2}:\d{2}/);
  } finally {
    setLocale(previous);
  }
});

test("the last-trade tooltip uses the same timezone", () => {
  const previous = getLocale();
  try {
    setLocale("en");
    assert.match(formatLastTradeTime(TRADE_MS, "UTC"), /02\/01\/2026, 03:04:05/);
    assert.match(formatLastTradeTime(TRADE_MS, "Asia/Tokyo"), /02\/01\/2026, 12:04:05/);
  } finally {
    setLocale(previous);
  }
});
