import assert from "node:assert/strict";
import test from "node:test";

import { listLocalDatasets, LocalKlineApi } from "./localDataApi.js";
import { toEpochSeconds } from "../market-data/marketDataTypes.js";


function jsonResponse(payload: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

function manifest() {
  return {
    schema_version: 1,
    dataset_id: "local-0123456789abcdef0123456789abcdef",
    data_epoch: `sha256:${"a".repeat(64)}`,
    name: "BTC sample",
    source: "local_dataset",
    symbol: "BTC-USDT",
    interval: "1m",
    timezone: "UTC",
    timestamp_semantics: "bar_open",
    rows: 2,
    first_open_ms: 1_704_067_200_000,
    last_open_ms: 1_704_067_260_000,
    all_rows_final: true,
    excluded_range_count: 0,
    sqlite_sha256: "b".repeat(64),
    imported_at: "2026-08-05T00:00:00+00:00",
  };
}

test("local dataset library validates manifests", async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => { globalThis.fetch = originalFetch; });
  let capturedUrl = "";
  globalThis.fetch = async (url) => {
    capturedUrl = String(url);
    return jsonResponse({ datasets: [manifest()], count: 1 });
  };

  const datasets = await listLocalDatasets();

  assert.equal(capturedUrl, "/api/v1/local/datasets");
  assert.equal(datasets[0]?.source, "local_dataset");
  assert.equal(datasets[0]?.rows, 2);
});

test("local kline adapter uses dataset-scoped HTTP and exposes no stream URL", async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => { globalThis.fetch = originalFetch; });
  let capturedUrl = "";
  globalThis.fetch = async (url) => {
    capturedUrl = String(url);
    return jsonResponse({
      source: "local_dataset",
      data: [{
        time: 1_704_067_200,
        open: 100,
        high: 102,
        low: 99,
        close: 101,
        volume: 10,
        is_closed: true,
      }],
      has_more: false,
      complete: true,
      retryable: false,
      history_state: "exhausted",
      terminal_reason: "dataset_boundary",
      missing_ranges: [],
      excluded_ranges: [],
    });
  };
  const api = new LocalKlineApi("local-0123456789abcdef0123456789abcdef");

  const result = await api.fetchKlinesHistory(
    "BTC-USDT",
    "1m",
    null,
    "local",
    "local",
    { countBack: 500 },
  );

  assert.match(capturedUrl, /^\/api\/v1\/local\/datasets\/local-[a-f0-9]+\/klines\/history\?/);
  assert.match(capturedUrl, /count_back=500/);
  assert.equal(result.data?.[0]?.time, toEpochSeconds(1_704_067_200));
  assert.equal(result.retryable, false);
  assert.equal(api.getMultiStreamUrl(), "");
});
