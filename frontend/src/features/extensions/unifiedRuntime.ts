import { UnifiedEntryLifecycle, type UnifiedItem, type UnifiedPlan } from "../../../desktop/unified-entry-lifecycle.mjs";
import { pluginManagementAvailable, unifiedAssetBase, unifiedBackgroundRequest } from "../plugins/pluginPlatformApi.js";
import { createExtensionContext, loadUnifiedFrontend } from "./runtime.js";
import { extensionSafeMode } from "./state.js";

const listeners = new Set<() => void>();
let snapshot = { revision: 0, restartRequired: false, errors: {} as Record<string, string>, views: [] as UnifiedItem[] };
const views = new Map<string, UnifiedItem>();
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
    instances.add(item.instanceId);
  }
  return plan;
}

const host = new UnifiedEntryLifecycle({
  changed,
  load(item) {
    if (item.entry.kind === "sandbox-view") return { activate() {
      views.set(item.instanceId, item); changed();
      return () => { views.delete(item.instanceId); changed(); };
    } };
    return loadUnifiedFrontend(`${unifiedAssetBase(item.assetBase)}${item.entry.path}`);
  },
  createContext(item, guard) {
    if (item.entry.kind === "sandbox-view") {
      const cleanups: (() => void)[] = [];
      return { context: { track(cleanup: () => void) { cleanups.push(cleanup); } }, dispose() { for (const cleanup of cleanups.reverse()) cleanup(); } };
    }
    const owned = createExtensionContext({ manifest: { id: item.pluginId, internalApiVersion: 1 }, assetBase: item.assetBase }, guard, unifiedAssetBase, async () => {
      await unifiedBackgroundRequest("/check", { sessionId: currentPlan?.sessionId, instanceId: item.instanceId });
    });
    Object.assign(owned.context, { identity: item.identity, entryId: item.entry.id, instanceId: item.instanceId });
    return owned;
  },
  report(plan, item, state, error) {
    return unifiedBackgroundRequest("/report", { sessionId: plan.sessionId, instanceId: item.instanceId,
      state: item.entry.kind === "sandbox-view" && state === "running" ? "ready" : state, ...(error ? { error } : {}) });
  },
});
let clientId = "";
let started = false;
let refreshing: Promise<void> | null = null;
let currentPlan: UnifiedPlan | null = null;
export function refreshUnified(): Promise<void> {
  if (!pluginManagementAvailable()) return Promise.resolve();
  clientId ||= crypto.randomUUID();
  refreshing ??= (async () => {
    const plan = parseUnifiedPlan(await unifiedBackgroundRequest("/realm", { clientId, realm: "frontend" }));
    host.errors = { ...host.errors, ...plan.errors };
    currentPlan = plan;
    await host.reconcile(extensionSafeMode() ? { ...plan, safeMode: true, entries: [] } : plan);
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
