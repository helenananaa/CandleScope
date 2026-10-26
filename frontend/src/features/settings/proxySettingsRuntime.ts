import { useCallback, useEffect, useState } from "react";
import { t } from "../../i18n/index.js";
import {
  fetchProxySettings,
  fetchProxyPoolStatus,
  testProxyConnection,
  updateProxySettings,
} from "../../services/api";

export type ProxyMode = "system" | "custom" | "none" | "pool";
export interface ProxyRouteConfig extends Record<string, unknown> {
  id: string; name: string; url: string; egress_group: string;
  enabled: boolean; exchanges: string[]; max_concurrency: number;
  max_ws_subscriptions?: number;
}
export interface ProxyPoolStatus {
  routes?: Array<{ id: string; active_requests: number;
    ws_subscriptions?: number; ws_sessions?: number; max_ws_subscriptions?: number;
    native_websockets?: number; ccxt_physical_websockets?: number;
    ws_traffic?: { window_seconds: number; messages_per_second: number; payload_bytes_per_second: number;
      messages_total: number; payload_bytes_total: number; disconnects_total: number; disconnects_recent: number;
      last_message_age_seconds: number | null; queue_size: number; queue_capacity: number; queue_pressure: number };
    observations: Array<{ exchange: string; kind: string; successes: number; failures: number;
      latency_ms: number | null; cooldown_seconds: number }>;
    budgets: Record<string, { cooldown_remaining_seconds?: number; last_wait_seconds?: number;
      global_circuit?: { cooldown_remaining_seconds?: number } }>;
  }>;
}

export interface ProxyTestResult extends Record<string, unknown> {
  success?: boolean;
  partial?: boolean;
  message?: string;
  proxy_used?: string;
  data_engine?: "ready" | "not_initialized" | "not_started" | "error" | "unknown";
  results?: ProxyExchangeTestResult[];
}

export interface ProxyExchangeTestResult {
  route_id?: string;
  exchange: string;
  success: boolean;
  label: string;
  message: string;
}

export interface ProxySaveMessage {
  ok: boolean;
  text: string;
}

export interface ProxySettingsRuntime extends Record<string, unknown> {
  proxyMode: ProxyMode;
  customProxy: string;
  systemProxy: string;
  effectiveProxy: string;
  proxyLoading: boolean;
  proxyTestResult: ProxyTestResult | null;
  proxySaveMsg: ProxySaveMessage | null;
  handleProxyModeChange(mode: ProxyMode): void;
  handleCustomProxyChange(value: string): void;
  handleProxySave(): Promise<void>;
  handleProxyTest(): Promise<void>;
  proxyRoutes: ProxyRouteConfig[];
  proxySavedRoutes: ProxyRouteConfig[];
  proxyStrategy: "failover" | "balanced";
  proxyPoolStatus: ProxyPoolStatus | null;
  handleProxyRoutesChange(routes: ProxyRouteConfig[]): void;
  handleProxyStrategyChange(strategy: "failover" | "balanced"): void;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function stringField(record: Record<string, unknown>, key: string, fallback = ""): string {
  const value = record[key];
  return typeof value === "string" ? value : fallback;
}

function proxyModeField(record: Record<string, unknown>): ProxyMode {
  const value = record.mode;
  return value === "custom" || value === "none" || value === "system" || value === "pool" ? value : "system";
}

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message ? error.message : String(error);
}

export function useProxySettingsRuntime({ isOpen }: { isOpen: boolean }): ProxySettingsRuntime {
  const [proxyMode, setProxyMode] = useState<ProxyMode>("system");
  const [customProxy, setCustomProxy] = useState("");
  const [systemProxy, setSystemProxy] = useState("");
  const [effectiveProxy, setEffectiveProxy] = useState("");
  const [proxyLoading, setProxyLoading] = useState(false);
  const [proxyTestResult, setProxyTestResult] = useState<ProxyTestResult | null>(null);
  const [proxySaveMsg, setProxySaveMsg] = useState<ProxySaveMessage | null>(null);
  const [proxyRoutes, setProxyRoutes] = useState<ProxyRouteConfig[]>([]);
  const [proxySavedRoutes, setProxySavedRoutes] = useState<ProxyRouteConfig[]>([]);
  const [proxyStrategy, setProxyStrategy] = useState<"failover" | "balanced">("failover");
  const [proxyPoolStatus, setProxyPoolStatus] = useState<ProxyPoolStatus | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setProxyTestResult(null);
    setProxySaveMsg(null);
    fetchProxySettings()
      .then((data) => {
        const record = isRecord(data) ? data : {};
        setProxyMode(proxyModeField(record));
        setCustomProxy(stringField(record, "custom_proxy"));
        setSystemProxy(stringField(record, "system_proxy"));
        setEffectiveProxy(stringField(record, "effective_proxy"));
        const routes = Array.isArray(record.routes) ? record.routes as ProxyRouteConfig[] : [];
        setProxyRoutes(routes);
        setProxySavedRoutes(routes);
        setProxyStrategy(record.strategy === "balanced" ? "balanced" : "failover");
      })
      .catch(() => {});
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || proxyMode !== "pool") return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const result = await fetchProxyPoolStatus();
        if (!cancelled && isRecord(result)) setProxyPoolStatus(result as ProxyPoolStatus);
      } catch { /* Keep the last observation while the backend recovers. */ }
      if (!cancelled) timer = setTimeout(() => { void refresh(); }, 5000);
    };
    void refresh();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [isOpen, proxyMode, proxySavedRoutes]);

  const handleProxyRoutesChange = useCallback((routes: ProxyRouteConfig[]) => {
    setProxyRoutes(routes); setProxySaveMsg(null); setProxyTestResult(null);
  }, []);
  const handleProxyStrategyChange = useCallback((strategy: "failover" | "balanced") => {
    setProxyStrategy(strategy); setProxySaveMsg(null);
  }, []);

  const handleProxyModeChange = useCallback((mode: ProxyMode) => {
    setProxyMode(mode);
    setProxyTestResult(null);
    setProxySaveMsg(null);
  }, []);

  const handleCustomProxyChange = useCallback((value: string) => {
    setCustomProxy(value);
    setProxySaveMsg(null);
  }, []);

  const handleProxySave = useCallback(async () => {
    setProxyLoading(true);
    setProxySaveMsg(null);
    try {
      const res = await updateProxySettings({ mode: proxyMode, custom_proxy: customProxy,
        routes: proxyRoutes, strategy: proxyStrategy });
      const record = isRecord(res) ? res : {};
      setEffectiveProxy(stringField(record, "effective_proxy"));
      const savedRoutes = Array.isArray(record.routes) ? record.routes as ProxyRouteConfig[] : proxyRoutes;
      setProxyRoutes(savedRoutes);
      setProxySavedRoutes(savedRoutes);
      setProxyPoolStatus(null);
      setProxySaveMsg({ ok: true, text: t("settings.proxy.saved") });
    } catch (err: unknown) {
      setProxySaveMsg({
        ok: false,
        text: t("settings.proxy.saveFailed", { error: errorMessage(err) }),
      });
    } finally {
      setProxyLoading(false);
    }
  }, [proxyMode, customProxy, proxyRoutes, proxyStrategy]);

  const handleProxyTest = useCallback(async () => {
    setProxyLoading(true);
    setProxyTestResult(null);
    try {
      const res = await testProxyConnection({ mode: proxyMode, custom_proxy: customProxy,
        routes: proxyRoutes, strategy: proxyStrategy });
      setProxyTestResult(isRecord(res) ? res : {});
    } catch (err: unknown) {
      setProxyTestResult({
        success: false,
        message: t("settings.proxy.requestFailed", { error: errorMessage(err) }),
      });
    } finally {
      setProxyLoading(false);
    }
  }, [proxyMode, customProxy, proxyRoutes, proxyStrategy]);

  return {
    proxyMode,
    customProxy,
    systemProxy,
    effectiveProxy,
    proxyLoading,
    proxyTestResult,
    proxySaveMsg,
    handleProxyModeChange,
    handleCustomProxyChange,
    handleProxySave,
    handleProxyTest,
    proxyRoutes, proxySavedRoutes, proxyStrategy, proxyPoolStatus, handleProxyRoutesChange, handleProxyStrategyChange,
  };
}
