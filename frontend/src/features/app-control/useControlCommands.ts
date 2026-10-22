import { useLayoutEffect, useRef } from "react";
import { appCommandRegistry, type ControlCommandGroup } from "./commandRegistry.js";

export function useControlCommands(input: ControlCommandGroup | (() => ControlCommandGroup), enabled = true): void {
  const group = enabled && typeof window !== "undefined" && window.candlescopeDesktop?.controlEnabled ? (typeof input === "function" ? input() : input) : null;
  const latest = useRef(group);
  const groupId = group?.id, title = group?.title;
  useLayoutEffect(() => { latest.current = group; });
  useLayoutEffect(() => {
    if (!groupId || !title) return;
    return appCommandRegistry.register({ id: groupId, title,
      context: () => latest.current!.context(), snapshot: () => latest.current!.snapshot(),
      get commands() { return latest.current!.commands; } });
  }, [groupId, title]);
}

/** Non-workspace pages share the same authenticated bridge and command registry. */
let pageBridgeUsers = 0;
let pageBridgeUnsubscribe: (() => void) | undefined;
export function usePageControlBridge(): void {
  useLayoutEffect(() => {
    const bridge = window.candlescopeDesktop;
    if (!bridge?.controlEnabled || !bridge.onControlRequest || !bridge.sendControlResult) return;
    if (pageBridgeUsers++ === 0) {
      const windowId = bridge.controlWindowId ?? new URLSearchParams(window.location.search).get("windowId") ?? "main-window";
      pageBridgeUnsubscribe = bridge.onControlRequest((request) => {
        void appCommandRegistry.execute(request, windowId).then((result) => bridge.sendControlResult?.({ id: request.id, ...(request.instanceId ? { instanceId: request.instanceId } : {}), result, final: true }));
      });
      bridge.controlReady?.();
    }
    return () => { if (--pageBridgeUsers === 0) { pageBridgeUnsubscribe?.(); pageBridgeUnsubscribe = undefined; } };
  }, []);
}
