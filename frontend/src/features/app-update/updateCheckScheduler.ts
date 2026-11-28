import { releaseToOffer, type AvailableRelease } from "./releaseModel.js";
import type { UpdateCheckPreferencesStore } from "./updateCheckPreferences.js";

/** At most one check per this long while the app runs. */
export const UPDATE_CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000;
/** How often the 24-hour mark is looked at, so a check is not missed by much after sleep. */
const TICK_MS = 60 * 60 * 1000;

export interface UpdateCheckDependencies {
  currentVersion: string;
  preferences: UpdateCheckPreferencesStore;
  fetchRelease(signal: AbortSignal): Promise<AvailableRelease | null>;
  /** Shows the notice; `skip` remembers the version so it is never offered again. */
  showNotice(release: AvailableRelease, skip: () => void): void;
  /** Failures are logged here and never shown. */
  log(message: string, error: unknown): void;
  now?: () => number;
  setInterval?: (callback: () => void, ms: number) => unknown;
  clearInterval?: (handle: unknown) => void;
}

/**
 * Checks once now, then at most once every 24 hours, while "Check for updates" is on.
 * Turning the setting on checks right away unless a check ran in the last 24 hours.
 * A version is offered at most once per session: a closed notice stays closed until the next launch.
 * Returns a function that stops checking.
 */
export function startUpdateChecks(dependencies: UpdateCheckDependencies): () => void {
  const { currentVersion, preferences, fetchRelease, showNotice, log } = dependencies;
  const now = dependencies.now ?? Date.now;
  const controller = new AbortController();
  const offered = new Set<string>();
  let lastAttemptAt: number | null = null;
  let inFlight = false;

  const check = async () => {
    if (controller.signal.aborted || inFlight || !preferences.get().enabled) return;
    if (lastAttemptAt !== null && now() - lastAttemptAt < UPDATE_CHECK_INTERVAL_MS) return;
    lastAttemptAt = now();
    inFlight = true;
    try {
      const release = await fetchRelease(controller.signal);
      // The setting may have changed, or a version been skipped, while the request was out.
      const current = preferences.get();
      if (controller.signal.aborted || !current.enabled) return;
      const offer = releaseToOffer(release, currentVersion, current.skippedVersions);
      if (!offer || offered.has(offer.version)) return;
      offered.add(offer.version);
      showNotice(offer, () => preferences.skipVersion(offer.version));
    } catch (error) {
      if (!controller.signal.aborted) log("Update check failed; trying again in 24 hours", error);
    } finally {
      inFlight = false;
    }
  };

  void check();
  const setTimer = dependencies.setInterval ?? ((callback, ms) => globalThis.setInterval(callback, ms));
  const clearTimer = dependencies.clearInterval
    ?? ((handle) => globalThis.clearInterval(handle as ReturnType<typeof globalThis.setInterval>));
  const timer = setTimer(() => void check(), TICK_MS);
  const unsubscribe = preferences.subscribe(() => void check());
  return () => {
    controller.abort();
    clearTimer(timer);
    unsubscribe();
  };
}
