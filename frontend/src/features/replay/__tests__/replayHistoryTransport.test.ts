import assert from "node:assert/strict";
import test from "node:test";
import { readReplayHistory, ReplayHistoryLoadGate } from "../replayHistoryTransport.js";
import { TransferredViewportHistory } from "../../../components/transferredViewportHistory.js";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

test("four charts join one read; canceling one cannot interrupt its peers", async () => {
  const gate = deferred<Response>();
  let count = 0;
  let transportSignal: AbortSignal | null | undefined;
  const fetcher: typeof fetch = (_url, init) => {
    count += 1;
    transportSignal = init?.signal;
    return gate.promise.then((response) => response.clone());
  };
  const controllers = Array.from({ length: 4 }, () => new AbortController());
  const jobs = controllers.map((controller) => readReplayHistory(fetcher, "/page?reveal=10", "SOL", controller.signal));
  assert.equal(count, 1);
  const canceled = assert.rejects(jobs[0]!, { name: "AbortError" });
  controllers[0]!.abort();
  await canceled;
  assert.equal(transportSignal?.aborted, false);
  gate.resolve(Response.json({ bars: [1, 2] }));
  const replies = await Promise.all(jobs.slice(1));
  assert.deepEqual(replies.map((reply) => reply.payload), Array(3).fill({ bars: [1, 2] }));
  assert.equal(transportSignal?.aborted, false);
  await readReplayHistory(fetcher, "/page?reveal=10", "SOL", new AbortController().signal);
  assert.equal(count, 2, "completed data is not retained as a shared cache");
});

test("all consumers leaving aborts the transport and a new chart gets a fresh read", async () => {
  const requests: { gate: ReturnType<typeof deferred<Response>>; signal: AbortSignal | null | undefined }[] = [];
  const fetcher: typeof fetch = (_url, init) => {
    const gate = deferred<Response>();
    requests.push({ gate, signal: init?.signal });
    return gate.promise;
  };
  const a = new AbortController();
  const b = new AbortController();
  const first = readReplayHistory(fetcher, "/page", "SOL", a.signal);
  const second = readReplayHistory(fetcher, "/page", "SOL", b.signal);
  const rejected = Promise.all([assert.rejects(first, { name: "AbortError" }), assert.rejects(second, { name: "AbortError" })]);
  a.abort(); b.abort();
  await rejected;
  assert.equal(requests[0]?.signal?.aborted, true);
  const next = readReplayHistory(fetcher, "/page", "SOL", new AbortController().signal);
  assert.equal(requests.length, 2);
  requests[0]!.gate.resolve(Response.json({ stale: true }));
  await Promise.resolve();
  const joined = readReplayHistory(fetcher, "/page", "SOL", new AbortController().signal);
  assert.equal(requests.length, 2, "the canceled read must not remove its replacement");
  requests[1]!.gate.resolve(Response.json({ fresh: true }));
  assert.deepEqual((await next).payload, { fresh: true });
  assert.deepEqual((await joined).payload, { fresh: true });
});

test("boundary, epoch, period, source identity and fetcher remain isolated", async () => {
  let count = 0;
  const gate = deferred<void>();
  const fetcher: typeof fetch = async () => {
    count += 1;
    await gate.promise;
    return Response.json({});
  };
  const urls = ["/page?boundary=1&epoch=a&period=1d", "/page?boundary=2&epoch=a&period=1d",
    "/page?boundary=1&epoch=b&period=1d", "/page?boundary=1&epoch=a&period=4h"];
  const jobs = urls.map((url) => readReplayHistory(fetcher, url, "SOL", new AbortController().signal));
  jobs.push(readReplayHistory(fetcher, urls[0]!, "DOGE", new AbortController().signal));
  const otherFetcher: typeof fetch = (...args) => fetcher(...args);
  jobs.push(readReplayHistory(otherFetcher, urls[0]!, "SOL", new AbortController().signal));
  assert.equal(count, 6);
  gate.resolve();
  await Promise.all(jobs);
});

test("transport failure and already-canceled consumers cannot poison a retry", async () => {
  let count = 0;
  const fetcher: typeof fetch = async () => {
    count += 1;
    if (count === 1) throw new Error("offline");
    return Response.json({ ready: true });
  };
  const gone = new AbortController(); gone.abort();
  await assert.rejects(readReplayHistory(fetcher, "/page", "SOL", gone.signal), { name: "AbortError" });
  assert.equal(count, 0);
  await assert.rejects(readReplayHistory(fetcher, "/page", "SOL", new AbortController().signal), /offline/);
  assert.deepEqual((await readReplayHistory(fetcher, "/page", "SOL", new AbortController().signal)).payload, { ready: true });
  assert.equal(count, 2);
});

test("a transferred viewport waits for an existing warmup page before checking progress", async () => {
  const gate = new ReplayHistoryLoadGate();
  const pending = deferred<void>();
  let firstTime = 900;
  let loads = 0;
  const load = () => gate.run("SOL:1m", async () => {
    loads += 1;
    await pending.promise;
    firstTime = 400;
  });
  const warmup = load();
  const fill = new TransferredViewportHistory("SOL:1m", 100);
  const input = () => ({ datasetKey: "SOL:1m", firstTime, loading: false, canLoad: true, hasHandler: true });
  let finished = false;
  const viewport = fill.loadPage(input(), load).then(() => { finished = true; });
  await Promise.resolve();
  assert.equal(finished, false, "a busy load cannot masquerade as an empty successful page");
  assert.equal(loads, 1);
  pending.resolve();
  await Promise.all([warmup, viewport]);
  assert.equal(fill.claim(input()), 400, "the next contiguous page is still eligible");
});

test("an old interval completion cannot clear a new interval's load ownership", async () => {
  const gate = new ReplayHistoryLoadGate();
  const old = deferred<void>();
  const current = deferred<void>();
  const first = gate.run("1d", () => old.promise);
  const next = gate.run("1m", () => current.promise);
  old.resolve(); await first;
  const joined = gate.run("1m", () => { throw new Error("duplicate load"); });
  assert.equal(joined, next);
  current.resolve(); await next;
  let retried = false;
  await gate.run("1m", async () => { retried = true; });
  assert.equal(retried, true);
});

test("publishing loading=false can immediately start the next page before the old promise settles", async () => {
  const gate = new ReplayHistoryLoadGate();
  const old = deferred<void>();
  const current = deferred<void>();
  let releaseOld!: () => void;
  const first = gate.run("1d", (release) => { releaseOld = release; return old.promise; });
  assert.equal(gate.run("1d", () => { throw new Error("duplicate"); }), first);
  releaseOld();
  const next = gate.run("1d", () => current.promise);
  assert.notEqual(first, next);
  releaseOld();
  assert.equal(gate.run("1d", () => { throw new Error("old release erased reused key"); }), next);
  old.resolve(); await first;
  assert.equal(gate.run("1d", () => { throw new Error("old cleanup erased current page"); }), next);
  current.resolve(); await next;
});

test("contiguous fill follows a discarded anchor page instead of treating it as history exhaustion", async () => {
  const gate = new ReplayHistoryLoadGate();
  const anchor = deferred<void>();
  let first = 900;
  let contiguousRequests = 0;
  const initial = gate.run("1m", () => anchor.promise);
  const fill = new TransferredViewportHistory("1m", 100);
  const request = (before: number) => gate.runAfterCurrent("1m", () => first >= before, async () => {
    contiguousRequests += 1;
    first -= 400;
  });
  const input = () => ({ datasetKey: "1m", firstTime: first, loading: false, canLoad: true, hasHandler: true });
  const page = fill.loadPage(input(), request);
  await Promise.resolve();
  assert.equal(contiguousRequests, 0);
  anchor.resolve(); await Promise.all([initial, page]);
  assert.equal(first, 500);
  assert.equal(await fill.loadPage(input(), request), true);
  assert.equal(await fill.loadPage(input(), request), false);
  assert.equal(first, 100);
  assert.equal(contiguousRequests, 2);
});

test("a joined page that already advanced, or a superseded generation, needs no follow-up request", async () => {
  for (const scenario of ["advanced", "superseded"] as const) {
    const gate = new ReplayHistoryLoadGate();
    const anchor = deferred<void>();
    let first = 900;
    let current = true;
    const initial = gate.run("1m", () => anchor.promise);
    const job = gate.runAfterCurrent("1m", () => current && first >= 900, async () => {
      assert.fail("obsolete contiguous demand must not request a page");
    });
    if (scenario === "advanced") first = 400;
    else current = false;
    anchor.resolve();
    await Promise.all([initial, job]);
  }
});
