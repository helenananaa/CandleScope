import { t } from "../../i18n/index.js";
import type { ExtensionState } from "./state.js";

export interface RecoveryNotice {
  tone: "info" | "warning";
  title: string;
  message: string;
}

/**
 * The extension recovery notice, or null when extensions are healthy. It appears in recovery mode
 * and when an extension failed to load. A registry read failure ("runtime") alone does not raise
 * it: that is usually a brief outage of the local service, and management shows it.
 */
export function recoveryNotice(state: Pick<ExtensionState, "errors" | "safeMode">, urlSafeMode: boolean): RecoveryNotice | null {
  if (urlSafeMode || state.safeMode) {
    return { tone: "info", title: t("extensions.notice.safeModeTitle"), message: t("extensions.notice.safeModeMessage") };
  }
  const failed = Object.keys(state.errors).filter((id) => id !== "runtime").sort();
  if (!failed.length) return null;
  return { tone: "warning", title: t("extensions.notice.failedTitle"), message: failed.join(", ") };
}
