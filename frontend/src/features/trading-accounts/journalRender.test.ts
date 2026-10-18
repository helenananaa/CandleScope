import assert from "node:assert/strict";
import test from "node:test";
import { getLocale, setLocale } from "../../i18n/index.js";
import { linkSuggestionLabel, planLevelParts, planLevels } from "./journalRender.js";
import { formatDateTime } from "./tradingFormat.js";
import type { LinkSuggestion } from "./tradingTypes.js";

const CREATED = Date.UTC(2026, 9, 17, 14, 32, 10);

function suggestion(overrides: Partial<LinkSuggestion>): LinkSuggestion {
  return {
    id: "je_1", kind: "note", createdAtMs: CREATED, symbol: "BTCUSDT", tradeId: null,
    entryPrice: null, stopPrice: null, targetPrice: null, riskUsdt: null, direction: null,
    ...overrides,
  };
}

test("link suggestions in the same minute differ by their planned levels", () => {
  const previous = getLocale();
  try {
    setLocale("en");
    const time = formatDateTime(CREATED);
    const long = linkSuggestionLabel(suggestion({
      entryPrice: "82100", stopPrice: "81000", targetPrice: "84000", riskUsdt: "25", direction: "long",
    }));
    const short = linkSuggestionLabel(suggestion({ id: "je_2", entryPrice: "82100.5", stopPrice: "83000", direction: "short" }));
    assert.equal(long, `Link plan from ${time} · Long · entry 82,100 · stop 81,000 · target 84,000 · risk 25.00`);
    assert.equal(short, `Link plan from ${time} · Short · entry 82,100.5 · stop 83,000`);
    assert.equal(linkSuggestionLabel(suggestion({})), `Link plan from ${time}`);
  } finally {
    setLocale(previous);
  }
});

test("plan levels are read from fields as the backend reads them", () => {
  assert.deepEqual(planLevels({ entryPrice: " 82100.50 ", stopPrice: "81000", targetPrice: "84000", riskUsdt: "25" }), {
    entryPrice: "82100.5", stopPrice: "81000", targetPrice: "84000", riskUsdt: "25", direction: "long",
  });
  assert.deepEqual(planLevels({ entryPrice: "82,100", stopPrice: "", targetPrice: "0x10", riskUsdt: "abc" }), {
    entryPrice: null, stopPrice: null, targetPrice: null, riskUsdt: null, direction: null,
  });
  assert.deepEqual(planLevels({ entryPrice: "0.00000012300", stopPrice: "+1.2e-7", targetPrice: "100." }), {
    entryPrice: "0.000000123", stopPrice: "1.2e-7", targetPrice: "100", riskUsdt: null, direction: "long",
  });
  assert.equal(planLevels({ entryPrice: "82100", stopPrice: "83000" }).direction, "short");
  assert.equal(planLevels({ entryPrice: "82100", targetPrice: "80000" }).direction, "short");
  // Stop and target on the same side, levels at entry, or no entry: unclear.
  assert.equal(planLevels({ entryPrice: "82100", stopPrice: "81000", targetPrice: "81500" }).direction, null);
  assert.equal(planLevels({ entryPrice: "82100", stopPrice: "82100" }).direction, null);
  assert.equal(planLevels({ stopPrice: "81000", targetPrice: "84000" }).direction, null);
});

test("plan level parts leave out empty levels", () => {
  const previous = getLocale();
  try {
    setLocale("en");
    assert.deepEqual(planLevelParts(planLevels({ entryPrice: "82100", riskUsdt: "25" })), ["entry 82,100", "risk 25.00"]);
    assert.deepEqual(planLevelParts(planLevels({})), []);
  } finally {
    setLocale(previous);
  }
});
