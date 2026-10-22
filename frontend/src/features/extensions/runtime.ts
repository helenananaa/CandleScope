import * as React from "react";
import { extensionManagementRequest, pluginManagementAvailable, trustedExtensionAssetBase } from "../plugins/pluginPlatformApi.js";
import type { Dispose, ExtensionCatalog, ExtensionContext, ExtensionModule, ExtensionRecord } from "./contracts.js";
import { applyExtensionTheme, bindHostService, emitHostEvent, subscribeHostEvent, extensionSafeMode, getExtensionState, getHostService, publishExtensions } from "./state.js";

const commands = new Map<string, (payload?: unknown) => unknown>();
const slotOwners = new Map<string, string>();
const serviceOwners = new Map<string, string>();
const modules = new Map<string, { digest: string; generation: number; version: string; dispose: Dispose }>();
const runningModules = () => [...modules].map(([id, { digest, generation, version }]) => ({ id, digest, generation, version }));
const attempted = new Set<string>();
let refreshing: Promise<void> | null = null;
let lastRevision = -1;
let reconciliationEpoch = 0;
const marker = "candlescope-extension-loading-v1";
const validSlots = new Set(["shell", "topBar", "intervalSelector", "workspace", "featureSurfaces", "statusBar", "toolbar", "chart", "bottomPanel", "rightRail", "exportOverlay"]);

async function boundedActivation<T>(work: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([work, new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => reject(new Error("Extension activation timed out; reload after disabling it")), 10_000);
    })]);
  } finally { if (timer !== undefined) clearTimeout(timer); }
}

export function createExtensionContext(item: ExtensionRecord): { context: ExtensionContext; dispose: Dispose } {
  const cleanups: Dispose[] = [];
  let disposed = false;
  const id = item.manifest.id;
  const track = (cleanup: Dispose) => {
    if (disposed) { void Promise.resolve().then(cleanup).catch((error) => report(id, error)); throw new Error("Extension has been disposed"); }
    cleanups.push(cleanup);
  };
  const context: ExtensionContext = {
    id, apiVersion: 1, React, track,
    assetUrl(path) {
      if (!/^[A-Za-z0-9_./-]+$/.test(path) || path.split("/").some((part) => !part || part === "." || part === "..")) throw new Error("Invalid extension asset path");
      return `${trustedExtensionAssetBase(item.assetBase ?? "")}${path}`;
    },
    ui: {
      replaceSlot(name, component) {
        if (!validSlots.has(name) || slotOwners.has(name)) throw new Error(`Slot unavailable or already replaced: ${name}`);
        slotOwners.set(name, id);
        const slots = new Map(getExtensionState().slots);
        slots.set(name, component);
        publishExtensions({ slots });
        track(() => {
          if (slotOwners.get(name) !== id) return;
          slotOwners.delete(name);
          const remaining = new Map(getExtensionState().slots);
          remaining.delete(name);
          publishExtensions({ slots: remaining });
        });
      },
      stylesheet(css) {
        const element = document.createElement("style");
        element.dataset.extensionOwner = id;
        element.textContent = css;
        document.head.append(element);
        track(() => element.remove());
      },
    },
    commands: {
      register(name, handler) {
        const key = `${id}.${name}`;
        if (commands.has(key)) throw new Error(`Duplicate command: ${key}`);
        commands.set(key, handler);
        track(() => { if (commands.get(key) === handler) commands.delete(key); });
      },
      execute(name, payload) {
        const handler = commands.get(name);
        if (!handler) throw new Error(`Command unavailable: ${name}`);
        return handler(payload);
      },
    },
    events: {
      on(name, listener) {
        track(subscribeHostEvent(name, (payload) => {
          try { void Promise.resolve(listener(payload)).catch((error) => report(id, error)); } catch (error) { report(id, error); }
        }));
      },
      emit: emitHostEvent,
    },
    services: {
      get: getHostService,
      register(name, value) {
        const key = `${id}.${name}`;
        if (serviceOwners.has(key)) throw new Error(`Duplicate service: ${key}`);
        serviceOwners.set(key, id);
        const unbind = bindHostService(key, value);
        track(() => { unbind(); serviceOwners.delete(key); });
      },
    },
    ...(item.manifest.internalApiVersion === 1 ? { internal: { apiVersion: 1 as const, get: getHostService } } : {}),
  };
  return { context, async dispose() {
    disposed = true;
    const errors: unknown[] = [];
    for (const cleanup of cleanups.reverse()) {
      try { await boundedActivation(Promise.resolve(cleanup())); } catch (error) { errors.push(error); }
    }
    cleanups.length = 0;
    if (errors.length) throw new AggregateError(errors, `Failed to dispose ${id}`);
  } };
}

async function reconcile(): Promise<void> {
  const epoch = reconciliationEpoch;
  if (!pluginManagementAvailable()) return;
  const response = await extensionManagementRequest(`/plan?afterRevision=${lastRevision}`) as ExtensionCatalog | { unchanged: true };
  if (epoch !== reconciliationEpoch) return;
  if ("unchanged" in response) return;
  const plan = response;
  if (plan.revision === lastRevision) return;
  const safe = extensionSafeMode() || plan.safeMode;
  const active = safe ? [] : plan.active ?? [];
  const errors = { ...getExtensionState().errors };
  delete errors.runtime;
  for (const id of Object.keys(errors)) {
    if (!active.some((item) => item.manifest.id === id)) delete errors[id];
  }
  publishExtensions({ errors });
  const selectedTheme = active.find((item) => item.manifest.id === plan.theme)?.manifest.theme ?? null;
  const selectedLayout = active.find((item) => item.manifest.id === plan.layout)?.manifest.layout ?? null;
  applyExtensionTheme(selectedTheme);
  publishExtensions({ theme: selectedTheme, layout: selectedLayout });
  for (const [id, loaded] of [...modules].reverse()) {
    if (active.some((item) => item.manifest.id === id && item.digest === loaded.digest && item.generation === loaded.generation)) continue;
    try { await loaded.dispose(); } catch (error) { report(id, error); }
    modules.delete(id);
    publishExtensions({ reloadRequired: true, running: runningModules() });
  }
  let interrupted: string | null = null;
  try { interrupted = sessionStorage.getItem(marker); } catch { /* storage may be unavailable */ }
  for (const item of active) {
    const id = item.manifest.id;
    const activationIdentity = `${item.digest}:${item.generation}`;
    if (!item.manifest.entries?.frontend || modules.has(id) || attempted.has(activationIdentity)) continue;
    if (interrupted === activationIdentity) { report(id, new Error("Previous load was interrupted. Start with ?extensions=off to recover.")); continue; }
    if (Object.keys(item.manifest.dependencies ?? {}).some((dep) => getExtensionState().errors[dep])) { report(id, new Error("A dependency failed to load")); continue; }
    attempted.add(activationIdentity);
    const owned = createExtensionContext(item);
    let module: ExtensionModule | undefined;
    try {
      try { sessionStorage.setItem(marker, activationIdentity); } catch { /* optional crash marker */ }
      const url = owned.context.assetUrl(item.manifest.entries.frontend);
      module = await boundedActivation(import(/* @vite-ignore */ url)) as ExtensionModule;
      if (epoch !== reconciliationEpoch) throw new Error("Activation superseded by a newer extension decision");
      if (typeof module.activate !== "function") throw new Error("Frontend entry must export activate(context)");
      if (module.deactivate) owned.context.track(module.deactivate);
      const cleanup = await boundedActivation(Promise.resolve(module.activate(owned.context)));
      if (typeof cleanup === "function") owned.context.track(cleanup);
      if (epoch !== reconciliationEpoch) throw new Error("Activation superseded by a newer extension decision");
      modules.set(id, { digest: item.digest, generation: item.generation, version: item.manifest.version, dispose: owned.dispose });
      const currentErrors = { ...getExtensionState().errors };
      delete currentErrors[id];
      publishExtensions({ errors: currentErrors, running: runningModules() });
    } catch (error) {
      if (epoch !== reconciliationEpoch) attempted.delete(activationIdentity);
      report(id, error);
      publishExtensions({ reloadRequired: true });
      try { await owned.dispose(); } catch (cleanupError) { report(id, cleanupError); }
    } finally {
      try { if (interrupted) sessionStorage.setItem(marker, interrupted); else sessionStorage.removeItem(marker); } catch { /* optional marker */ }
    }
  }
  if (epoch === reconciliationEpoch) lastRevision = plan.revision;
}

function report(id: string, error: unknown): void {
  publishExtensions({ errors: { ...getExtensionState().errors, [id]: String(error) } });
}

export function refreshExtensions(force = false): Promise<void> {
  if (force) {
    reconciliationEpoch++;
    lastRevision = -1;
    if (refreshing) return refreshing.then(() => refreshExtensions());
  }
  refreshing ??= reconcile().catch((error) => report("runtime", error)).finally(() => { refreshing = null; });
  return refreshing;
}

let started = false;
export function startTrustedExtensions(): void {
  if (started || extensionSafeMode()) return;
  started = true;
  void refreshExtensions();
  const refresh = () => { if (document.visibilityState === "visible") void refreshExtensions(); };
  window.addEventListener("focus", refresh);
  document.addEventListener("visibilitychange", refresh);
  // One lightweight registry read per window, independent of chart count.
  window.setInterval(refresh, 10_000);
}
