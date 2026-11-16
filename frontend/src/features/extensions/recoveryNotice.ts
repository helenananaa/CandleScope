import type { ExtensionState } from "./state.js";

export interface RecoveryNotice {
  tone: "info" | "warning";
  title: string;
  message: string;
}

type Text = (zh: string, en: string) => string;

/**
 * The extension recovery notice, or null when extensions are healthy. It appears in recovery mode
 * and when an extension failed to load. A registry read failure ("runtime") alone does not raise
 * it: that is usually a brief backend outage, and management shows it.
 */
export function recoveryNotice(state: Pick<ExtensionState, "errors" | "safeMode">, urlSafeMode: boolean, text: Text): RecoveryNotice | null {
  if (urlSafeMode || state.safeMode) {
    return { tone: "info", title: text("恢复模式：扩展未运行", "Recovery mode: extensions are not running"), message: text("可以在这里停用或回退扩展。", "Disable or roll back extensions here.") };
  }
  const failed = Object.keys(state.errors).filter((id) => id !== "runtime").sort();
  if (!failed.length) return null;
  return { tone: "warning", title: text("有扩展加载失败", "An extension failed to load"), message: failed.join(", ") };
}
