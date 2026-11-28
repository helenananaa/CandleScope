import assert from "node:assert/strict";
import test from "node:test";
import type { AvailableRelease } from "../releaseModel.js";
import { createUpdateCheckPreferences } from "../updateCheckPreferences.js";
import { UPDATE_CHECK_INTERVAL_MS, startUpdateChecks } from "../updateCheckScheduler.js";
import type { StorageLike } from "../../../shared/browserStorage.js";

const HOUR = 60 * 60 * 1000;
const v101: AvailableRelease = { version: "1.0.1", url: "https://github.com/helenananaa/CandleScope/releases/tag/v1.0.1" };

function memoryStorage(initial: Record<string, string> = {}): StorageLike & { data: Record<string, string> } {
  const data = { ...initial };
  return { data, getItem: (key) => data[key] ?? null, setItem: (key, value) => { data[key] = value; } };
}

const settle = () => new Promise<void>((resolve) => setImmediate(resolve));

function harness({ storage = memoryStorage(), release = v101 as AvailableRelease | null | Error, currentVersion = "1.0.0" } = {}) {
  let clock = 0;
  let tick: (() => void) | null = null;
  const preferences = createUpdateCheckPreferences(() => storage);
  const notices: { release: AvailableRelease; skip: () => void }[] = [];
  const logs: unknown[] = [];
  let requests = 0;
  let response: AvailableRelease | null | Error = release;
  const stop = startUpdateChecks({
    currentVersion, preferences,
    fetchRelease: async () => { requests++; if (response instanceof Error) throw response; return response; },
    showNotice: (offer, skip) => notices.push({ release: offer, skip }),
    log: (_message, error) => logs.push(error),
    now: () => clock,
    setInterval: (callback) => { tick = callback; return 1; },
    clearInterval: () => { tick = null; },
  });
  return {
    storage, preferences, notices, logs, stop,
    get requests() { return requests; },
    respond(next: AvailableRelease | null | Error) { response = next; },
    async advance(ms: number) { clock += ms; tick?.(); await settle(); },
    get ticking() { return tick !== null; },
  };
}

test("checks at startup and shows a notice for a newer release", async () => {
  const h = harness();
  await settle();
  assert.equal(h.requests, 1);
  assert.deepEqual(h.notices.map((notice) => notice.release), [v101]);
  h.stop();
});

test("no notice for the same or an older version", async () => {
  for (const currentVersion of ["1.0.1", "1.0.2"]) {
    const h = harness({ currentVersion });
    await settle();
    assert.equal(h.requests, 1);
    assert.equal(h.notices.length, 0, currentVersion);
    h.stop();
  }
});

test("then checks at most once every 24 hours", async () => {
  const h = harness({ release: null });
  await settle();
  await h.advance(HOUR);
  await h.advance(UPDATE_CHECK_INTERVAL_MS - 2 * HOUR);
  assert.equal(h.requests, 1, "not yet 24 hours");
  await h.advance(HOUR);
  assert.equal(h.requests, 2, "24 hours after the first check");
  await h.advance(HOUR);
  assert.equal(h.requests, 2);
  h.stop();
  assert.equal(h.ticking, false);
});

test("with Check for updates off, nothing is requested until it is turned on", async () => {
  const storage = memoryStorage({ "candlescope-update-check": JSON.stringify({ enabled: false, skippedVersions: [] }) });
  const h = harness({ storage });
  await settle();
  await h.advance(UPDATE_CHECK_INTERVAL_MS * 2);
  assert.equal(h.requests, 0);
  assert.equal(h.notices.length, 0);
  h.preferences.setEnabled(true);
  await settle();
  assert.equal(h.requests, 1, "turning it on checks right away");
  assert.equal(h.notices.length, 1);
  assert.deepEqual(JSON.parse(storage.data["candlescope-update-check"]!), { enabled: true, skippedVersions: [] });
  h.stop();
});

test("turning the setting off while a check is out drops its notice", async () => {
  const h = harness();
  h.preferences.setEnabled(false);
  await settle();
  assert.equal(h.requests, 1);
  assert.equal(h.notices.length, 0);
  h.stop();
});

test("turning it back on within 24 hours does not check again", async () => {
  const h = harness({ release: null });
  await settle();
  h.preferences.setEnabled(false);
  h.preferences.setEnabled(true);
  await settle();
  assert.equal(h.requests, 1);
  h.stop();
});

test("skip this version is remembered for that version only", async () => {
  const storage = memoryStorage();
  const first = harness({ storage });
  await settle();
  assert.equal(first.notices.length, 1);
  first.notices[0]!.skip();
  first.stop();
  assert.deepEqual(JSON.parse(storage.data["candlescope-update-check"]!), { enabled: true, skippedVersions: ["1.0.1"] });

  const relaunched = harness({ storage });
  await settle();
  assert.equal(relaunched.requests, 1);
  assert.equal(relaunched.notices.length, 0, "the skipped version is not offered again");
  relaunched.respond({ version: "1.0.2", url: "https://github.com/helenananaa/CandleScope/releases/tag/v1.0.2" });
  await relaunched.advance(UPDATE_CHECK_INTERVAL_MS);
  assert.deepEqual(relaunched.notices.map((notice) => notice.release.version), ["1.0.2"], "a newer version is");
  relaunched.stop();
});

test("a version is noticed once per session; the next launch shows it again", async () => {
  const storage = memoryStorage();
  const h = harness({ storage });
  await settle();
  await h.advance(UPDATE_CHECK_INTERVAL_MS);
  assert.equal(h.requests, 2);
  assert.equal(h.notices.length, 1, "closing it keeps it closed for this session");
  h.stop();
  const relaunched = harness({ storage });
  await settle();
  assert.equal(relaunched.notices.length, 1);
  relaunched.stop();
});

test("failures are logged, never shown, and retried after 24 hours", async () => {
  const h = harness({ release: new TypeError("Failed to fetch") });
  await settle();
  assert.equal(h.notices.length, 0);
  assert.equal(h.logs.length, 1);
  assert.match(String(h.logs[0]), /Failed to fetch/);
  h.respond(v101);
  await h.advance(UPDATE_CHECK_INTERVAL_MS);
  assert.equal(h.notices.length, 1);
  h.stop();
});

test("stopping aborts a pending check without a log or notice", async () => {
  const preferences = createUpdateCheckPreferences(() => memoryStorage());
  const logs: unknown[] = [];
  const notices: unknown[] = [];
  const stop = startUpdateChecks({
    currentVersion: "1.0.0", preferences,
    fetchRelease: (signal) => new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")))),
    showNotice: (release) => notices.push(release), log: (_message, error) => logs.push(error),
    setInterval: () => 1, clearInterval: () => undefined,
  });
  stop();
  await settle();
  assert.deepEqual([logs.length, notices.length], [0, 0]);
});
