import assert from "node:assert/strict";
import test from "node:test";
import { KlineConsumerRecovery } from "../feed/klineConsumerRecovery.js";
import { SeriesDataFeed } from "../feed/seriesDataFeed.js";
import type { KlineApi, KlineFetchResult } from "../klineContracts.js";
import type { KlineBar } from "../marketDataTypes.js";
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
  const committedRows: KlineBar[][] = [];
  const api: KlineApi = {
    getMultiStreamUrl: () => "ws://test",
    fetchKlinesHistory: read, fetchKlinesBefore: read, fetchLatestKlines: read,
    fetchKlinesRange: (...args) => { calls.push(args); return read(); },
  };
  const feed = new SeriesDataFeed({
    api, getActiveSeries: () => series,
    commitMergedChartData: (_s, _i, rows) => {
      commits.push(rows.map((row) => Number(row.time)));
      committedRows.push(rows);
    },
  });
  return { feed, calls, commits, committedRows };
}

test("gap recovery waits for subscribe acknowledgement and reloads the entire held range", async () => {
  const { feed, calls, commits } = harness(async () => proof);
  const recovery = new KlineConsumerRecovery();
  recovery.capture(feed, series, held);
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

test("a disconnected forming row is read back even after it falls behind latest two", async () => {
  const forming = { time: epochSeconds(240), close: 1, volume: 2, is_closed: false };
  const final = { ...forming, close: 74444.5, volume: 4567.5, is_closed: true };
  const { feed, calls, committedRows } = harness(async () => ({ ...proof, data: [...held, final] }));
  const recovery = new KlineConsumerRecovery();
  recovery.capture(feed, series, [...held, forming]);
  await recovery.recover(feed, () => true);
  assert.deepEqual(calls[0]?.slice(2, 4), [60, 240]);
  assert.deepEqual(committedRows.at(-1)?.at(-1), final);
  assert.equal(recovery.required, false);
});

test("closing recovery cancels an in-flight readback before it commits", async () => {
  let finish!: (result: KlineFetchResult) => void;
  const { feed, commits } = harness(() => new Promise((resolve) => { finish = resolve; }));
  const recovery = new KlineConsumerRecovery();
  recovery.capture(feed, series, held);
  const work = recovery.recover(feed, () => true);
  await new Promise<void>((resolve) => setImmediate(resolve));
  recovery.close();
  finish(proof);
  await work;
  assert.deepEqual(commits, []);
  assert.equal(recovery.required, false);
});

test("a response omitting the disconnected forming row cannot clear recovery", async () => {
  const { feed } = harness(async () => proof);
  const recovery = new KlineConsumerRecovery();
  recovery.capture(feed, series, [...held, { time: epochSeconds(240), is_closed: false }]);
  await recovery.recover(feed, () => true);
  assert.equal(recovery.required, true);
});

test("resume without a new tick discovers the tail and verifies from the suspended row", async () => {
  const newer = [240, 300, 360].map((time) => ({ time: epochSeconds(time), close: time, is_closed: time < 360 }));
  let reads = 0;
  const { feed, calls } = harness(async () => {
    reads += 1;
    return { ...proof, data: reads === 1 ? newer.slice(-2) : newer, all_rows_final: false };
  });
  const recovery = new KlineConsumerRecovery();
  recovery.capture(feed, series, [{ time: epochSeconds(240), is_closed: false }], { discoverTail: true });
  await recovery.recover(feed, () => true);
  assert.equal(reads, 2);
  assert.deepEqual(calls[0]?.slice(2, 4), [240, 360]);
  assert.equal(recovery.required, false);
});

test("tail discovery does not commit or clear recovery when strict readback fails", async () => {
  let reads = 0;
  const { feed, commits } = harness(async () => {
    if (++reads === 1) return { ...proof, data: [{ time: epochSeconds(360), is_closed: false }] };
    throw new Error("HTTP 503");
  });
  const recovery = new KlineConsumerRecovery();
  recovery.capture(feed, series, held.slice(-1), { discoverTail: true });
  await recovery.recover(feed, () => true);
  assert.deepEqual(commits, []);
  assert.equal(recovery.required, true);
});

test("a repeated gap cannot forget an earlier forming obligation", async () => {
  const { feed, calls } = harness(async () => proof);
  const recovery = new KlineConsumerRecovery();
  recovery.capture(feed, series, [{ time: epochSeconds(120), is_closed: false }]);
  recovery.capture(feed, series, [{ time: epochSeconds(180), is_closed: true }]);
  await recovery.recover(feed, () => true);
  assert.deepEqual(calls[0]?.slice(2, 4), [120, 180]);
  assert.equal(recovery.required, false);
});

test("explicit navigation retires an old recovery demand before a new request can write", async () => {
  const { feed, calls, commits } = harness(async () => proof);
  const recovery = new KlineConsumerRecovery();
  recovery.capture(feed, series, held);
  feed.beginEpoch(series);
  await recovery.recover(feed, () => true);
  assert.deepEqual(calls, []);
  assert.deepEqual(commits, []);
  assert.equal(recovery.required, false);
});

test("a fresh gap after navigation does not revive the previous window demand", async () => {
  const { feed, calls } = harness(async () => proof);
  const recovery = new KlineConsumerRecovery();
  recovery.capture(feed, series, held.slice(0, 1));
  feed.beginEpoch(series);
  recovery.capture(feed, series, held.slice(-1));
  await recovery.recover(feed, () => true);
  assert.deepEqual(calls[0]?.slice(2, 4), [180, 180]);
  assert.equal(recovery.required, false);
});
