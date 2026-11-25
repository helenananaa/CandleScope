import { RELEASES_API_URL, newestAppRelease, type AvailableRelease } from "./releaseModel.js";

const REQUEST_TIMEOUT_MS = 15_000;

/**
 * Asks GitHub's public releases API for the newest app release. The request goes through the
 * page's own network stack, so the system proxy applies and an intercepted (non-GitHub)
 * certificate fails like any other network error. Throws on any failure; callers stay silent.
 */
export async function fetchNewestAppRelease(
  signal: AbortSignal,
  fetchImpl: typeof fetch = globalThis.fetch.bind(globalThis),
): Promise<AvailableRelease | null> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal.aborted) controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, REQUEST_TIMEOUT_MS);
  try {
    const response = await fetchImpl(RELEASES_API_URL, {
      headers: { Accept: "application/vnd.github+json" },
      cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer", signal: controller.signal,
    });
    if (!response.ok) {
      const limited = response.headers.get("x-ratelimit-remaining") === "0";
      throw new Error(`GitHub releases request failed: HTTP ${response.status}${limited ? " (rate limited)" : ""}`);
    }
    return newestAppRelease(await response.json());
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", abort);
  }
}
