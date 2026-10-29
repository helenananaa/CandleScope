import { desktopWindowManager } from "../../desktop/desktopWindowManager.js";
import type { DesktopWindowLifecycleEvent } from "../../desktop/desktopWindowManager.js";

interface VisibilitySources {
  document?: Pick<Document, "visibilityState" | "addEventListener" | "removeEventListener">;
  desktop: {
    readonly windowId: string;
    onLifecycle(listener: (event: DesktopWindowLifecycleEvent) => void): () => void;
  };
}

/** Native minimization need not change document.visibilityState on macOS. */
export function observeMarketWindowVisibility(
  listener: (visible: boolean) => void,
  sources: VisibilitySources = {
    ...(typeof document === "undefined" ? {} : { document }),
    desktop: desktopWindowManager,
  },
): () => void {
  let nativeVisible = true;
  let previous: boolean | undefined;
  let active = true;
  const publish = () => {
    const visible = nativeVisible && sources.document?.visibilityState !== "hidden";
    if (!active || visible === previous) return;
    previous = visible;
    listener(visible);
  };
  const release = sources.desktop.onLifecycle((event) => {
    if (event.windowId !== sources.desktop.windowId) return;
    nativeVisible = event.visible && !event.minimized && event.state !== "hidden";
    publish();
  });
  sources.document?.addEventListener("visibilitychange", publish);
  publish();
  return () => {
    if (!active) return;
    active = false;
    sources.document?.removeEventListener("visibilitychange", publish);
    release();
  };
}
