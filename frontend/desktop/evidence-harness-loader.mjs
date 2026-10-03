const probeOutputs = [
  "CANDLESCOPE_DESKTOP_SPIKE_OUT",
  "CANDLESCOPE_DESKTOP_RESTORE_PROBE_OUT",
  "CANDLESCOPE_DESKTOP_PHASE7_OUT",
  "CANDLESCOPE_DESKTOP_PHASE8_OUT",
];

export async function loadEvidenceHarness(
  dependencies,
  environment = dependencies.process.env,
  importHarness = () => import("./evidence-harness.mjs"),
) {
  if (!probeOutputs.some((key) => environment[key])) return null;
  const { createEvidenceHarness } = await importHarness();
  return createEvidenceHarness(dependencies);
}

// Own probe policy here as well as lazy loading. The production shell only
// supplies its live owners; it does not interpret individual acceptance modes.
export function createEvidenceSession(environment, {
  loadHarness = loadEvidenceHarness,
  delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
} = {}) {
  if (!probeOutputs.some((key) => environment[key])) return null;
  const spikeOutput = environment.CANDLESCOPE_DESKTOP_SPIKE_OUT;
  const restoreOutput = environment.CANDLESCOPE_DESKTOP_RESTORE_PROBE_OUT;
  const phase7Output = environment.CANDLESCOPE_DESKTOP_PHASE7_OUT;
  const phase8Output = environment.CANDLESCOPE_DESKTOP_PHASE8_OUT;
  let harness;

  return {
    configureApp(app) {
      if (phase8Output) app.commandLine.appendSwitch("js-flags", "--expose-gc");
    },
    instrumentAppUrl(appUrl) {
      const target = new URL(appUrl);
      if (phase8Output) target.searchParams.set("capacityProbe", "phase8");
      else if (phase7Output) target.searchParams.set("capacityProbe", "phase7");
      return target.href;
    },
    async initialize(dependencies) {
      harness = await loadHarness(dependencies, environment);
    },
    topologyRejection(shellRevision) {
      if (!spikeOutput && !restoreOutput && harness?.state.phase7TopologyArmed) return null;
      return {
        ok: false,
        code: "SPIKE_TOPOLOGY_OWNED_BY_SHELL",
        message: "Automated desktop spike freezes its four-window topology until evidence is captured",
        shellRevision,
      };
    },
    noteDisplayEvent(kind) {
      harness.noteDisplayEvent(kind);
    },
    async run({ store, cached, manager }) {
      if (phase8Output) {
        await harness.runPhase8Evidence(store, phase8Output);
      } else if (phase7Output) {
        await harness.runPhase7Evidence(store, phase7Output);
      } else {
        if (spikeOutput) {
          const topology = harness.syntheticSpikeTopology(
            cached,
            Math.min(4, Math.max(1, Number(environment.CANDLESCOPE_DESKTOP_SPIKE_WINDOW_COUNT || 4))),
          );
          await manager.reconcile(topology);
        } else {
          await manager.restoreCached(cached);
        }
        await delay(2_000);
        const closeIsolation = await harness.exerciseCloseIsolation(store);
        const lifecycle = await harness.exerciseNativeLifecycle();
        await harness.writeSpikeEvidence(
          store, spikeOutput || restoreOutput, spikeOutput ? "create" : "restore",
          lifecycle, closeIsolation,
        );
      }
    },
  };
}
