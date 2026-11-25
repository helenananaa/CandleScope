import assert from "node:assert/strict";
import test from "node:test";
import { RELEASES_API_URL } from "../releaseModel.js";
import { createUpdateCheckPreferences } from "../updateCheckPreferences.js";
import { fetchNewestAppRelease } from "../updateCheckService.js";

const json = (body: unknown, init: ResponseInit = {}) => new Response(JSON.stringify(body), { status: 200, ...init });

test("asks GitHub's releases list without credentials and reads the newest app release", async () => {
  let seen: { url: string; init: RequestInit | undefined } | null = null;
  const result = await fetchNewestAppRelease(new AbortController().signal, async (input, init) => {
    seen = { url: String(input), init };
    return json([
      { tag_name: "pine-v0.3.4", draft: false, prerelease: false, published_at: "2026-11-27T00:00:00Z" },
      { tag_name: "v1.0.1", draft: false, prerelease: false, published_at: "2026-11-27T00:00:00Z" },
    ]);
  });
  assert.deepEqual(result, { version: "1.0.1", url: "https://github.com/helenananaa/CandleScope/releases/tag/v1.0.1" });
  assert.equal(seen!.url, RELEASES_API_URL);
  assert.equal(seen!.init?.credentials, "omit");
  assert.equal(seen!.init?.referrerPolicy, "no-referrer");
});

test("rate limits, HTTP errors, bad JSON and network failures reject for the caller to log", async () => {
  const signal = new AbortController().signal;
  await assert.rejects(fetchNewestAppRelease(signal, async () => json({ message: "API rate limit exceeded" }, {
    status: 403, headers: { "x-ratelimit-remaining": "0" } })), /HTTP 403 \(rate limited\)/);
  await assert.rejects(fetchNewestAppRelease(signal, async () => json({}, { status: 502 })), /HTTP 502/);
  await assert.rejects(fetchNewestAppRelease(signal, async () => new Response("<html>captive portal</html>")), SyntaxError);
  await assert.rejects(fetchNewestAppRelease(signal, async () => json({ releases: [] })), TypeError);
  await assert.rejects(fetchNewestAppRelease(signal, async () => { throw new TypeError("net::ERR_CERT_AUTHORITY_INVALID"); }), /ERR_CERT/);
});

test("the caller's abort cancels the request", async () => {
  const controller = new AbortController();
  const pending = fetchNewestAppRelease(controller.signal, (_input, init) => new Promise((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
  }));
  controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
});

test("preferences default to on, survive bad storage and keep each skipped version once", () => {
  assert.deepEqual(createUpdateCheckPreferences(() => null).get(), { enabled: true, skippedVersions: [] });
  const data: Record<string, string> = { "candlescope-update-check": "{not json" };
  const storage = { getItem: (key: string) => data[key] ?? null, setItem: (key: string, value: string) => { data[key] = value; } };
  const preferences = createUpdateCheckPreferences(() => storage);
  assert.deepEqual(preferences.get(), { enabled: true, skippedVersions: [] });
  let changes = 0;
  preferences.subscribe(() => changes++);
  preferences.skipVersion("1.0.1");
  preferences.skipVersion("1.0.1");
  preferences.setEnabled(false);
  preferences.setEnabled(false);
  assert.equal(changes, 2);
  assert.deepEqual(createUpdateCheckPreferences(() => storage).get(), { enabled: false, skippedVersions: ["1.0.1"] });
  const throwing = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  const memoryOnly = createUpdateCheckPreferences(() => throwing);
  memoryOnly.setEnabled(false);
  assert.equal(memoryOnly.get().enabled, false, "kept for the session when storage is blocked");
});
