import { useCallback, useEffect, useRef, useState } from "react";
import type { PluginManagementDetail, PluginPlatformRuntime } from "./pluginPlatformTypes.js";

/** A response may only update the selection and request generation that issued it. */
export function usePluginDetail(runtime: PluginPlatformRuntime, pluginId: string | null) {
  const [result, setResult] = useState<{ id: string; detail: PluginManagementDetail | null; error: string | null; loading: boolean } | null>(null);
  const generation = useRef(0);
  const target = useRef<{ id: string | null; available: boolean } | null>(null);
  const load = runtime.actions.loadDetail;
  const available = runtime.view.managementAvailable;
  const reload = useCallback(async () => {
    // A mutation can finish after its detail component has been replaced.
    // Its old reload callback must not invalidate the new selection's request.
    if (target.current?.id !== pluginId || target.current.available !== available) return;
    const request = ++generation.current;
    if (!pluginId || !available) { setResult(null); return; }
    setResult((previous) => ({ id: pluginId, detail: previous?.id === pluginId ? previous.detail : null, error: null, loading: true }));
    try {
      const detail = await load(pluginId);
      if (request === generation.current) setResult({ id: pluginId, detail, error: null, loading: false });
    } catch (error) {
      if (request === generation.current) setResult((previous) => ({ id: pluginId, detail: previous?.id === pluginId ? previous.detail : null, error: error instanceof Error ? error.message : String(error), loading: false }));
    }
  }, [pluginId, available, load]);
  useEffect(() => {
    target.current = { id: pluginId, available };
    void reload();
    return () => { target.current = null; generation.current += 1; };
  }, [reload, pluginId, available]);
  const current = result?.id === pluginId && available ? result : null;
  return { detail: current?.detail ?? null, loading: current?.loading ?? false, error: current?.error ?? null, reload };
}
