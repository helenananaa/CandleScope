import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { CHART_THEME_COLORS, chartSchemeForBackground } from "../chartPalette.js";

function tokenValue(css: string, block: string, name: string): string | undefined {
  const body = css.match(new RegExp(`${block.replace(/[[\]']/g, "\\$&")}\\s*\\{([^}]*)\\}`))?.[1] ?? "";
  return body.match(new RegExp(`${name}:\\s*(#[0-9a-f]{6})`, "i"))?.[1];
}

test("canvas colours match the Graphite tokens in both themes", () => {
  const css = readFileSync(new URL("../../styles/tokens.css", import.meta.url), "utf8");
  assert.equal(CHART_THEME_COLORS.dark.background, tokenValue(css, ":root", "--surface-0"));
  assert.equal(CHART_THEME_COLORS.dark.text, tokenValue(css, ":root", "--text-secondary"));
  assert.equal(CHART_THEME_COLORS.light.background, tokenValue(css, "[data-theme='light']", "--surface-0"));
  assert.equal(CHART_THEME_COLORS.light.text, tokenValue(css, "[data-theme='light']", "--text-secondary"));
});

test("background brightness decides the foreground scheme", () => {
  assert.equal(chartSchemeForBackground("#ffffff"), "light");
  assert.equal(chartSchemeForBackground("#f4efe2"), "light");
  assert.equal(chartSchemeForBackground("#0d0e10"), "dark");
  assert.equal(chartSchemeForBackground("#1e3a5f"), "dark");
  assert.equal(chartSchemeForBackground("#fff"), "light");
  assert.equal(chartSchemeForBackground("not-a-colour"), "dark");
});
