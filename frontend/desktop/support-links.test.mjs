import assert from "node:assert/strict";
import test from "node:test";
import { isSupportLink } from "./support-links.mjs";

test("support external links only allow exact HTTPS project destinations", () => {
  const base = "https://github.com/helenananaa/CandleScope";
  for (const suffix of ["", "#readme", "/releases", "/releases/tag/v1.0.1", "/releases/tag/v12.0.30",
    "/blob/main/LICENSE", "/issues/new?body=hello%0Aworld"]) {
    assert.equal(isSupportLink(base + suffix), true);
  }
  for (const value of ["file:///C:/secret", "javascript:alert(1)", base.replace("https", "http"),
    base.replace("github.com", "github.com.attacker.test"), base.replace("github.com", "user:secret@github.com"),
    base + "/../other", base + "/issues/new?redirect=https://attacker.test", base + "/releases?token=secret",
    base + "/issues/new?body=" + "x".repeat(8000),
    // Only app release pages: no plugin or prerelease tags, no deeper paths, no queries.
    base + "/releases/tag/pine-v0.3.3", base + "/releases/tag/v1.1.0-rc.1", base + "/releases/tag/v1.0",
    base + "/releases/tag/", base + "/releases/tag/v1.0.1/../../../../other", base + "/releases/tag/v1.0.1/extra",
    base + "/releases/tag/v1.0.1?token=secret", base + "/releases/tag/v1.0.1#x", base + "/releases/download/v1.0.1/app.dmg"]) {
    assert.equal(isSupportLink(value), false, value);
  }
});
