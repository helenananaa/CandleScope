import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { loadEvidenceHarness } from "./evidence-harness-loader.mjs";
import { createEvidenceHarness } from "./evidence-harness.mjs";

const display = { workArea: { x: 0, y: 0, width: 1920, height: 1080 }, scaleFactor: 1 };
const dependencies = (env = {}) => ({
  process: { env },
  screen: { getPrimaryDisplay: () => display },
});

test("ordinary startup does not import or initialize evidence and fault injection", async () => {
  const deps = dependencies({ CANDLESCOPE_DESKTOP_PHASE8_MODE: "F1" });
  const result = await loadEvidenceHarness(deps, deps.process.env, () => {
    assert.fail("production startup must not load the probe module");
  });
  assert.equal(result, null);
});

for (const flag of ["SPIKE_OUT", "RESTORE_PROBE_OUT", "PHASE7_OUT", "PHASE8_OUT"]) {
  test(`${flag} loads the harness with the live shell dependencies`, async () => {
    const deps = dependencies({ [`CANDLESCOPE_DESKTOP_${flag}`]: "probe.json" });
    const result = { state: { phase7TopologyArmed: false } };
    let imports = 0;
    assert.equal(await loadEvidenceHarness(deps, deps.process.env, async () => {
      imports += 1;
      return { createEvidenceHarness: (supplied) => { assert.equal(supplied, deps); return result; } };
    }), result);
    assert.equal(imports, 1);
  });
}

test("real lazy module preserves synthetic topology and all probe entrypoints", async () => {
  const harness = await loadEvidenceHarness(dependencies({ CANDLESCOPE_DESKTOP_SPIKE_OUT: "probe.json" }));
  const topology = harness.syntheticSpikeTopology({ workspaceRevision: 7, shellRevision: 12 }, 4);
  assert.equal(topology.workspaceRevision, 8);
  assert.equal(topology.expectedShellRevision, 12);
  assert.deepEqual(Object.keys(topology.windows), ["main-window", "window-2", "window-3", "window-4"]);
  assert.equal(topology.windows["window-4"].boundsDip.x, 999);
  for (const entry of ["exerciseNativeLifecycle", "exerciseCloseIsolation", "writeSpikeEvidence", "runPhase7Evidence", "runPhase8Evidence"]) {
    assert.equal(typeof harness[entry], "function");
  }
});

test("phase7 readiness updates the shared topology state observed by IPC", async () => {
  const stopped = new Error("stop after readiness boundary");
  let reconciled;
  const window = {
    isDestroyed: () => false,
    webContents: { executeJavaScript: async (source) => {
      if (source.includes("configure64()")) throw stopped;
      return true;
    } },
  };
  const harness = createEvidenceHarness({
    ...dependencies(),
    manager: {
      windows: new Map([["main-window", window]]),
      reconcile: async (topology) => { reconciled = topology; },
    },
  });
  const ipcState = harness.state;
  assert.equal(ipcState.phase7TopologyArmed, false);
  await assert.rejects(harness.runPhase7Evidence({ snapshot: () => ({ workspaceRevision: 0, shellRevision: 0 }) }, "unused"), stopped);
  assert.equal(Object.keys(reconciled.windows).length, 4);
  assert.equal(harness.state, ipcState);
  assert.equal(ipcState.phase7TopologyArmed, true);
});

test("unsupported probe scenarios retain fail-closed dispatch", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "candlescope-evidence-test-"));
  try {
    const harness = createEvidenceHarness(dependencies({
      CANDLESCOPE_DESKTOP_PHASE7_SCENARIO: "invalid",
      CANDLESCOPE_DESKTOP_PHASE8_MODE: "invalid",
    }));
    await assert.rejects(harness.runPhase7Evidence({}, "unused"), /Unsupported Phase 7 scenario: INVALID/);
    await assert.rejects(harness.runPhase8Evidence({}, path.join(directory, "probe.json")), /Unsupported Phase 8 mode: INVALID/);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
