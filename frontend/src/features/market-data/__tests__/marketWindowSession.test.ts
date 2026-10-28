import assert from "node:assert/strict";
import test from "node:test";
import { MarketWindowRegistry } from "../window/marketWindowSession.js";
import { SharedKlineRequestCoordinator } from "../feed/sharedKlineRequestCoordinator.js";
import type { KlineApi, KlineFetchResult } from "../klineContracts.js";

const key = "binance-spot-BTCUSDT-1m";
const rows = (...times: number[]) => times.map((time) => ({ time, open: 1, high: 2, low: 0, close: 1, volume: 3 }));

test("same-series windows navigate and return live independently", () => {
  const workspace = new MarketWindowRegistry({ maxBars: 3 });
  const a = workspace.createWindow("a");
  const b = workspace.createWindow("b");
  const ta = a.prepareSelection(key);
  const tb = b.prepareSelection(key);
  a.activate(ta);
  b.activate(tb);
  for (const [session, token] of [[a, ta], [b, tb]] as const) {
    session.transact(token, () => {
      session.getOrCreate(key, { intervalSeconds: 60 });
      session.apply(key, { type: "replace", rows: rows(180, 240, 300) });
    });
  }
  const ar = a.get(key)!;
  const br = b.get(key)!;
  assert.notEqual(ar, br);
  a.transact(ta, () => a.apply(key, { type: "range", rows: rows(60, 120) }));
  assert.deepEqual(ar.snapshot().map((r) => r.time), [60, 120, 180]);
  assert.deepEqual(br.snapshot().map((r) => r.time), [180, 240, 300]);
  assert.equal(ar.rightTruncated, true);
  assert.equal(br.rightTruncated, false);
  b.transact(tb, () => b.apply(key, { type: "tick", row: rows(360)[0]! }));
  assert.equal(br.last()?.time, 360);
  b.transact(tb, () => b.apply(key, { type: "replace", rows: rows(360, 420, 480) }));
  assert.deepEqual(ar.snapshot().map((r) => r.time), [60, 120, 180]);
  a.close();
  a.transact(ta, () => a.apply(key, { type: "clear" }));
  b.transact(tb, () => b.apply(key, { type: "tick", row: rows(540)[0]! }));
  assert.equal(br.last()?.time, 540);
  assert.equal(workspace.entries().length, 1);
});

test("closing one window retains the shared HTTP lease and commits only to the surviving owner", async () => {
  const workspace = new MarketWindowRegistry();
  const a = workspace.createWindow("a");
  const b = workspace.createWindow("b");
  const ta = a.prepareSelection(key), tb = b.prepareSelection(key);
  a.activate(ta); b.activate(tb);
  let resolve!: (result: KlineFetchResult) => void;
  let signal!: AbortSignal;
  let calls = 0;
  const api = new SharedKlineRequestCoordinator({
    fetchKlinesHistory: (...args: Parameters<KlineApi["fetchKlinesHistory"]>) => {
      calls += 1;
      signal = args[5]!.signal!;
      return new Promise<KlineFetchResult>((done) => { resolve = done; });
    },
  } as KlineApi);
  const abortA = new AbortController();
  const requestA = api.fetchKlinesHistory("BTCUSDT", "1m", 1, "spot", "binance", { signal: abortA.signal });
  const requestB = api.fetchKlinesHistory("BTCUSDT", "1m", 1, "spot", "binance", {});
  await Promise.resolve();
  assert.equal(calls, 1);
  a.close(); abortA.abort();
  await assert.rejects(requestA, { name: "AbortError" });
  assert.equal(signal.aborted, false);
  resolve({ data: rows(60, 120) as NonNullable<KlineFetchResult["data"]> });
  const result = await requestB;
  b.transact(tb, () => {
    b.getOrCreate(key);
    b.apply(key, { type: "replace", rows: result.data! });
  });
  assert.equal(b.get(key)?.barCount, 2);
  assert.equal(api.diagnostics().physicalInflight, 0);
});

test("StrictMode cleanup/setup retains the owner, but final cleanup revokes and releases it", async () => {
  const workspace = new MarketWindowRegistry();
  const session = workspace.createWindow();
  const token = session.prepareSelection(key);
  session.activate(token);
  session.transact(token, () => session.getOrCreate(key));
  session.revoke(token);
  session.activate(token);
  await Promise.resolve();
  session.transact(token, () => session.apply(key, { type: "replace", rows: rows(60) }));
  assert.equal(workspace.entries().length, 1);
  session.revoke(token);
  await Promise.resolve();
  assert.equal(workspace.entries().length, 0);
  session.transact(token, () => assert.fail("released owner must reject late work"));
});

test("shared seeds retain provenance but require local history validation and have no array aliases", () => {
  const workspace = new MarketWindowRegistry();
  const a = workspace.createWindow(), b = workspace.createWindow();
  const ta = a.prepareSelection(key), tb = b.prepareSelection(key);
  a.activate(ta); b.activate(tb);
  a.transact(ta, () => {
    a.getOrCreate(key);
    a.apply(key, { type: "replace", rows: rows(60, 120) });
    a.touchMeta(key, { historyComplete: true, historyValidatedCountBack: 2 });
  });
  b.transact(tb, () => b.getOrCreate(key));
  const ar = a.get(key)!, br = b.get(key)!;
  assert.notEqual(ar.snapshot(), br.snapshot());
  assert.notEqual(ar.first(), br.first());
  assert.equal(br.commitState.historyComplete, false);
  assert.equal((br.commitState.seed as Record<string, unknown>).windowId, a.windowId);
  a.transact(ta, () => a.apply(key, { type: "tick", row: { ...rows(120)[0]!, close: 2 } }));
  assert.equal(br.last()?.close, 1);
});

test("subscribers see data, proof and revisions from one commit, including queued reentry", () => {
  const workspace = new MarketWindowRegistry();
  const session = workspace.createWindow("a");
  const token = session.prepareSelection(key);
  session.activate(token);
  session.transact(token, () => session.getOrCreate(key));
  const reader = session.get(key)!;
  const seen: unknown[] = [];
  reader.subscribe(() => {
    seen.push([reader.last()?.time, reader.commitState.historyComplete, reader.commitState.dataRevision, reader.version]);
    if (reader.barCount === 1) {
      session.transact(token, () => session.apply(key, { type: "range", rows: rows(120) }));
      assert.equal(reader.barCount, 1, "reentrant actions wait for every subscriber");
    }
  });
  session.transact(token, () => {
    session.apply(key, { type: "replace", rows: rows(60) });
    session.touchMeta(key, { historyComplete: true });
  });
  assert.deepEqual(seen, [[60, true, 1, 1], [120, true, 2, 2]]);
  const dataVersion = reader.version;
  session.transact(token, () => session.touchMeta(key, { historyComplete: false }));
  assert.equal(reader.version, dataVersion);
  assert.equal(reader.commitState.commitRevision, 3);
  assert.equal(reader.commitState.historyComplete, false);
});

test("selection ABA and closed-window work lose write permission; readers cannot mutate aliases", () => {
  const session = new MarketWindowRegistry().createWindow("a");
  const old = session.prepareSelection(key);
  session.activate(old);
  session.transact(old, () => {
    session.getOrCreate(key);
    session.apply(key, { type: "replace", rows: rows(60) });
  });
  session.activate(session.prepareSelection("eth"));
  const current = session.prepareSelection(key);
  session.activate(current);
  session.transact(old, () => session.apply(key, { type: "clear" }));
  const reader = session.get(key)!;
  assert.equal(reader.barCount, 1);
  assert.equal("applyTick" in reader, false);
  assert.throws(() => reader.snapshot().push(rows(120)[0] as never), TypeError);
  assert.throws(() => { reader.snapshot()[0]!.close = 999; }, TypeError);
  const stable = reader.capture();
  const hot = reader.snapshot();
  const times = reader.timeSet();
  assert.equal(reader.timeSet(), times, "reader must not churn projection dependencies");
  session.transact(current, () => session.apply(key, { type: "tick", row: { ...rows(60)[0]!, close: 2 } }));
  assert.equal(reader.snapshot(), hot, "tail updates retain the O(1) reader path");
  assert.equal(reader.timeSet(), times, "same-time ticks retain axis identity");
  assert.equal((times as unknown as Set<number>).add, undefined);
  assert.equal(stable.rows[0]?.close, 1);
  assert.equal(reader.last()?.close, 2);
  session.revoke(current);
  session.transact(current, () => session.apply(key, { type: "clear" }));
  assert.equal(reader.barCount, 1);
});

test("nested row fields and proof have no mutable input or reader aliases", () => {
  const session = new MarketWindowRegistry().createWindow();
  const token = session.prepareSelection(key);
  session.activate(token);
  const input = { ...rows(60)[0]!, order_flow: { volume_delta_base: 4 } };
  const proof = { coverage: { from: 60, to: 60 }, missingRanges: [{ from: 0, to: 0 }] };
  session.transact(token, () => {
    session.getOrCreate(key);
    session.apply(key, { type: "replace", rows: [input] });
    session.touchMeta(key, proof);
  });
  const reader = session.get(key)!;
  input.order_flow.volume_delta_base = 999;
  proof.coverage.from = 999;
  assert.equal(reader.first()?.order_flow?.volume_delta_base, 4);
  assert.equal((reader.commitState.coverage as { from: number }).from, 60);
  assert.throws(() => { reader.first()!.order_flow!.volume_delta_base = 999; }, TypeError);
  assert.throws(() => { (reader.commitState.coverage as { from: number }).from = 999; }, TypeError);
});
