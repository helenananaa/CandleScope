import assert from "node:assert/strict";
import test from "node:test";
import { createEvidenceSession } from "./evidence-harness-loader.mjs";

function fixture(environment) {
  const calls = [];
  const store = {};
  const cached = {};
  const topology = {};
  const harness = {
    state: { phase7TopologyArmed: false },
    runPhase7Evidence: async (...args) => calls.push(["phase7", ...args]),
    runPhase8Evidence: async (...args) => calls.push(["phase8", ...args]),
    syntheticSpikeTopology: (...args) => { calls.push(["topology", ...args]); return topology; },
    exerciseCloseIsolation: async (value) => { calls.push(["close", value]); return "closed"; },
    exerciseNativeLifecycle: async () => { calls.push(["lifecycle"]); return "lifecycle-result"; },
    writeSpikeEvidence: async (...args) => calls.push(["write", ...args]),
    noteDisplayEvent: (kind) => calls.push(["display", kind]),
  };
  const manager = {
    reconcile: async (value) => calls.push(["reconcile", value]),
    restoreCached: async (value) => calls.push(["restore", value]),
  };
  const session = createEvidenceSession(environment, {
    loadHarness: async (dependencies, suppliedEnvironment) => {
      assert.equal(suppliedEnvironment, environment);
      calls.push(["initialize", dependencies]);
      return harness;
    },
    delay: async (milliseconds) => calls.push(["delay", milliseconds]),
  });
  return { session, calls, store, cached, topology, harness, manager };
}

test("ordinary startup creates no probe session, even with a fault mode set", () => {
  assert.equal(createEvidenceSession({ CANDLESCOPE_DESKTOP_PHASE8_MODE: "F1" }, {
    loadHarness: () => assert.fail("ordinary startup cannot initialize probes"),
  }), null);
});

test("phase8 configures GC before initialization and has dispatch and URL precedence", async () => {
  const f = fixture({ CANDLESCOPE_DESKTOP_PHASE8_OUT: "eight.json", CANDLESCOPE_DESKTOP_PHASE7_OUT: "seven.json" });
  const switches = [];
  f.session.configureApp({ commandLine: { appendSwitch: (...args) => switches.push(args) } });
  assert.deepEqual(switches, [["js-flags", "--expose-gc"]]);
  assert.deepEqual(f.calls, []);
  const url = new URL(f.session.instrumentAppUrl("http://127.0.0.1:15173/?existing=value#chart"));
  assert.equal(url.searchParams.get("existing"), "value");
  assert.equal(url.searchParams.get("capacityProbe"), "phase8");
  assert.equal(url.hash, "#chart");
  assert.equal(f.session.topologyRejection(7).shellRevision, 7);
  await f.session.initialize({ manager: f.manager });
  await f.session.run(f);
  assert.deepEqual(f.calls.slice(1), [["phase8", f.store, "eight.json"]]);
  f.harness.state.phase7TopologyArmed = true;
  assert.equal(f.session.topologyRejection(8), null);
  f.session.noteDisplayEvent("removed");
  assert.deepEqual(f.calls.at(-1), ["display", "removed"]);
});

test("phase7 preserves topology handoff and does not enable GC", async () => {
  const f = fixture({ CANDLESCOPE_DESKTOP_PHASE7_OUT: "seven.json" });
  f.session.configureApp({ commandLine: { appendSwitch: () => assert.fail("only phase8 requires GC") } });
  assert.equal(new URL(f.session.instrumentAppUrl("http://127.0.0.1/")).searchParams.get("capacityProbe"), "phase7");
  await f.session.initialize({ manager: f.manager });
  assert.equal(f.session.topologyRejection(9).code, "SPIKE_TOPOLOGY_OWNED_BY_SHELL");
  await f.session.run(f);
  assert.deepEqual(f.calls.slice(1), [["phase7", f.store, "seven.json"]]);
  f.harness.state.phase7TopologyArmed = true;
  assert.equal(f.session.topologyRejection(10), null);
});

for (const [requested, count] of [["0", 1], ["3", 3], ["7", 4]]) {
  test(`spike preserves bounded topology and lifecycle ordering for ${requested} windows`, async () => {
    const f = fixture({
      CANDLESCOPE_DESKTOP_SPIKE_OUT: "spike.json",
      CANDLESCOPE_DESKTOP_RESTORE_PROBE_OUT: "restore.json",
      CANDLESCOPE_DESKTOP_SPIKE_WINDOW_COUNT: requested,
    });
    assert.equal(f.session.instrumentAppUrl("http://127.0.0.1/?test=1"), "http://127.0.0.1/?test=1");
    await f.session.initialize({ manager: f.manager });
    f.harness.state.phase7TopologyArmed = true;
    assert.equal(f.session.topologyRejection(12).shellRevision, 12);
    await f.session.run(f);
    assert.deepEqual(f.calls.slice(1), [
      ["topology", f.cached, count], ["reconcile", f.topology], ["delay", 2_000],
      ["close", f.store], ["lifecycle"],
      ["write", f.store, "spike.json", "create", "lifecycle-result", "closed"],
    ]);
  });
}

test("restore uses cached windows and writes restore evidence after lifecycle checks", async () => {
  const f = fixture({ CANDLESCOPE_DESKTOP_RESTORE_PROBE_OUT: "restore.json" });
  await f.session.initialize({ manager: f.manager });
  await f.session.run(f);
  assert.deepEqual(f.calls.slice(1), [
    ["restore", f.cached], ["delay", 2_000], ["close", f.store], ["lifecycle"],
    ["write", f.store, "restore.json", "restore", "lifecycle-result", "closed"],
  ]);
});

test("failed setup stops the probe before lifecycle or evidence publication", async () => {
  const f = fixture({ CANDLESCOPE_DESKTOP_SPIKE_OUT: "spike.json" });
  const failure = new Error("cannot create window");
  f.manager.reconcile = async () => { throw failure; };
  await f.session.initialize({ manager: f.manager });
  await assert.rejects(f.session.run(f), failure);
  assert.deepEqual(f.calls.map(([name]) => name), ["initialize", "topology"]);
});

test("probe import failure propagates to startup error handling", async () => {
  const failure = new Error("probe module unavailable");
  const session = createEvidenceSession({ CANDLESCOPE_DESKTOP_PHASE8_OUT: "probe.json" }, {
    loadHarness: async () => { throw failure; },
  });
  await assert.rejects(session.initialize({}), failure);
});
