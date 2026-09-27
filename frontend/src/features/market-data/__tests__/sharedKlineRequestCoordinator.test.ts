import assert from "node:assert/strict";
import test from "node:test";

import type { KlineApi, KlineFetchResult } from "../klineContracts.js";
import { SharedKlineRequestCoordinator } from "../feed/sharedKlineRequestCoordinator.js";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, reject, resolve };
}

function fakeApi(
  request: (signal: AbortSignal) => Promise<KlineFetchResult>,
  calls: { value: number },
): KlineApi {
  const run = (...args: unknown[]) => {
    calls.value += 1;
    const options = args.at(-1) as { signal: AbortSignal };
    return request(options.signal);
  };
  return {
    fetchKlinesHistory: run as KlineApi["fetchKlinesHistory"],
    fetchKlinesBefore: run as KlineApi["fetchKlinesBefore"],
    fetchKlinesRange: run as KlineApi["fetchKlinesRange"],
    fetchLatestKlines: run as KlineApi["fetchLatestKlines"],
    getMultiStreamUrl: () => "ws://example/stream",
  };
}

const result: KlineFetchResult = { data: [] };

test("exact history requests join one physical request and retain independent callers", async () => {
  const work = deferred<KlineFetchResult>();
  const calls = { value: 0 };
  const coordinator = new SharedKlineRequestCoordinator(fakeApi(() => work.promise, calls));

  const first = coordinator.fetchKlinesHistory(
    "BTCUSDT", "1m", 7, "futures", "binance", {
      countBack: 500,
      demandScope: "chart:a",
      demandGeneration: 9,
    },
  );
  const second = coordinator.fetchKlinesHistory(
    "btcusdt", "1m", 7, "futures", "BINANCE", {
      countBack: 500,
      demandScope: "chart:a",
      demandGeneration: 9,
    },
  );
  await Promise.resolve();
  assert.equal(calls.value, 1);
  assert.deepEqual(coordinator.diagnostics(0), {
    completedPhysical: 0,
    joinedLogical: 1,
    logicalInflight: 2,
    physicalInflight: 1,
    requests: [{
      ageMs: 0,
      consumers: 2,
      key: '["history","binance","futures","BTCUSDT","1m",7,500,null,null,"chart:a",9]',
      kind: "history",
    }],
    totalLogical: 2,
    totalPhysical: 1,
  });

  work.resolve(result);
  assert.equal(await first, result);
  assert.equal(await second, result);
  assert.equal(coordinator.diagnostics().physicalInflight, 0);
  assert.equal(coordinator.diagnostics().completedPhysical, 1);
});

test("one logical abort does not cancel a physical request still owned by another Cell", async () => {
  const work = deferred<KlineFetchResult>();
  const calls = { value: 0 };
  const physicalSignal: { current?: AbortSignal } = {};
  const coordinator = new SharedKlineRequestCoordinator(fakeApi((signal) => {
    physicalSignal.current = signal;
    return work.promise;
  }, calls));
  const firstAbort = new AbortController();
  const secondAbort = new AbortController();
  const first = coordinator.fetchKlinesBefore(
    "BTCUSDT", "5m", 100 as never, 500, "spot", "binance", { signal: firstAbort.signal },
  );
  const second = coordinator.fetchKlinesBefore(
    "BTCUSDT", "5m", 100 as never, 500, "spot", "binance", { signal: secondAbort.signal },
  );
  await Promise.resolve();

  firstAbort.abort();
  await assert.rejects(first, (error: unknown) => (error as Error).name === "AbortError");
  assert.equal(physicalSignal.current?.aborted, false);
  assert.equal(coordinator.diagnostics().logicalInflight, 1);

  work.resolve(result);
  assert.equal(await second, result);
});

test("the physical request aborts when its final logical owner leaves", async () => {
  const calls = { value: 0 };
  const physicalSignal: { current?: AbortSignal } = {};
  const coordinator = new SharedKlineRequestCoordinator(fakeApi((signal) => {
    physicalSignal.current = signal;
    return new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(new Error("physical-abort")), { once: true });
    });
  }, calls));
  const owner = new AbortController();
  const request = coordinator.fetchLatestKlines(
    "ETHUSDT", "1m", 2, "futures", "binance", "poll", { signal: owner.signal },
  );
  await Promise.resolve();
  owner.abort();
  await assert.rejects(request, (error: unknown) => (error as Error).name === "AbortError");
  assert.equal(physicalSignal.current?.aborted, true);
  assert.equal(coordinator.diagnostics().physicalInflight, 0);
});

test("request semantics that can change rows do not join", async () => {
  const calls = { value: 0 };
  const coordinator = new SharedKlineRequestCoordinator(fakeApi(async () => result, calls));
  await Promise.all([
    coordinator.fetchKlinesRange("BTCUSDT", "1m", 1 as never, 2 as never, "spot", "binance", { repair: "async" }),
    coordinator.fetchKlinesRange("BTCUSDT", "1m", 1 as never, 2 as never, "spot", "binance", { repair: "none" }),
  ]);
  assert.equal(calls.value, 2);
});

test("latest repair policy and demand generation are part of shared request identity", async () => {
  const calls = { value: 0 };
  const coordinator = new SharedKlineRequestCoordinator(fakeApi(async () => result, calls));
  await Promise.all([
    coordinator.fetchLatestKlines(
      "BTCUSDT", "1m", 5, "spot", "binance", "initial-latest",
      { repair: "wait", waitMs: 1_500, demandScope: "chart:a", demandGeneration: 1 },
    ),
    coordinator.fetchLatestKlines(
      "BTCUSDT", "1m", 5, "spot", "binance", "initial-latest",
      { repair: "none", demandScope: "chart:a", demandGeneration: 1 },
    ),
    coordinator.fetchLatestKlines(
      "BTCUSDT", "1m", 5, "spot", "binance", "initial-latest",
      { repair: "wait", waitMs: 1_500, demandScope: "chart:a", demandGeneration: 2 },
    ),
  ]);
  assert.equal(calls.value, 3);
});

test("history, before, and range requests do not inherit another demand owner", async () => {
  const calls = { value: 0 };
  const coordinator = new SharedKlineRequestCoordinator(fakeApi(async () => result, calls));
  const firstDemand = { demandScope: "chart:a", demandGeneration: 1 };
  const nextDemand = { demandScope: "chart:a", demandGeneration: 2 };

  await Promise.all([
    coordinator.fetchKlinesHistory(
      "BTCUSDT", "1m", 7, "spot", "binance", { countBack: 500, ...firstDemand },
    ),
    coordinator.fetchKlinesHistory(
      "BTCUSDT", "1m", 7, "spot", "binance", { countBack: 500, ...nextDemand },
    ),
    coordinator.fetchKlinesBefore(
      "BTCUSDT", "1m", 100 as never, 500, "spot", "binance", firstDemand,
    ),
    coordinator.fetchKlinesBefore(
      "BTCUSDT", "1m", 100 as never, 500, "spot", "binance", nextDemand,
    ),
    coordinator.fetchKlinesRange(
      "BTCUSDT", "1m", 1 as never, 2 as never, "spot", "binance", firstDemand,
    ),
    coordinator.fetchKlinesRange(
      "BTCUSDT", "1m", 1 as never, 2 as never, "spot", "binance", nextDemand,
    ),
  ]);

  assert.equal(calls.value, 6);
});

test("distinct history requests in one browser task use one bounded physical batch", async () => {
  const singleCalls = { value: 0 };
  let batchCalls = 0;
  const api = fakeApi(async () => result, singleCalls);
  api.fetchKlinesHistoryBatch = async (requests) => {
    batchCalls += 1;
    assert.deepEqual(requests.map((item) => item.symbol), ["BTCUSDT", "ETHUSDT"]);
    return requests.map(() => ({ ok: true as const, result }));
  };
  const coordinator = new SharedKlineRequestCoordinator(api);

  const outcomes = await Promise.all([
    coordinator.fetchKlinesHistory(
      "BTCUSDT", "1m", 7, "spot", "binance", { countBack: 500 },
    ),
    coordinator.fetchKlinesHistory(
      "ETHUSDT", "1m", 7, "spot", "binance", { countBack: 500 },
    ),
  ]);

  assert.deepEqual(outcomes, [result, result]);
  assert.equal(batchCalls, 1);
  assert.equal(singleCalls.value, 0);
  assert.equal(coordinator.diagnostics().totalPhysical, 1);
  assert.equal(coordinator.diagnostics().completedPhysical, 1);
});

test("one batch consumer abort does not cancel the other distinct history request", async () => {
  const work = deferred<Awaited<ReturnType<NonNullable<KlineApi["fetchKlinesHistoryBatch"]>>>>();
  const singleCalls = { value: 0 };
  const physicalSignal: { current?: AbortSignal } = {};
  const api = fakeApi(async () => result, singleCalls);
  api.fetchKlinesHistoryBatch = (_requests, options) => {
    if (options.signal) physicalSignal.current = options.signal;
    return work.promise;
  };
  const coordinator = new SharedKlineRequestCoordinator(api);
  const firstAbort = new AbortController();
  const first = coordinator.fetchKlinesHistory(
    "BTCUSDT", "1m", 7, "spot", "binance", {
      countBack: 500,
      signal: firstAbort.signal,
    },
  );
  const second = coordinator.fetchKlinesHistory(
    "ETHUSDT", "1m", 7, "spot", "binance", { countBack: 500 },
  );
  await Promise.resolve();
  await Promise.resolve();

  firstAbort.abort();
  await assert.rejects(first, (error: unknown) => (error as Error).name === "AbortError");
  assert.equal(physicalSignal.current?.aborted, false);
  work.resolve([
    { ok: true, result },
    { ok: true, result },
  ]);
  assert.equal(await second, result);
});

test("late completion of an abandoned physical group cannot remove its replacement", async () => {
  const works = [deferred<KlineFetchResult>(), deferred<KlineFetchResult>()];
  const calls = { value: 0 };
  const coordinator = new SharedKlineRequestCoordinator(fakeApi(() => works[calls.value - 1]!.promise, calls));
  const owner = new AbortController();
  const first = coordinator.fetchKlinesHistory("BTCUSDT", "1m", 1, "spot", "binance", { signal: owner.signal });
  const failure = assert.rejects(first, (error: unknown) => (error as Error).name === "AbortError");
  await Promise.resolve(); owner.abort(); await failure;
  const second = coordinator.fetchKlinesHistory("BTCUSDT", "1m", 1, "spot", "binance", {});
  await Promise.resolve();
  works[0]!.resolve({ data: [] });
  await new Promise((resolve) => setImmediate(resolve));
  const third = coordinator.fetchKlinesHistory("BTCUSDT", "1m", 1, "spot", "binance", {});
  assert.equal(calls.value, 2);
  works[1]!.resolve(result);
  assert.equal(await second, result);
  assert.equal(await third, result);
  assert.equal(coordinator.diagnostics().physicalInflight, 0);
});

test("synchronous batch failure rejects every owner and allows an immediate retry", async () => {
  const calls = { value: 0 };
  const api = fakeApi(async () => result, calls);
  api.fetchKlinesHistoryBatch = () => { throw new Error("batch unavailable"); };
  const coordinator = new SharedKlineRequestCoordinator(api);
  await Promise.all(["BTCUSDT", "ETHUSDT"].map((symbol) => assert.rejects(
    coordinator.fetchKlinesHistory(symbol, "1m", 1, "spot", "binance", {}), /batch unavailable/,
  )));
  assert.equal(coordinator.diagnostics().logicalInflight, 0);
  assert.equal(coordinator.diagnostics().physicalInflight, 0);
  api.fetchKlinesHistoryBatch = async (requests) => requests.map(() => ({ ok: true, result }));
  await Promise.all(["BTCUSDT", "ETHUSDT"].map((symbol) => (
    coordinator.fetchKlinesHistory(symbol, "1m", 1, "spot", "binance", {})
  )));
  assert.equal(coordinator.diagnostics().completedPhysical, 2);
});

test("history batches stay bounded and preserve semantic identity and independent outcomes", async () => {
  const calls = { value: 0 };
  const batches: number[] = [];
  const api = fakeApi(async () => result, calls);
  api.fetchKlinesHistoryBatch = async (requests) => {
    batches.push(requests.length);
    assert.equal(requests[1]?.options.seriesIdentity?.providerId, "secondary");
    assert.ok(requests.every((request) => !("clientContext" in request.options)));
    return requests.map((_request, index) => index === 1
      ? { ok: false, error: new Error("provider failed") }
      : { ok: true, result });
  };
  const coordinator = new SharedKlineRequestCoordinator(api);
  const outcomes = await Promise.allSettled(Array.from({ length: 17 }, (_value, index) => (
    coordinator.fetchKlinesHistory("BTCUSDT", "1m", 1, "spot", "binance", {
      seriesIdentity: { providerId: index === 1 ? "secondary" : `provider-${index}` },
      clientContext: { epoch: 3, scope: "probe" },
    })
  )));
  assert.deepEqual(batches, [16]);
  assert.equal(calls.value, 1);
  assert.equal(outcomes.filter((outcome) => outcome.status === "fulfilled").length, 16);
  assert.equal(outcomes[1]?.status, "rejected");
  assert.equal(coordinator.diagnostics().physicalInflight, 0);
});
