import type { ExtensionRecord, RunningExtension } from "./contracts.js";

export function extensionRuntimeStatus(item: ExtensionRecord, realm: "frontend" | "backend" | "desktop",
  active: RunningExtension[] | undefined, error: string | undefined, safe: boolean) {
  const running = active?.find((entry) => entry.id === item.manifest.id);
  const wanted = item.enabled && Boolean(item.manifest.entries?.[realm]);
  if (safe) return "safe-mode";
  if (active === undefined) return "unavailable";
  if (running && !wanted) return "pending-stop";
  if (running && (running.digest !== item.digest || running.generation !== item.generation)) return "pending-restart";
  if (error) return "failed";
  if (running) return "running";
  return wanted ? "pending-start" : "stopped";
}
