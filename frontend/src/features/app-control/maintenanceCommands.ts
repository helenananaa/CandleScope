import type { SettingsRuntime } from "../settings/useSettingsRuntime.js";
import { command, type ControlCommandGroup } from "./commandRegistry.js";
import { array, bool, choice, empty, number, object, optional, text } from "./commandSchema.js";

function publicProxy(value: string): string {
  try { const url = new URL(value); url.username = ""; url.password = ""; return url.href; } catch { return value ? "[configured]" : ""; }
}
export function maintenanceCommands(id: string, runtime: SettingsRuntime, backendEnabled: boolean): ControlCommandGroup {
  const { view: v, actions: a } = runtime;
  const d = v.cacheDiagnostics;
  const state = () => ({ proxy: { mode: v.proxy.proxyMode, customProxy: publicProxy(v.proxy.customProxy), effectiveProxy: publicProxy(v.proxy.effectiveProxy), loading: v.proxy.proxyLoading,
    strategy: v.proxy.proxyStrategy, routes: v.proxy.proxyRoutes?.map((route) => ({ ...route, url: publicProxy(route.url) })), saved: v.proxy.proxySaveMsg },
    exchanges: v.exchanges.supportedExchanges, checks: v.exchanges.exchangeConnectionChecks, exchangeError: v.exchanges.exchangeListError,
    cache: { frontend: d.frontendDiagnostics, backend: d.backendDiagnostics, frontendPlan: d.frontendGcPlan, memoryPlan: d.backendMemoryGcPlan, storagePlan: d.storageGcPlan,
      frontendResult: d.frontendGcResult, memoryResult: d.backendMemoryGcResult, storageResult: d.storageGcResult, vacuumResult: d.storageVacuumResult, loading: d.loading, error: d.error },
    maintenance: { scope: v.maintenance.maintenanceScope, current: v.maintenance.currentScopeSymbols, watchlist: v.maintenance.watchlistScopeSymbols, repair: v.maintenance.storageRepairResult,
      repairLoading: v.maintenance.storageRepairLoading, gap: v.maintenance.gapScanResult, gapLoading: v.maintenance.gapScanLoading, refresh: v.maintenance.exchangeRefreshResult } });
  const available = () => backendEnabled;
  const confirm = object({ confirmed: choice([true] as const) });
  return { id: `maintenance:${id}`, title: "Settings network, exchanges and cache maintenance", context: state, snapshot: state, commands: [
    command("proxyMode", "Edit proxy mode; save separately.", object({ mode: choice(["system", "custom", "none", "pool"]) }), ({ mode }) => a.proxy.onProxyModeChange(mode), { available }),
    command("proxyUrl", "Edit custom proxy URL. Credentials are never returned by inspect.", object({ url: text(2048) }), ({ url }) => { const u = new URL(url); if (!["http:", "https:", "socks5:", "socks5h:"].includes(u.protocol)) throw new Error("INVALID_PROXY"); a.proxy.onCustomProxyChange(url); }, { available }),
    command("proxyRoutes", "Edit typed proxy routes and scheduling strategy.", object({ strategy: choice(["failover", "balanced"]), routes: array(object({ id: text(96), name: text(128), url: text(2048), egress_group: text(128), enabled: bool, exchanges: array(text(96), 128), max_concurrency: number(1, 10000, true), max_ws_subscriptions: optional(number(0, 100000, true)) }), 64) }), ({ strategy, routes }) => {
      for (const route of routes) { const url = new URL(route.url); if (!["http:", "https:", "socks5:", "socks5h:"].includes(url.protocol)) throw new Error("INVALID_PROXY"); }
      if (new Set(routes.map((route) => route.id)).size !== routes.length) throw new Error("DUPLICATE_ROUTE");
      a.proxy.onProxyRoutesChange?.(routes); a.proxy.onProxyStrategyChange?.(strategy);
    }, { available }),
    command("proxyTest", "Test the current proxy draft through the UI action.", empty, () => a.proxy.onProxyTest(), { available }),
    command("proxySave", "Save the current proxy draft.", empty, () => a.proxy.onProxySave(), { available }),
    command("exchangeRefresh", "Refresh supported exchange catalog.", empty, () => a.exchanges.onRefreshExchanges(), { available }),
    command("exchangeTest", "Test a listed exchange/market pair.", object({ exchange: text(96), marketType: choice(["spot", "futures"]) }), ({ exchange, marketType }) => {
      if (!v.exchanges.supportedExchanges.some((row) => row.id === exchange)) throw new Error("EXCHANGE_UNAVAILABLE"); return a.exchanges.onTestExchangeMarket(exchange, marketType);
    }, { available }),
    command("diagnostics", "Refresh cache diagnostics.", empty, () => a.cacheDiagnostics.onRefresh(), { available }),
    command("planFrontendGc", "Plan frontend GC without executing it.", empty, () => a.cacheDiagnostics.onPlanFrontendGc()),
    command("planMemoryGc", "Plan backend memory GC without executing it.", empty, () => a.cacheDiagnostics.onPlanBackendMemoryGc(), { available }),
    command("planStorageGc", "Plan storage GC without executing it.", empty, () => a.cacheDiagnostics.onPlanStorageGc(), { available }),
    command("runFrontendGc", "Execute the inspected frontend plan with explicit confirmation and context guard.", confirm, () => a.cacheDiagnostics.onRunFrontendGc(), { available: () => !!d.frontendGcPlan && !d.loading }),
    command("runMemoryGc", "Run backend memory GC after inspection; the UI service revalidates current policy.", confirm, () => a.cacheDiagnostics.onRunBackendMemoryGc(), { available: () => backendEnabled && !!d.backendMemoryGcPlan && !d.loading }),
    command("runStorageGc", "Run storage GC after inspection; the UI service revalidates current policy and references.", confirm, () => a.cacheDiagnostics.onRunStorageGc(), { available: () => backendEnabled && !!d.storageGcPlan && !d.loading }),
    command("vacuum", "Compact storage through the existing maintenance action.", confirm, () => a.cacheDiagnostics.onVacuumStorage(), { available: () => backendEnabled && !d.loading }),
    command("repair", "Repair current/watchlist storage through the existing UI workflow.", object({ scope: choice(["current", "watchlist"]), confirmed: choice([true] as const) }), ({ scope }) => a.maintenance.onStorageRepair(scope), { available: () => backendEnabled && !v.maintenance.storageRepairLoading }),
    command("gapScan", "Scan/fill gaps in current/watchlist data.", object({ scope: choice(["current", "watchlist"]) }), ({ scope }) => a.maintenance.onGapScan(scope), { available: () => backendEnabled && !v.maintenance.gapScanLoading }),
    command("refreshExchangeData", "Refresh current exchange data.", empty, () => a.maintenance.onExchangeRefresh(), { available: () => backendEnabled && !v.maintenance.exchangeRefreshLoading }),
  ] };
}
