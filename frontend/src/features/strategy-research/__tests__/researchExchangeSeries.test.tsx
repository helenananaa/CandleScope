import { LOCALES, loadLocaleCatalog } from "../../../i18n/registry.js";
import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { t } from "../../../i18n/index.js";
import {
  isCapabilityAvailable, ordinarySourceLabel, parseResearchSourceRef, projectResearchCapabilities, ResearchDataError,
} from "../../research-data/researchDataSourceModel.js";
import { RESEARCH_SOURCE_SCHEMA, type ExchangeSeriesSourceRefV1 } from "../../research-data/researchDataTypes.js";
import { ResearchDataDrawer } from "../../research-data/ResearchDataDrawer.js";
import { researchResultMatchesSource, sessionFromResearchSource } from "../useStrategyResearchRun.js";
import type { ChartStrategyResultBundle } from "../../backtest/chart-tester/chartStrategyResultCache.js";

test.before(async () => { await Promise.all(LOCALES.map(loadLocaleCatalog)); });

const START = Date.UTC(2026, 10, 1), END = Date.UTC(2026, 10, 8);
const series: ExchangeSeriesSourceRefV1 = {
  schemaVersion: RESEARCH_SOURCE_SCHEMA, kind: "EXCHANGE_SERIES",
  exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1h", startMs: START, endMs: END,
};

test("exchange history is a research source of its own: a series and a fixed range, kept across restarts", () => {
  assert.deepEqual(parseResearchSourceRef(JSON.parse(JSON.stringify(series))), series);
  for (const broken of [{ ...series, startMs: END }, { ...series, endMs: undefined }, { ...series, startMs: 1.5 }, { ...series, symbol: "" }]) {
    assert.throws(() => parseResearchSourceRef(broken), ResearchDataError);
  }
});

test("exchange history prepares missing bars in the live service and is unavailable offline", () => {
  const live = projectResearchCapabilities({ sourceKind: "EXCHANGE_SERIES", runtimeMode: "LIVE" });
  assert.equal(isCapabilityAvailable(live, "onlineBackfill"), true);
  assert.equal(isCapabilityAvailable(live, "importNewData"), false);
  const offline = projectResearchCapabilities({ sourceKind: "EXCHANGE_SERIES", runtimeMode: "LOCAL_OFFLINE" });
  assert.equal(isCapabilityAvailable(offline, "viewKlines"), false);
  assert.equal(isCapabilityAvailable(offline, "barApprox"), false);
  for (const locale of LOCALES) assert.notEqual(ordinarySourceLabel("EXCHANGE_SERIES", locale), "researchSource.exchangeSeries");
});

function result(start: number, end: number, exchange = "binance"): ChartStrategyResultBundle {
  return { chart: { symbol: "BTCUSDT", interval: "1h" }, run: {}, config: { exchange, market_type: "spot", start_time_ms: start, end_time_ms: end } } as unknown as ChartStrategyResultBundle;
}

test("a result belongs to the exchange history when it ran that series inside the chosen range", () => {
  const session = sessionFromResearchSource(series, null, null);
  assert.deepEqual(session, { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1h" });
  assert.equal(researchResultMatchesSource(result(START + 3_600_000, END - 1), series, session), true, "warm-up may narrow the range");
  assert.equal(researchResultMatchesSource(result(START - 3_600_000, END - 1), series, session), false, "an earlier range is another input");
  assert.equal(researchResultMatchesSource(result(START, END - 1, "okx"), series, session), false);
});

test("the data drawer offers exchange history beside the library and shows its form when chosen", () => {
  const props = { open: true, runtimeMode: "LIVE" as const, capabilities: null, settings: {} as never, events: [],
    availableKinds: ["IMPORTED_DATASET", "EXCHANGE_SERIES"] as Array<"IMPORTED_DATASET" | "EXCHANGE_SERIES">,
    onSelectKind: () => undefined, onClose: () => undefined };
  const html = renderToStaticMarkup(<ResearchDataDrawer {...props} selectedKind="EXCHANGE_SERIES" exchangeSeries={<p data-testid="series-form" />} />);
  assert.match(html, /data-testid="research-source-card-EXCHANGE_SERIES"[^>]*aria-pressed="true"|aria-pressed="true"[^>]*data-testid="research-source-card-EXCHANGE_SERIES"/);
  assert.match(html, /data-testid="series-form"/);
  assert.ok(html.includes(t("researchSource.exchangeSeries")));
  const offline = renderToStaticMarkup(<ResearchDataDrawer {...props} runtimeMode="LOCAL_OFFLINE" selectedKind="IMPORTED_DATASET" />);
  assert.match(offline, /disabled=""[^>]*data-testid="research-source-card-EXCHANGE_SERIES"|data-testid="research-source-card-EXCHANGE_SERIES"[^>]*disabled=""/);
});

test("with exchange history the run settings do not offer a second date range", async () => {
  const { StrategyConditionsEditor } = await import("../../backtest/chart-tester/StrategyConditionsEditor.js");
  const settings = { parameters: {}, fidelityPreference: "FAST" as const, rangeMode: "CUSTOM" as const, customRange: { startMs: START, endMs: END } };
  const fixed = renderToStaticMarkup(<StrategyConditionsEditor settings={settings} marketType="spot" rangeFixed onChange={() => undefined} />);
  assert.ok(!fixed.includes(t("chartTester.settings.date")));
  const free = renderToStaticMarkup(<StrategyConditionsEditor settings={settings} marketType="spot" onChange={() => undefined} />);
  assert.ok(free.includes(t("chartTester.settings.date")));
});
