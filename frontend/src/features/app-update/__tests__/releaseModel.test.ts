import assert from "node:assert/strict";
import test from "node:test";
import { appReleaseVersion, compareVersions, newestAppRelease, releaseToOffer } from "../releaseModel.js";

const published = "2026-11-26T00:00:00Z";
const release = (tag_name: string, extra: Record<string, unknown> = {}) => ({
  tag_name, draft: false, prerelease: false, published_at: published,
  html_url: `https://github.com/helenananaa/CandleScope/releases/tag/${tag_name}`, ...extra,
});

test("only vMAJOR.MINOR.PATCH tags are app releases", () => {
  assert.equal(appReleaseVersion("v1.0.1"), "1.0.1");
  assert.equal(appReleaseVersion("v12.0.30"), "12.0.30");
  // Plugin releases share the repository: their real tags look like these.
  for (const tag of ["candlescope-plugin-pine-compat-v0.3.3", "candlescope-plugin-pyne-v0.2.0-dev.1", "pine-v0.3.3", "1.0.1", "v1.0", "v1.0.1-rc.1", "v1.0.1+build", "V1.0.1", " v1.0.1", "v1.0.1\n", "v1.0.x", null, 101]) {
    assert.equal(appReleaseVersion(tag), null, String(tag));
  }
});

test("versions compare by semver: newer, same, older and prereleases", () => {
  assert.equal(compareVersions("1.0.1", "1.0.0"), 1);
  assert.equal(compareVersions("1.1.0", "1.0.9"), 1);
  assert.equal(compareVersions("2.0.0", "1.99.99"), 1);
  assert.equal(compareVersions("1.0.10", "1.0.9"), 1, "numeric, not lexical");
  assert.equal(compareVersions("1.0.0", "1.0.0"), 0);
  assert.equal(compareVersions("0.9.9", "1.0.0"), -1);
  assert.equal(compareVersions("1.0.0", "1.0.1"), -1);
  assert.equal(compareVersions("1.1.0", "1.1.0-rc.1"), 1, "a release is newer than its own prerelease");
  assert.equal(compareVersions("1.1.0-rc.1", "1.1.0"), -1);
  assert.equal(compareVersions("1.1.0-rc.1", "1.0.9"), 1);
  assert.equal(compareVersions("1.0.0+abc", "1.0.0"), 0, "build metadata is ignored");
  assert.equal(compareVersions("unknown", "1.0.0"), null);
  assert.equal(compareVersions("1.0.0", ""), null);
});

test("the newest app release skips drafts, prereleases, unpublished entries and plugin tags", () => {
  const result = newestAppRelease([
    release("v1.2.0", { draft: true, published_at: null }),
    release("v1.1.0-rc.1", { prerelease: true }),
    release("v1.1.0", { prerelease: true }),
    release("pine-v9.9.9"),
    release("v1.0.9", { published_at: null }),
    release("v1.0.1"),
    release("v1.0.0"),
    release("pine-v0.3.3"),
    release("candlescope-plugin-pine-compat-v9.0.0"),
    release("candlescope-plugin-pyne-v0.2.0-dev.1", { prerelease: true }),
    null, "v3.0.0", { tag_name: "v4.0.0" },
  ]);
  assert.deepEqual(result, { version: "1.0.1", url: "https://github.com/helenananaa/CandleScope/releases/tag/v1.0.1" });
});

test("the newest release is found whatever the list order, and its page is built, not copied", () => {
  const result = newestAppRelease([
    release("v1.0.0"), release("v1.0.10", { html_url: "https://attacker.test/" }), release("v1.0.9"),
  ]);
  assert.deepEqual(result, { version: "1.0.10", url: "https://github.com/helenananaa/CandleScope/releases/tag/v1.0.10" });
});

test("a list with no app release has none; a response that is not a list is an error", () => {
  assert.equal(newestAppRelease([]), null);
  assert.equal(newestAppRelease([release("pine-v0.3.3"), release("v2.0.0", { draft: true })]), null);
  for (const payload of [null, {}, { message: "API rate limit exceeded" }, "[]", 42]) {
    assert.throws(() => newestAppRelease(payload), TypeError);
  }
});

test("a release is offered only when it is newer than this app and not skipped", () => {
  const newer = { version: "1.0.1", url: "https://github.com/helenananaa/CandleScope/releases/tag/v1.0.1" };
  assert.deepEqual(releaseToOffer(newer, "1.0.0", []), newer, "newer");
  assert.equal(releaseToOffer(newer, "1.0.1", []), null, "same version");
  assert.equal(releaseToOffer(newer, "1.1.0", []), null, "older than this app");
  assert.deepEqual(releaseToOffer(newer, "1.0.1-rc.2", []), newer, "this app is a prerelease of it");
  assert.equal(releaseToOffer(newer, "1.0.0", ["1.0.1"]), null, "skipped");
  assert.deepEqual(releaseToOffer(newer, "1.0.0", ["1.0.0", "1.0.2"]), newer, "another version was skipped");
  assert.equal(releaseToOffer(null, "1.0.0", []), null, "no release");
  assert.equal(releaseToOffer(newer, "unknown", []), null, "this app's version is unknown");
});
