import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ChartLoadingStatus } from "../ChartLoadingStatus.js";
import { SeriesWindowStore } from "../../features/market-data/window/seriesWindowStore.js";
import { asSeriesKey } from "../../features/market-data/marketDataTypes.js";

test("pending history reveals a rendered live tail without changing loading or history proof", () => {
  const key = asSeriesKey("binance:futures:BTCUSDT:10007m");
  const store = new SeriesWindowStore({ seriesKey: key });
  store.replace([{ time: 600420, open: 1, high: 2, low: 1, close: 2 }]);
  const meta = { seriesKey: key, historyComplete: false, indicatorWindowDeferred: true };
  const props = { loading: true, text: "Loading history", datasetKey: key, dataMeta: meta,
    seriesStore: store, paintedDatasetKey: key };
  const before = store.snapshot();
  const html = renderToStaticMarkup(<ChartLoadingStatus {...props} />);
  assert.match(html, /loading-overlay--partial/);
  assert.match(html, /role="status"/);
  assert.match(html, /Loading history/);
  assert.equal(props.loading, true);
  assert.equal(meta.historyComplete, false);
  assert.equal(meta.indicatorWindowDeferred, true);
  assert.equal(store.snapshot(), before);
  assert.equal(renderToStaticMarkup(<ChartLoadingStatus {...props} loading={false} />), "");

  // Empty replacement/correction must return to the opaque loading state.
  store.replace([]);
  assert.doesNotMatch(renderToStaticMarkup(<ChartLoadingStatus {...props} />), /loading-overlay--partial/);
});

test("session transitions never expose outgoing or unrendered data under the incoming label", () => {
  const oldKey = asSeriesKey("binance:futures:BTCUSDT:89m");
  const key = asSeriesKey("binance:futures:ETHUSDT:97m");
  const store = new SeriesWindowStore({ seriesKey: key });
  store.replace([{ time: 600420, close: 2 }]);
  const props = { loading: true, text: "Loading history", datasetKey: key,
    dataMeta: { seriesKey: key }, seriesStore: store, paintedDatasetKey: key };
  for (const override of [
    { dataMeta: { seriesKey: oldKey, optimistic: true } },
    { dataMeta: { seriesKey: key, optimistic: true } },
    { dataMeta: { seriesKey: oldKey } },
    { seriesStore: new SeriesWindowStore({ seriesKey: oldKey }) },
    { paintedDatasetKey: oldKey },
    { paintedDatasetKey: null },
    { datasetKey: null },
    { dataMeta: null },
  ]) {
    const html = renderToStaticMarkup(<ChartLoadingStatus {...props} {...override} />);
    assert.match(html, /class="loading-overlay"/);
    assert.doesNotMatch(html, /loading-overlay--partial/);
  }
});
