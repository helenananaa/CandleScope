import { useEffect, useSyncExternalStore } from "react";
import { notify } from "../../components/ui/overlay/overlayApi.js";
import { t } from "../../i18n/index.js";
import { APP_VERSION } from "../../shared/appVersion.js";
import type { AvailableRelease } from "./releaseModel.js";
import { updateCheckPreferences } from "./updateCheckPreferences.js";
import { fetchNewestAppRelease } from "./updateCheckService.js";
import { startUpdateChecks } from "./updateCheckScheduler.js";

/** Only the desktop app checks: the browser build is always the current version. */
export function updateChecksSupported(): boolean {
  return typeof window !== "undefined" && Boolean(window.candlescopeDesktop);
}

/** A quiet notice that stays until closed; it never blocks the workspace. */
export function showUpdateNotice(release: AvailableRelease, skip: () => void): void {
  notify({
    tone: "info",
    title: t("appUpdate.available", { version: release.version }),
    message: t("appUpdate.current", { version: APP_VERSION }),
    // The desktop shell opens this GitHub release page in the default browser.
    action: { label: t("appUpdate.view"), onClick: () => { window.open(release.url, "_blank", "noopener,noreferrer"); } },
    secondaryAction: { label: t("appUpdate.skip"), onClick: skip },
    durationMs: 0,
  });
}

/** Checks for a newer release while `active` (the desktop app's main window). */
export function useAppUpdateCheck(active: boolean): void {
  useEffect(() => {
    if (!active) return undefined;
    return startUpdateChecks({
      currentVersion: APP_VERSION,
      preferences: updateCheckPreferences,
      fetchRelease: (signal) => fetchNewestAppRelease(signal),
      showNotice: showUpdateNotice,
      log: (message, error) => console.warn(`[update-check] ${message}`, error),
    });
  }, [active]);
}

/** The "Check for updates" setting. */
export function useUpdateCheckEnabled(): [boolean, (enabled: boolean) => void] {
  const preferences = useSyncExternalStore(updateCheckPreferences.subscribe, updateCheckPreferences.get, updateCheckPreferences.get);
  return [preferences.enabled, updateCheckPreferences.setEnabled];
}
