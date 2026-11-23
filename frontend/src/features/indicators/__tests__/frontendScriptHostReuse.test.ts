import assert from "node:assert/strict";
import { after, before, mock, test } from "node:test";
import vm from "node:vm";
import { computeFrontendScript, frontendScriptRuntimeDiagnostics, releaseIdleFrontendScriptHosts } from "../frontendScriptRuntime.js";
import { frontendScriptSandboxDocument } from "../frontendScriptSandbox.js";
import { FRONTEND_SCRIPT_LANGUAGE } from "../frontendScriptContract.js";
import type { IndicatorComputeRequest } from "../indicatorTypes.js";

// A small renderer fake. Each hidden iframe runs the real sandbox bootstrap
// (`frontendScriptSandboxDocument`) in its own V8 context, and each Worker runs
// the real worker source from the bootstrap's Blob in a fresh context, so the
// isolation and lifecycle rules under test are the production ones.

type Listener = (event: unknown) => void;
const HOLD = "/*hold*/";
const parentWindow = {};
const blobs = new Map<string, string>();
const stats = { framesCreated: 0, workersCreated: 0, liveWorkers: 0, liveBlobUrls: 0, maxLiveWorkers: 0 };
const workers: FakeWorker[] = [];
const frames: FakeFrame[] = [];

/** Copy JSON-safe data into another realm, as structured clone would. */
function intoRealm(context: vm.Context, value: unknown): unknown {
  return (vm.runInContext("JSON.parse", context) as (text: string) => unknown)(JSON.stringify(value));
}

class FakeWorker {
  terminated = false;
  held?: unknown;
  onmessage: Listener | null = null;
  onerror: Listener | null = null;
  readonly scope: Record<string, unknown>;
  readonly context: vm.Context;
  constructor(url: string) {
    const source = blobs.get(url);
    if (source === undefined) throw new Error("Unknown worker URL");
    stats.workersCreated++;
    stats.liveWorkers++;
    stats.maxLiveWorkers = Math.max(stats.maxLiveWorkers, stats.liveWorkers);
    workers.push(this);
    this.scope = {
      postMessage: (data: unknown) => setImmediate(() => { if (!this.terminated) this.onmessage?.({ data }); }),
      // The test loader (tsx/esbuild keepNames) inserts this helper into
      // `workerMain.toString()`; Vite's production build does not.
      __name: (target: unknown) => target,
    };
    this.context = vm.createContext(this.scope);
    vm.runInContext(source, this.context);
  }
  postMessage(data: unknown): void {
    if ((data as { script?: string }).script?.includes(HOLD)) { this.held = data; return; }
    this.deliver(data);
  }
  /** Lets a held "long-running" script finish. */
  resume(): void { const data = this.held; delete this.held; if (data !== undefined) this.deliver(data); }
  private deliver(data: unknown): void {
    const copy = intoRealm(this.context, data);
    setImmediate(() => {
      if (this.terminated) return;
      (this.scope.onmessage as Listener | undefined)?.({ data: copy });
    });
  }
  terminate(): void {
    if (this.terminated) return;
    this.terminated = true;
    stats.liveWorkers--;
  }
}

class FakeFrame {
  hidden = false;
  title = "";
  referrerPolicy = "";
  srcdoc = "";
  isConnected = false;
  onload: (() => void) | null = null;
  readonly attributes = new Map<string, string>();
  readonly listeners = new Map<string, Set<Listener>>();
  readonly ports: MessagePort[] = [];
  context?: vm.Context;
  contentWindow: { postMessage: (data: unknown, origin: string, ports: MessagePort[]) => void } | null = null;
  setAttribute(name: string, value: string): void { this.attributes.set(name, value); }
  load(): void {
    const script = /<script>([\s\S]*)<\/script>/.exec(this.srcdoc)?.[1];
    if (!script) throw new Error("Sandbox document has no bootstrap");
    stats.framesCreated++;
    frames.push(this);
    this.isConnected = true;
    const listeners = this.listeners;
    this.context = vm.createContext({
      parent: parentWindow,
      addEventListener: (type: string, listener: Listener, options?: { once?: boolean }) => {
        const set = listeners.get(type) ?? new Set<Listener>();
        listeners.set(type, set);
        if (!options?.once) { set.add(listener); return; }
        const once: Listener = event => { set.delete(once); listener(event); };
        (listener as Listener & { once?: Listener }).once = once;
        set.add(once);
      },
      removeEventListener: (type: string, listener: Listener & { once?: Listener }) => {
        listeners.get(type)?.delete(listener);
        if (listener.once) listeners.get(type)?.delete(listener.once);
      },
      Blob: class { readonly source: string; constructor(parts: string[]) { this.source = parts.join(""); } },
      URL: {
        createObjectURL: (blob: { source: string }) => {
          const url = `blob:fake/${blobs.size + 1}`;
          blobs.set(url, blob.source);
          stats.liveBlobUrls++;
          return url;
        },
        revokeObjectURL: (url: string) => { if (blobs.delete(url)) stats.liveBlobUrls--; },
      },
      Worker: FakeWorker,
    });
    vm.runInContext(script, this.context);
    this.contentWindow = {
      postMessage: (data, _origin, ports) => {
        const { transferred } = structuredClone({ transferred: ports }, { transfer: ports });
        this.ports.push(...transferred);
        const copy = intoRealm(this.context!, data);
        setImmediate(() => {
          if (!this.isConnected) { for (const port of transferred) port.close(); return; }
          for (const listener of [...(listeners.get("message") ?? [])]) listener({ source: parentWindow, data: copy, ports: transferred });
        });
      },
    };
    setImmediate(() => { if (this.isConnected) this.onload?.(); });
  }
  remove(): void {
    if (!this.isConnected) return;
    this.isConnected = false;
    this.contentWindow = null;
    // A removed document gets pagehide; the bootstrap stops its Worker there.
    for (const listener of [...(this.listeners.get("pagehide") ?? [])]) listener({});
    // Its ports die with it, so it can never acknowledge a later "stop".
    for (const port of this.ports) port.close();
  }
}

const fakeDocument = {
  createElement: (tag: string) => {
    assert.equal(tag, "iframe");
    return new FakeFrame();
  },
  body: { append: (...nodes: FakeFrame[]) => { for (const node of nodes) node.load(); } },
};

const bars = [1, 2, 3].map(time => ({ time, open: 10, high: 20, low: 9, close: 10 + time, volume: 1 }));
const job = (script: string): IndicatorComputeRequest => ({ language: FRONTEND_SCRIPT_LANGUAGE, script, ohlcv: bars });
const clean = 'plot("close", bars.map(bar => bar.close))';
const connectedFrames = () => frames.filter(frame => frame.isConnected);
const pagehideListeners = () => frames.reduce((total, frame) => total + (frame.listeners.get("pagehide")?.size ?? 0), 0);

async function until(predicate: () => boolean, label: string): Promise<void> {
  const deadline = Date.now() + 5_000;
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error(`Timed out waiting for ${label}`);
    await new Promise(resolve => setImmediate(resolve));
  }
}

function assertNoLeakedExecution(): void {
  const diagnostics = frontendScriptRuntimeDiagnostics();
  assert.equal(diagnostics.running, 0, "an execution slot stayed busy");
  assert.equal(diagnostics.queued, 0, "queued work was left behind");
  assert.equal(stats.liveWorkers, 0, "a Worker was not terminated");
  assert.equal(stats.liveBlobUrls, 0, "a worker Blob URL was not revoked");
  assert.equal(pagehideListeners(), 0, "a finished job kept its pagehide listener");
  assert.ok(connectedFrames().length <= 2, "more than two isolation hosts are alive");
}

before(() => {
  Object.defineProperty(globalThis, "document", { value: fakeDocument, configurable: true, writable: true });
  // Only the runtime's timers are mocked; message delivery uses setImmediate.
  mock.timers.enable({ apis: ["setTimeout"] });
});

after(() => {
  releaseIdleFrontendScriptHosts();
  // Closing every document's ports also closes their peers, so a failed
  // assertion cannot leave an open MessagePort that keeps this file running.
  for (const frame of frames) frame.remove();
  mock.timers.reset();
  Reflect.deleteProperty(globalThis, "document");
});

test("forty computations reuse at most two opaque hosts and every job gets fresh script globals", async () => {
  const dirty = await computeFrontendScript(job(
    'globalThis.__priorJob = 123; Array.prototype.__polluted = 1; Object.prototype.__leak = 1; plot("x", bars.map(() => 1));'));
  assert.equal(dirty.ok, true, dirty.error ?? "computation failed");
  const hosts = connectedFrames();
  for (let index = 0; index < 40; index++) {
    const next = await computeFrontendScript(job(
      'if (globalThis.__priorJob !== undefined || [].__polluted !== undefined || ({}).__leak !== undefined) throw new Error("shared worker state");'
      + ' plot("close", bars.map(bar => bar.close));'));
    assert.equal(next.ok, true, next.error ?? "computation failed");
    assert.deepEqual(next.lines[0]!.data.map(point => point.value), [11, 12, 13]);
  }
  assert.ok(hosts.length >= 1 && hosts.length <= 2);
  assert.ok(connectedFrames().every(frame => hosts.includes(frame)), "continuous computations recreated isolation documents");
  assert.ok(stats.framesCreated <= 2, `created ${stats.framesCreated} isolation documents for sequential work`);
  assert.equal(stats.workersCreated, 41, "every computation must get its own Worker");
  assertNoLeakedExecution();
});

test("several charts computing at once share two hosts and never run more than two Workers", async () => {
  const framesBefore = stats.framesCreated;
  stats.maxLiveWorkers = 0;
  const results = await Promise.all(Array.from({ length: 8 }, (_, index) =>
    computeFrontendScript(job(`plot("chart${index}", bars.map(bar => bar.close + ${index}))`))));
  results.forEach((result, index) => {
    assert.equal(result.ok, true, result.error ?? "computation failed");
    assert.equal(result.lines[0]!.name, `chart${index}`);
    assert.deepEqual(result.lines[0]!.data.map(point => point.value), [11 + index, 12 + index, 13 + index]);
  });
  assert.equal(stats.maxLiveWorkers, 2);
  assert.ok(stats.framesCreated - framesBefore <= 1, "concurrent work created more than the second host");
  assert.equal(connectedFrames().length, 2);
  assertNoLeakedExecution();
});

test("script errors and invalid output return errors and keep the host reusable", async () => {
  const framesBefore = stats.framesCreated;
  const thrown = await computeFrontendScript(job('throw new Error("boom")'));
  assert.equal(thrown.ok, false);
  assert.equal(thrown.error, "boom");
  const forged = await computeFrontendScript(job('plot("x", [1])'));
  assert.equal(forged.ok, false);
  assert.match(forged.error ?? "", /plot requires/);
  const next = await computeFrontendScript(job(clean));
  assert.equal(next.ok, true, next.error ?? "computation failed");
  assert.equal(stats.framesCreated, framesBefore, "an error retired a healthy host");
  assertNoLeakedExecution();
});

test("cancelling running or queued work releases its slot, and the next computation succeeds", async () => {
  const startedBefore = frontendScriptRuntimeDiagnostics().started;
  const workersBefore = workers.length;
  const controllers = [new AbortController(), new AbortController(), new AbortController()];
  const tasks = controllers.map(controller => computeFrontendScript(job(`${HOLD}${clean}`), controller.signal));
  await until(() => workers.slice(workersBefore).filter(worker => worker.held !== undefined).length === 2, "two running jobs");
  assert.equal(frontendScriptRuntimeDiagnostics().queued, 1);
  controllers[2]!.abort();
  await assert.rejects(tasks[2]!, { name: "AbortError" });
  assert.equal(frontendScriptRuntimeDiagnostics().started, startedBefore + 2, "a cancelled queued job started");
  controllers[0]!.abort();
  controllers[1]!.abort();
  await assert.rejects(tasks[0]!, { name: "AbortError" });
  await assert.rejects(tasks[1]!, { name: "AbortError" });
  const next = await computeFrontendScript(job(clean));
  assert.equal(next.ok, true, next.error ?? "computation failed");
  assertNoLeakedExecution();
});

test("a script past the execution limit is stopped and its host is reused after the stop acknowledgement", async () => {
  const framesBefore = stats.framesCreated;
  const workersBefore = workers.length;
  const task = computeFrontendScript(job(`${HOLD}${clean}`));
  await until(() => workers[workersBefore]?.held !== undefined, "running job");
  mock.timers.tick(2_000);
  const result = await task;
  assert.equal(result.ok, false);
  assert.match(result.error ?? "", /2 second execution limit/);
  assert.equal(workers[workersBefore]!.terminated, true);
  assert.equal(stats.framesCreated, framesBefore, "a stopped host was not reused");
  const next = await computeFrontendScript(job(clean));
  assert.equal(next.ok, true, next.error ?? "computation failed");
  assert.equal(stats.framesCreated, framesBefore);
  assertNoLeakedExecution();
});

test("a host whose document went away is retired and replaced, not reused", async () => {
  const workersBefore = workers.length;
  const task = computeFrontendScript(job(`${HOLD}${clean}`));
  await until(() => workers[workersBefore]?.held !== undefined, "running job");
  const owner = connectedFrames().find(frame => frame.listeners.get("pagehide")?.size);
  assert.ok(owner);
  owner.remove();
  assert.equal(workers[workersBefore]!.terminated, true, "pagehide did not stop the running Worker");
  mock.timers.tick(2_000);
  // The gone document can never acknowledge "stop"; the bounded cleanup retires it.
  await new Promise(resolve => setImmediate(resolve));
  mock.timers.tick(250);
  const result = await task;
  assert.match(result.error ?? "", /2 second execution limit/);
  const framesBefore = stats.framesCreated;
  const next = await computeFrontendScript(job(clean));
  assert.equal(next.ok, true, next.error ?? "computation failed");
  assert.ok(stats.framesCreated <= framesBefore + 1);
  assert.ok(!connectedFrames().includes(owner));
  assertNoLeakedExecution();
});

test("idle hosts retire after 30 seconds; releasing idle hosts never interrupts a running job", async () => {
  releaseIdleFrontendScriptHosts();
  assert.equal(frontendScriptRuntimeDiagnostics().hosts, 0);
  assert.equal(connectedFrames().length, 0);
  assert.equal((await computeFrontendScript(job(clean))).ok, true);
  assert.equal(frontendScriptRuntimeDiagnostics().hosts, 1);
  mock.timers.tick(29_999);
  assert.equal(frontendScriptRuntimeDiagnostics().hosts, 1, "host retired before its idle period");
  mock.timers.tick(1);
  assert.equal(frontendScriptRuntimeDiagnostics().hosts, 0, "idle host was not retired");
  assert.equal(connectedFrames().length, 0);

  const workersBefore = workers.length;
  const task = computeFrontendScript(job(`${HOLD}${clean}`));
  await until(() => workers[workersBefore]?.held !== undefined, "running job");
  releaseIdleFrontendScriptHosts();
  assert.equal(frontendScriptRuntimeDiagnostics().hosts, 1, "a busy host was released");
  workers[workersBefore]!.resume();
  const result = await task;
  assert.equal(result.ok, true, result.error ?? "computation failed");
  releaseIdleFrontendScriptHosts();
  assert.equal(frontendScriptRuntimeDiagnostics().hosts, 0);
  assertNoLeakedExecution();
});

test("the sandbox bootstrap refuses a second job while one is active and accepts new work after stop", async () => {
  const frame = new FakeFrame();
  frame.srcdoc = frontendScriptSandboxDocument();
  frame.load();
  const send = (data: unknown) => {
    const channel = new MessageChannel();
    const replies: unknown[] = [];
    channel.port1.onmessage = event => replies.push(event.data);
    frame.contentWindow!.postMessage(data, "*", [channel.port2]);
    return { channel, replies };
  };
  const first = send({ script: `${HOLD}${clean}`, bars, params: {} });
  await until(() => first.replies.includes("ready"), "first job ready");
  const second = send({ script: clean, bars, params: {} });
  await until(() => second.replies.length === 1, "busy refusal");
  assert.deepEqual(JSON.parse(String(second.replies[0])), { error: "Frontend script isolation is busy" });
  first.channel.port1.postMessage("run");
  first.channel.port1.postMessage("stop");
  await until(() => first.replies.includes("stopped"), "stop acknowledgement");
  const third = send({ script: clean, bars, params: {} });
  await until(() => third.replies.includes("ready"), "third job ready");
  third.channel.port1.postMessage("run");
  await until(() => third.replies.length === 2, "third job output");
  assert.equal((JSON.parse(String(third.replies[1])) as { lines: unknown[] }).lines.length, 1);
  for (const channel of [first.channel, second.channel, third.channel]) channel.port1.close();
  frame.remove();
  assert.equal(stats.liveWorkers, 0);
  assert.equal(stats.liveBlobUrls, 0);
});
