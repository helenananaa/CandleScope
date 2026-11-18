import { UnifiedEntryLifecycle, type UnifiedAppearance, type UnifiedItem, type UnifiedPlan } from "../../../desktop/unified-entry-lifecycle.mjs";
import { pluginManagementAvailable, unifiedAssetBase, unifiedBackgroundRequest } from "../plugins/pluginPlatformApi.js";
import { createExtensionContext, loadUnifiedFrontend } from "./runtime.js";
import { applyExtensionTheme, extensionSafeMode, getExtensionState, publishExtensions } from "./state.js";
import { pluginChartOwner, type PluginChartScope } from "../plugins/unifiedChartContext.js";

const listeners = new Set<() => void>();
let snapshot = { revision: 0, restartRequired: false, errors: {} as Record<string, string>, views: [] as UnifiedItem[] };
const views = new Map<string, UnifiedItem>();
const startupInstances = new Set<string>();
const loading = new Set<string>();
function startupMarker(item: UnifiedItem): string {
  return `candlescope-unified-loading:${item.pluginId}:${item.entry.id}`;
}
function activationKey(item: UnifiedItem): string {
  return `${item.identity.packageSha256}:${item.identity.generation}`;
}
export const getUnifiedState = () => snapshot;
export const subscribeUnified = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
function changed() {
  snapshot = { revision: snapshot.revision + 1, restartRequired: host.restartRequired, errors: { ...host.errors }, views: [...views.values()] };
  for (const listener of listeners) listener();
}

export function parseUnifiedPlan(value: unknown, validateAssets = unifiedAssetBase): UnifiedPlan {
  if (!value || typeof value !== "object") throw new Error("Invalid plugin plan");
  const plan = value as UnifiedPlan;
  if (typeof plan.sessionId !== "string" || typeof plan.hostInstance !== "string" || !Array.isArray(plan.entries) || plan.entries.length > 256) throw new Error("Invalid plugin plan");
  const instances = new Set<string>();
  let shellClaimed = false;
  for (const item of plan.entries) {
    if (!item || !item.manifest || !item.entry || !item.identity || item.manifest.schema !== "candlescope.unified-plugin/1"
      || item.manifest.hostApiVersion !== 1 || !["restricted", "full-trust"].includes(item.manifest.trust)
      || item.pluginId !== item.identity.pluginId || item.pluginId !== item.manifest.id || item.manifest.version !== item.identity.version
      || !Number.isSafeInteger(item.identity.generation) || item.identity.generation < 1
      || !/^sha256:[a-f0-9]{64}$/.test(item.identity.packageSha256) || !/^[a-f0-9]{32}$/.test(item.instanceId)
      || instances.has(item.instanceId) || !["frontend", "sandbox-view"].includes(item.entry.kind)
      || item.entry.kind === "frontend" && item.manifest.trust !== "full-trust") throw new Error("Invalid plugin entry identity or trust");
    validateAssets(item.assetBase);
    if (!/^[A-Za-z0-9_./-]+$/.test(item.entry.path) || item.entry.path.split("/").some((part) => !part || part === "." || part === "..")) throw new Error("Invalid plugin entry path");
    const targets = item.entry.startup;
    if (targets !== undefined && (!Array.isArray(targets) || targets.length > 1
      || targets.length === 1 && (targets[0] !== "shell" || item.entry.kind !== "frontend" || shellClaimed))) {
      throw new Error("Invalid startup shell claim");
    }
    if (targets?.length) shellClaimed = true;
    instances.add(item.instanceId);
  }
  return plan;
}

const host = new UnifiedEntryLifecycle({
  changed,
  async load(item) {
    if (item.entry.kind === "sandbox-view") return { activate() {
      views.set(item.instanceId, item); changed();
      return () => { views.delete(item.instanceId); changed(); };
    } };
    const marker = startupMarker(item);
    const identity = activationKey(item);
    if (sessionStorage.getItem(marker) === identity) throw new Error("Previous plugin startup was interrupted");
    sessionStorage.setItem(marker, identity);
    loading.add(item.instanceId);
    return loadUnifiedFrontend(`${unifiedAssetBase(item.assetBase)}${item.entry.path}`);
  },
  createContext(item, guard) {
    if (item.entry.kind === "sandbox-view") {
      const cleanups: (() => void)[] = [];
      return { context: { track(cleanup: () => void) { cleanups.push(cleanup); } }, dispose() { for (const cleanup of cleanups.reverse()) cleanup(); } };
    }
    const owned = createExtensionContext({ manifest: { id: item.pluginId, internalApiVersion: 1 }, assetBase: item.assetBase }, guard, unifiedAssetBase, async () => {
      await unifiedBackgroundRequest("/check", { sessionId: currentPlan?.sessionId, instanceId: item.instanceId });
    }, (name) => name !== "shell" || startupInstances.has(item.instanceId));
    Object.assign(owned.context, {
      identity: item.identity, entryId: item.entry.id, instanceId: item.instanceId,
      charts: {
        list() {
          guard();
          return pluginChartOwner.list();
        },
        isCurrent(scope: PluginChartScope) {
          guard();
          return pluginChartOwner.isCurrent(scope);
        },
        async invoke(scope: PluginChartScope, entryId: string, input: unknown) {
          guard();
          if (!currentPlan) throw new Error("Plugin window is unavailable");
          const result = await pluginChartOwner.invoke(scope, {
            sessionId: currentPlan.sessionId, frontendInstanceId: item.instanceId, entryId,
          }, input);
          guard();
          if (result.identity.pluginId !== item.identity.pluginId || result.identity.generation !== item.identity.generation
            || result.identity.packageSha256 !== item.identity.packageSha256 || result.identity.version !== item.identity.version) {
            throw new Error("Plugin activation changed");
          }
          return result;
        },
      },
    });
    return owned;
  },
  report: reportEntry,
});

async function reportEntry(plan: UnifiedPlan, item: UnifiedItem, state: string, error?: string) {
  const marker = startupMarker(item);
  if (state !== "pending-restart" && loading.delete(item.instanceId)
    && sessionStorage.getItem(marker) === activationKey(item)) {
    sessionStorage.removeItem(marker);
  }
  return await unifiedBackgroundRequest("/report", { sessionId: plan.sessionId, instanceId: item.instanceId,
    state: item.entry.kind === "sandbox-view" && state === "running" ? "ready" : state, ...(error ? { error } : {}) });
}
let started = false;
let refreshing: Promise<void> | null = null;
let currentPlan: UnifiedPlan | null = null;
export function refreshUnified(): Promise<void> {
  return syncPlan(false);
}

export function prepareUnifiedShell(): Promise<void> {
  if (extensionSafeMode()) return Promise.resolve();
  return syncPlan(true);
}

function applyAppearance(appearance: UnifiedAppearance | undefined, safeMode: boolean): void {
  const { theme, layout } = safeMode || !appearance ? { theme: null, layout: null } : appearance;
  const state = getExtensionState();
  if (JSON.stringify(state.theme) !== JSON.stringify(theme)) applyExtensionTheme(theme);
  if (JSON.stringify(state.theme) !== JSON.stringify(theme) || JSON.stringify(state.layout) !== JSON.stringify(layout) || state.safeMode !== safeMode) {
    publishExtensions({ theme, layout, safeMode });
  }
}

function syncPlan(beforeRender: boolean): Promise<void> {
  if (!pluginManagementAvailable()) return Promise.resolve();
  refreshing ??= (async () => {
    const plan = parseUnifiedPlan(await unifiedBackgroundRequest("/realm", { clientId: pluginChartOwner.id, realm: "frontend" }));
    host.errors = { ...host.errors, ...plan.errors };
    currentPlan = plan;
    if (extensionSafeMode() || plan.safeMode) {
      applyAppearance(undefined, true);
      await host.reconcile({ ...plan, safeMode: true, entries: [] });
      return;
    }
    const startupPackages = new Set(plan.entries.filter((item) => item.entry.startup?.length).map((item) => item.pluginId));
    if (beforeRender) {
      // The owner orders providers first. Walk backwards to collect transitive dependencies.
      for (const item of [...plan.entries].reverse()) {
        if (startupPackages.has(item.pluginId)) {
          for (const dependency of Object.keys(item.manifest.dependencies ?? {})) startupPackages.add(dependency);
        }
      }
    }
    const entries = [];
    for (const item of plan.entries) {
      if (!item.entry.startup?.length) {
        if (!beforeRender || item.entry.kind === "frontend" && startupPackages.has(item.pluginId)) entries.push(item);
      } else if (beforeRender || startupInstances.has(item.instanceId)) {
        if (beforeRender) startupInstances.add(item.instanceId);
        entries.push(item);
      } else {
        await reportEntry(plan, item, "pending-restart");
      }
    }
    await host.reconcile({ ...plan, entries });
    applyAppearance(plan.appearance, false);
  })().catch((error: unknown) => { host.errors.runtime = String(error); changed(); }).finally(() => { refreshing = null; });
  return refreshing;
}
export function startUnified(): void {
  if (started) return;
  started = true;
  void refreshUnified();
  window.addEventListener("focus", () => { void refreshUnified(); });
  window.setInterval(() => { void refreshUnified(); }, 5000);
}
export function reportUnifiedView(item: UnifiedItem, state: "running" | "ready"): void {
  if (!currentPlan || !host.current(item)) return;
  void unifiedBackgroundRequest("/report", { sessionId: currentPlan.sessionId, instanceId: item.instanceId, state }).catch(() => undefined);
}
