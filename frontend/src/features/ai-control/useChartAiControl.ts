import { useLayoutEffect, useState } from "react";
import type { ChartWorkspaceRuntime } from "../chart-workspace/useChartWorkspaceRuntime.js";
import { ChartControlAdapter, type ReplayControlAdapter } from "./chartControlAdapter.js";
import { desktopWindowManager } from "../../desktop/desktopWindowManager.js";

export function useChartAiControl(workspace: ChartWorkspaceRuntime, kind: "market" | "replay", replay?: ReplayControlAdapter) {
  const [adapter] = useState(() => {
    const bridge = globalThis.window?.candlescopeDesktop;
    return bridge?.aiControlPublish && bridge.aiControlReply ? new ChartControlAdapter({
      aiControlPublish: bridge.aiControlPublish, aiControlReply: bridge.aiControlReply,
    }) : null;
  });
  useLayoutEffect(() => {
    const bridge = globalThis.window?.candlescopeDesktop;
    if (!adapter || !bridge?.onAiControlRequest) return;
    const unsubscribe = bridge.onAiControlRequest((request) => { void adapter.handle(request); });
    return () => { unsubscribe(); adapter.close(); };
  }, [adapter]);
  useLayoutEffect(() => { adapter?.update(workspace, desktopWindowManager.windowId, kind, replay); });
}
