export function resolveDesktopRuntimeConfig(environment = {}) {
  return {
    schemaVersion: 1,
    klineBatchStreamEnabled: environment.VITE_KLINE_BATCH_STREAM_ENABLED === undefined
      || environment.VITE_KLINE_BATCH_STREAM_ENABLED === "1",
  };
}

export function desktopBackendEnvironment(config) {
  if (config?.schemaVersion !== 1 || typeof config.klineBatchStreamEnabled !== "boolean") {
    throw new Error("Invalid desktop runtime configuration; rebuild the desktop package");
  }
  return { KLINE_BATCH_STREAM_ENABLED: config.klineBatchStreamEnabled ? "1" : "0" };
}

export function desktopRuntimeConfigPlugin() {
  let environment;
  return {
    name: "candlescope-desktop-runtime-config",
    apply: "build",
    configResolved(config) { environment = config.env; },
    generateBundle() {
      this.emitFile({
        type: "asset",
        fileName: "desktop-runtime-config.json",
        source: JSON.stringify(resolveDesktopRuntimeConfig(environment), null, 2),
      });
    },
  };
}
