import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const SRC = fileURLToPath(new URL("../src/", import.meta.url));
const TOKENS = join(SRC, "styles", "tokens.css");

// Ratchet: raw color literals outside tokens.css may only go down.
// When a migration lowers the count, lower these numbers in the same change.
const MAX_RAW_HEX = 582;
const MAX_RAW_RGB = 804;

function styleSources(dir = SRC) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "__tests__" ? [] : styleSources(path);
    return /\.css$|Styles\.tsx$/.test(entry.name) && path !== TOKENS ? [path] : [];
  });
}

function blockDeclarations(css, selectorName) {
  const match = css.match(new RegExp(`${selectorName.replace(/[[\]']/g, "\\$&")}\\s*\\{([^}]*)\\}`));
  assert.ok(match, `tokens.css must define ${selectorName}`);
  return Object.fromEntries(
    [...match[1].matchAll(/(--[a-z0-9-]+):\s*(#[0-9a-f]{6})\b/gi)].map(([, name, value]) => [name, value]),
  );
}

function luminance(hex) {
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const TEXT_TOKENS = ["--text-primary", "--text-secondary", "--text-muted", "--text-accent", "--text-success", "--text-danger", "--text-warning", "--text-info"];
const SURFACES = ["--surface-0", "--surface-1", "--surface-2"];

test("every text token reaches WCAG AA on every surface in both themes", () => {
  const css = readFileSync(TOKENS, "utf8");
  const dark = blockDeclarations(css, ":root");
  const light = { ...dark, ...blockDeclarations(css, "[data-theme='light']") };
  const failures = [];
  for (const [theme, tokens] of [["dark", dark], ["light", light]]) {
    for (const text of TEXT_TOKENS) {
      for (const surface of SURFACES) {
        const ratio = contrast(tokens[text], tokens[surface]);
        if (ratio < 4.5) failures.push(`${theme}: ${text} on ${surface} = ${ratio.toFixed(2)}`);
      }
    }
  }
  assert.deepEqual(failures, []);
  assert.ok(contrast("#ffffff", dark["--accent-solid"]) >= 4.5, "--text-on-accent must be legible on --accent-solid");
});

test("stylesheets never set text below the 11px floor except through the size tokens", () => {
  const offenders = styleSources().flatMap((path) => {
    const css = readFileSync(path, "utf8");
    return [...css.matchAll(/font(?:-size)?:\s*(?:\d{3}\s+|italic\s+|normal\s+)*(\d+(?:\.\d+)?)px/g)]
      .filter(([, size]) => Number(size) < 11)
      .map(([declaration]) => `${relative(SRC, path)}: ${declaration}`);
  });
  assert.deepEqual(offenders, [], "use var(--font-size-xs), or var(--font-size-2xs) for count badges and key caps");
});

test("raw color literals outside tokens.css do not grow", () => {
  let hex = 0;
  let rgb = 0;
  for (const path of styleSources()) {
    const css = readFileSync(path, "utf8");
    hex += (css.match(/#[0-9a-f]{3,8}\b/gi) ?? []).length;
    rgb += (css.match(/rgba?\(/g) ?? []).length;
  }
  assert.ok(hex <= MAX_RAW_HEX, `${hex} raw hex colors (max ${MAX_RAW_HEX}); use a token from src/styles/tokens.css`);
  assert.ok(rgb <= MAX_RAW_RGB, `${rgb} raw rgb()/rgba() colors (max ${MAX_RAW_RGB}); use a token or color-mix() with one`);
});
