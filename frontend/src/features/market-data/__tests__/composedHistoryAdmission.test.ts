import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { resolveComposedHistoryCapability, planComposedHistoryPage } from "../composedHistoryAdmission.js";
import { planInitialHistoryAdmission, planInitialHistoryCountBack } from "../useChartInitialLoad.js";

interface FixturePolicy { fields: string[]; schema_version: number; evidence: string[] }
interface FixtureCapability {
  exchange: string;
  markets: { market_type: string; calendar_id: string; timezone: string }[];
  channels: { history_composition?: FixturePolicy }[];
}
const raw = JSON.parse(readFileSync(new URL(
  "../../../../../docs/qa/mixed-history-viewport-127-20261114/capability.json", import.meta.url), "utf8")) as FixtureCapability;
function policy(value: FixtureCapability): FixturePolicy {
  const result = value.channels.find(channel => channel.history_composition)?.history_composition;
  assert.ok(result);
  return result;
}
const natives = ["1m", "5m", "15m", "1h", "4h", "1d"];
const resolve = (capability: unknown = raw, identity = {}) => resolveComposedHistoryCapability({
  exchange: "binance", marketType: "futures", identity, capability, nativeIntervals: natives,
});

test("real backend capability admits a bounded staged composed page and preserves ordinary admission", () => {
  const capability = resolve();
  assert.ok(capability);
  assert.deepEqual(planInitialHistoryAdmission("10007m", natives, false, capability), {
    historyCountBack: 406, viewportCountBack: 128, materializedOnly: false,
    compositionContract: "binance.usdm.trade-klines/base-utc/1",
  });
  assert.equal(planInitialHistoryCountBack("10007m", natives, false, capability), 406);
  assert.deepEqual(planInitialHistoryAdmission("45m", natives, false, capability),
    planInitialHistoryAdmission("45m", natives));
  assert.deepEqual(planInitialHistoryAdmission("10007m", natives), {
    historyCountBack: 500, viewportCountBack: 500, materializedOnly: true,
  });
});

test("admitted page budget covers every real prime phase on the qualified UTC grids", () => {
  const capability = resolve();
  assert.ok(capability);
  const page = planComposedHistoryPage("10007m", capability, 1500, 20_000);
  assert.ok(page);
  const widths = capability.sourceWidthsSeconds.map(width => width / 60);
  for (let index = 0; index < 1440; index++) {
    let cursor = index * 10007;
    const end = cursor + 10007;
    let rows = 0;
    while (cursor < end) {
      const width = widths.find(width => cursor % width === 0 && cursor + width <= end);
      assert.ok(width);
      cursor += width;
      rows++;
    }
    assert.equal(cursor, end);
    assert.ok(rows * (page.targetBars + 3) <= 16_384);
  }
  assert.equal(planComposedHistoryPage("10007m~a1~60000", capability, 1500, 20_000), null);
  assert.equal(planComposedHistoryPage("1M", capability, 1500, 20_000), null);
});

for (const identity of [{ providerId: "other" }, { venue: "other" }, { seriesVariant: "mark" },
  { priceAdjustment: "adjusted" }, { sessionVariant: "session" }, { volumeSemantics: "contracts" }]) {
  test(`a different series identity cannot inherit mixed source permission: ${JSON.stringify(identity)}`, () => {
    assert.equal(resolve(raw, identity), null);
  });
}

test("unsupported schemas, fields, calendars and markets retain the target-only escape hatch", () => {
  const clone = () => structuredClone(raw);
  for (const mutate of [
    (value: ReturnType<typeof clone>) => { value.exchange = "other"; },
    (value: ReturnType<typeof clone>) => { value.markets[1]!.calendar_id = "unknown.session"; },
    (value: ReturnType<typeof clone>) => { value.markets[1]!.timezone = "America/New_York"; },
    (value: ReturnType<typeof clone>) => { policy(value).fields.pop(); },
    (value: ReturnType<typeof clone>) => { policy(value).schema_version = 999; },
    (value: ReturnType<typeof clone>) => { policy(value).evidence = []; },
  ]) {
    const value = clone();
    mutate(value);
    const capability = resolve(value);
    assert.equal(capability, null);
    assert.equal(planInitialHistoryAdmission("10007m", natives, false, capability).materializedOnly, true);
  }
  assert.equal(resolveComposedHistoryCapability({ exchange: "binance", marketType: "spot",
    capability: raw, nativeIntervals: natives }), null);
});
