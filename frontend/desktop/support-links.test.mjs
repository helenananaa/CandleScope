import assert from "node:assert/strict";
import test from "node:test";
import { isSupportLink } from "./support-links.mjs";

test("support external links only allow exact HTTPS project destinations", () => {
  const base = "https://github.com/helenananaa/CandleScope";
  for (const suffix of ["", "#readme", "/releases", "/blob/main/LICENSE", "/issues/new?body=hello%0Aworld"]) {
    assert.equal(isSupportLink(base + suffix), true);
  }
  for (const value of ["file:///C:/secret", "javascript:alert(1)", base.replace("https", "http"),
    base.replace("github.com", "github.com.attacker.test"), base.replace("github.com", "user:secret@github.com"),
    base + "/../other", base + "/issues/new?redirect=https://attacker.test", base + "/releases?token=secret",
    base + "/issues/new?body=" + "x".repeat(8000)]) assert.equal(isSupportLink(value), false);
});
