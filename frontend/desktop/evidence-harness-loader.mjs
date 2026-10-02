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
