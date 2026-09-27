import assert from "node:assert/strict";
import test from "node:test";
import { KlineConsumerRecovery } from "../feed/klineConsumerRecovery.js";
import { SeriesDataFeed } from "../feed/seriesDataFeed.js";
import type { KlineApi, KlineFetchResult } from "../klineContracts.js";
import { epochSeconds } from "../../../test/testHelpers.js";

const series = { exchange: "binance", marketType: "spot", symbol: "BTCUSDT", interval: "1m" };
const held = [60, 120, 180].map((time) => ({ time: epochSeconds(time), close: 1, is_closed: true }));
const proof: KlineFetchResult = {
  data: held, complete: true, retryable: false, verified_contiguous: true,
  truncated: false, missing_ranges: [], all_rows_final: true, has_tail_gap: false,
  history_state: "ready",
};

function harness(read: () => Promise<KlineFetchResult>) {
  const calls: unknown[][] = [];
  const commits: number[][] = [];
  const api: KlineApi = {
    getMultiStreamUrl: () => "ws://test",
    fetchKlinesHistory: read, fetchKlinesBefore: read, fetchLatestKlines: read,
    fetchKlinesRange: (...args) => { calls.push(args); return read(); },
  };
  const feed = new SeriesDataFeed({
    api, getActiveSeries: () => series,
    commitMergedChartData: (_s, _i, rows) => { commits.push(rows.map((row) => Number(row.time))); },
  });
  return { feed, calls, commits };
}

test("gap recovery waits for subscribe acknowledgement and reloads the entire held range", async () => {
  const { feed, calls, commits } = harness(async () => proof);
  const recovery = new KlineConsumerRecovery();
  recovery.capture(feed, series, [...held, { time: epochSeconds(240), is_closed: false }]);
  await recovery.recover(feed, () => false);
  assert.equal(calls.length, 0);
  assert.equal(recovery.requiredFor("1m"), true);
  assert.equal(recovery.requiredFor("5m"), false);
  await recovery.recover(feed, () => true);
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0]?.slice(2, 4), [60, 180]);
  assert.deepEqual(commits, [[60, 120, 180]]);
  assert.equal(recovery.required, false);
});

const incompleteSnapshots: Array<[string, KlineFetchResult]> = [
  ["pending", { ...proof, complete: false, retryable: true }],
  ["unverified", { ...proof, verified_contiguous: false }],
  ["missing held row", { ...proof, data: [held[0]!, held[2]!] }],
];
for (const [name, result] of incompleteSnapshots) {
  test(`a ${name} snapshot cannot clear the recovery state`, async () => {
    const { feed } = harness(async () => result);
    const recovery = new KlineConsumerRecovery();
    recovery.capture(feed, series, held);
    await recovery.recover(feed, () => true);
    assert.equal(recovery.required, true);
  });
}

test("a second gap fences the old snapshot and coalesces concurrent recovery attempts", async () => {
  let finish!: (result: KlineFetchResult) => void;
  const work = new Promise<KlineFetchResult>((resolve) => { finish = resolve; });
  const { feed, calls, commits } = harness(() => work);
  const recovery = new KlineConsumerRecovery();
  recovery.capture(feed, series, held);
  const first = recovery.recover(feed, () => true);
  await new Promise<void>((resolve) => setImmediate(resolve));
  recovery.capture(feed, series, held);
  await recovery.recover(feed, () => true);
  assert.equal(calls.length, 1);
  finish(proof);
  await first;
  assert.equal(recovery.required, true);
  assert.deepEqual(commits, []);
  await recovery.recover(feed, () => true);
  assert.equal(recovery.required, false);
});

test("transport failure stays recoverable and a later verified snapshot succeeds", async () => {
  let fail = true;
  const { feed } = harness(async () => {
    if (fail) throw new Error("storage unavailable");
    return proof;
  });
  const recovery = new KlineConsumerRecovery();
  recovery.capture(feed, series, held);
  await recovery.recover(feed, () => true);
  assert.equal(recovery.required, true);
  fail = false;
  await recovery.recover(feed, () => true);
  assert.equal(recovery.required, false);
});
