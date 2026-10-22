import { useLayoutEffect, useRef, useState } from "react";
import type { ChartWorkspaceRuntime } from "../chart-workspace/useChartWorkspaceRuntime.js";
import { AppControlController } from "./controlController.js";
import { appCommandRegistry } from "./commandRegistry.js";

export function useAppControl(workspace: ChartWorkspaceRuntime, windowId: string): AppControlController {
  const latest = useRef(workspace);
  useLayoutEffect(() => { latest.current = workspace; }, [workspace]);
  const [controller] = useState(() => new AppControlController({
    read: () => latest.current,
    apply: (command) => latest.current.actions.applyControlCommand(command),
  }, windowId));
  useLayoutEffect(() => {
    const bridge = window.candlescopeDesktop;
    if (!bridge?.controlEnabled || !bridge.onControlRequest || !bridge.sendControlResult) return;
    controller.resume();
    const unsubscribe = bridge.onControlRequest((request) => {
      const reply = (result: Record<string, unknown>, final: boolean) => bridge.sendControlResult?.({ id: request.id, ...(request.instanceId ? { instanceId: request.instanceId } : {}), result, final });
      const execution = request.method.startsWith("app.") ? appCommandRegistry.execute(request, windowId)
        : controller.execute(request, (result) => reply(result, false));
      void execution
        .then((result) => reply(result, true))
        .catch((error: unknown) => reply({ state: "failed", code: "CONTROL_ERROR", message: error instanceof Error ? error.message : String(error) }, true));
    });
    bridge.controlReady?.();
    return () => { unsubscribe(); controller.dispose(); };
  }, [controller, windowId]);
  return controller;
}
