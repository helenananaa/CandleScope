#!/usr/bin/env node
// Style metrics for the design refactor (FRONTEND_DESIGN_REFACTOR_PLAN.md §5 and §7).
// Reports what the refactor drives down. With --strict (`npm run check:styles`, part of
// `npm run check`) it fails when a metric that has reached its target leaves it, or when a
// metric still on its way down rises above its ratchet.
//
//   node scripts/check-style-metrics.mjs            # summary + worst offenders
//   node scripts/check-style-metrics.mjs --strict   # the same, failing on a target or ratchet
//   node scripts/check-style-metrics.mjs --json     # machine-readable metrics
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const postcss = require("postcss");

const SRC = path.resolve(import.meta.dirname, "../src");

// Class names that are JS or test hooks, not styling hooks. Keep each one justified.
export const HOOK_CLASSES = new Set([
  "export-exclude", // export.ts drops these nodes from screenshots
  "chart-strategy-run-button", // ChartStrategyTesterPanel.test finds the tester's Run button (a kit Button)
  "pane-overlay-anchor", // positioning anchor read by pane overlays
  "chart-type-tool-btn", // scripts/chart-type-matrix.mjs and drawing-rollback-lifecycle-browser.mjs find the chart type button (a kit IconButton)
  "custom-interval-btn", // IntervalSelector.test checks that custom intervals on the bar are marked (kit Buttons)
  "drawing-text-style-bar", // drawingModel.ts keeps pointer events inside the text toolbar
  "settings-btn", // scripts/smoke.mjs finds the Settings button on every page
  "indicator-toggle-btn", // scripts/smoke.mjs and multi-chart-capacity.mjs find the indicators toggle (a kit icon button)
  "export-workspace", // scripts/export-matrix.mjs finds the export dialog
  "indicator-editor-console", // frontendScript browser test reads script output
  "indicator-editor-run", // frontendScript browser test runs the script
  "replay-public-time", // replay workspace test reads the public clock
  "pc-navigation", // scripts/trusted-extensions-desktop-smoke.mjs finds the plugin center's tabs
  "indicator-add-btn", // scripts/smoke.mjs and multi-chart-capacity.mjs add and remove indicators (with .added)
  "indicator-panel-close", // scripts/multi-chart-capacity.mjs closes the indicator drawer
  "indicator-tab-bar", // scripts/smoke.mjs and multi-chart-capacity.mjs find the drawer's tabs
  "indicator-tab-create", // frontendScript browser test opens the custom indicator editor
  "indicator-visibility-btn", // scripts/smoke.mjs toggles an active study
  "indicator-editor-save", // frontendScript browser test saves the custom indicator
  "export-panel-message", // export drill scripts read the panel's error message
  "export-preview-refresh", // export drill scripts regenerate the preview
  "sym-modal-close-btn", // smoke.mjs closes symbol search
  "replay-market-picker", // replay tests and the soak script find the initial market picker page
  "replay-end-dialog", // the soak script reads the end-session dialog
]);

// Metrics that have reached zero: any occurrence fails --strict.
export const ZERO_TARGETS = ["unstyledClasses", "important", "nativeDialogs", "legacyColorTokens", "malformedSelectors", "staticInlineStyles"];

// Metrics still on their way to the §7 targets (Phase 8c): --strict fails when one rises above
// its ratchet. Lower a ratchet when its count falls; never raise it.
export const RATCHETS = { rawButtons: 145, buttonClassFamilies: 18 };

function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "__tests__" || entry.name === "node_modules" ? [] : walk(full);
    return [full];
  });
}

/** Index just past the brace that closes the one at `open`. */
function closingBrace(source, open) {
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    if (source[i] === "{") depth++;
    else if (source[i] === "}" && --depth === 0) return i + 1;
  }
  return source.length;
}

/** Class tokens a TSX file can apply: static string parts inside className attributes. */
export function classNamesInTsx(source) {
  const names = new Set();
  const add = (text) => {
    // A token that ends in "-" is a dynamic prefix such as `status-${tone}`, not a class.
    for (const token of text.split(/\s+/)) if (/^[a-zA-Z_][\w-]*[a-zA-Z0-9_]$|^[a-zA-Z_]$/.test(token)) names.add(token);
  };
  for (const match of source.matchAll(/className="([^"]*)"/g)) add(match[1]);
  for (const match of source.matchAll(/className=\{/g)) {
    const open = match.index + match[0].length - 1;
    let expression = source.slice(open + 1, closingBrace(source, open) - 1);
    // buttonClassName({ variant: "primary" }) composes primitive classes; its arguments are options, not classes.
    expression = expression.replace(/\bbuttonClassName\(\{[^}]*\}\)/g, '"ui-btn"');
    // Values compared or looked up to choose a class (side === "short" ? "negative" : …,
    // ["profit", "pnl"].includes(column)) are data, not classes.
    expression = expression
      .replace(/\[[^\]]*\]\s*\.includes\(/g, "(")
      .replace(/([!=]==?)\s*("[^"]*"|'[^']*')/g, "$1 _")
      .replace(/("[^"]*"|'[^']*')\s*(?=[!=]==?)/g, "_ ");
    // Replace template interpolations (which may nest braces) with a separator.
    for (let at = expression.indexOf("${"); at !== -1; at = expression.indexOf("${")) {
      expression = `${expression.slice(0, at)} ${expression.slice(closingBrace(expression, at + 1))}`;
    }
    for (const literal of expression.matchAll(/"([^"]*)"|'([^']*)'|`([^`]*)`/g)) add(literal[1] ?? literal[2] ?? literal[3] ?? "");
  }
  return names;
}

/** Class names that appear in any selector of a stylesheet (or a *Styles.tsx string). */
export function classNamesInCss(source) {
  const withoutComments = source.replace(/\/\*[\s\S]*?\*\//g, "");
  return new Set([...withoutComments.matchAll(/\.([a-zA-Z_][\w-]*)/g)].map((match) => match[1]));
}

// The colour names tokens.css replaced (Phase 1) and dropped (Phase 8). Extension themes still use them
// in candlescope.theme/1; features/extensions/state.ts writes them as the design tokens.
const LEGACY_COLOR_TOKEN = /--(?:bg-(?:primary|secondary|tertiary|hover)|border-color)\b/g;

/**
 * Whether a style={{…}} object (the text between its braces) is static: only literal values,
 * nothing computed at render time. Dynamic geometry and colours from data stay inline.
 */
export function isStaticStyleObject(body) {
  if (/\$\{/.test(body)) return false;
  let rest = body.replace(/"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'/g, "S");
  rest = rest.replace(/(^|[,{\s])(\[?[A-Za-z_$][\w$]*\]?|S)\s*:/g, "$1");
  return !/[A-Za-z_$]/.test(rest.replace(/\bS\b/g, ""));
}

/** !important declarations outside comments and outside prefers-reduced-motion blocks. */
export function importantOutsideReducedMotion(css) {
  let text = css.replace(/\/\*[\s\S]*?\*\//g, "");
  for (let at = text.search(/@media[^{]*prefers-reduced-motion/); at !== -1; at = text.search(/@media[^{]*prefers-reduced-motion/)) {
    text = text.slice(0, at) + text.slice(closingBrace(text, text.indexOf("{", at)));
  }
  return (text.match(/!important/g) ?? []).length;
}

/**
 * Line numbers of rules whose selector has unbalanced () or []. A browser drops such a rule
 * whole (Vite only warns), so the rule silently stops applying.
 */
export function malformedSelectorLines(css) {
  const lines = [];
  postcss.parse(css).walkRules((rule) => {
    if (rule.parent?.type === "atrule" && /keyframes$/.test(rule.parent.name)) return;
    const text = rule.selector.replace(/"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'/g, "");
    let round = 0, square = 0;
    for (const ch of text) {
      if (ch === "(") round++; else if (ch === ")") round--;
      else if (ch === "[") square++; else if (ch === "]") square--;
      if (round < 0 || square < 0) break;
    }
    if (round !== 0 || square !== 0) lines.push(rule.source?.start?.line ?? 0);
  });
  return lines;
}

export function collectMetrics(files, read = (file) => fs.readFileSync(file, "utf8")) {
  const styleFiles = files.filter((file) => file.endsWith(".css") || file.endsWith("Styles.tsx"));
  // Components the app ships: not tests, not browser-test harnesses (*.browser.tsx, src/test/).
  const componentFiles = files.filter((file) => file.endsWith(".tsx") && !file.endsWith("Styles.tsx")
    && !/\.(?:test|browser)\.tsx$/.test(file) && !file.includes(`${path.sep}src${path.sep}test${path.sep}`) && !file.startsWith(`src${path.sep}test${path.sep}`));
  const defined = new Set();
  let important = 0;
  let legacyColorTokens = 0;
  const malformed = [];
  for (const file of styleFiles) {
    const css = read(file);
    for (const name of classNamesInCss(css)) defined.add(name);
    important += importantOutsideReducedMotion(css);
    if (file.endsWith(".css")) for (const line of malformedSelectorLines(css)) malformed.push(`${file}:${line}`);
  }
  for (const file of files.filter((f) => /\.(css|tsx?)$/.test(f) && !/\.test\.tsx?$/.test(f))) {
    legacyColorTokens += (read(file).match(LEGACY_COLOR_TOKEN) ?? []).length;
  }
  const unstyled = [];
  let rawButtons = 0;
  let buttonPrimitive = 0;
  let inlineStyles = 0;
  let staticInlineStyles = 0;
  let nativeDialogs = 0;
  for (const file of componentFiles) {
    const source = read(file);
    const missing = [...classNamesInTsx(source)]
      .filter((name) => !defined.has(name) && !HOOK_CLASSES.has(name) && !/^(is|has)-/.test(name));
    if (missing.length) unstyled.push({ file, classes: missing.sort() });
    if (!file.includes(`${path.sep}components${path.sep}ui${path.sep}`)) rawButtons += (source.match(/<button\b/g) ?? []).length;
    buttonPrimitive += (source.match(/<Button\b/g) ?? []).length;
    for (const match of source.matchAll(/style=\{\{/g)) {
      inlineStyles++;
      const open = match.index + "style={".length;
      if (isStaticStyleObject(source.slice(open + 1, closingBrace(source, open) - 1))) staticInlineStyles++;
    }
  }
  for (const file of files.filter((f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f))) {
    nativeDialogs += (read(file).match(/window\.(?:confirm|alert)\(/g) ?? []).length;
  }
  const buttonFamilies = new Set([...defined].filter((name) => /-(?:btn|button)$/.test(name)));
  return {
    unstyledClasses: unstyled.reduce((sum, entry) => sum + entry.classes.length, 0),
    unstyled: unstyled.sort((a, b) => b.classes.length - a.classes.length),
    rawButtons,
    buttonPrimitive,
    buttonClassFamilies: buttonFamilies.size,
    inlineStyles,
    staticInlineStyles,
    important,
    nativeDialogs,
    legacyColorTokens,
    malformedSelectors: malformed.length,
    malformed,
  };
}

/** What --strict rejects: metrics off their zero target or above their ratchet. */
export function strictFailures(metrics) {
  const failures = ZERO_TARGETS.filter((name) => metrics[name] > 0).map((name) => `${name} is ${metrics[name]}, target 0`);
  for (const [name, ceiling] of Object.entries(RATCHETS)) {
    if (metrics[name] > ceiling) failures.push(`${name} is ${metrics[name]}, above its ratchet of ${ceiling}`);
  }
  return failures;
}

function report(metrics) {
  const rows = [
    ["Class names with no CSS rule", metrics.unstyledClasses, "0"],
    ["Raw <button> outside components/ui", metrics.rawButtons, `≤ 20 (ratchet ${RATCHETS.rawButtons})`],
    ["<Button> primitive uses", metrics.buttonPrimitive, "grows"],
    ["*-btn / *-button class families", metrics.buttonClassFamilies, `primitives (ratchet ${RATCHETS.buttonClassFamilies})`],
    ["Inline style={{}} (dynamic)", metrics.inlineStyles - metrics.staticInlineStyles, "allowed"],
    ["Static inline style={{}}", metrics.staticInlineStyles, "0"],
    ["!important outside reduced motion", metrics.important, "0"],
    ["window.confirm / window.alert", metrics.nativeDialogs, "0"],
    ["Legacy colour token names (--bg-*)", metrics.legacyColorTokens, "0"],
    ["Selectors with unbalanced ( ) or [ ]", metrics.malformedSelectors, "0"],
  ];
  console.log("Style metrics (see FRONTEND_DESIGN_REFACTOR_PLAN.md §7)\n");
  for (const [label, value, target] of rows) console.log(`  ${label.padEnd(38)} ${String(value).padStart(5)}   target ${target}`);
  const lower = Object.entries(RATCHETS).filter(([name, ceiling]) => metrics[name] < ceiling);
  if (lower.length) console.log(`\nBelow the ratchet; lower RATCHETS in scripts/check-style-metrics.mjs: ${lower.map(([name]) => `${name} → ${metrics[name]}`).join(", ")}`);
  for (const location of metrics.malformed) console.log(`  malformed selector: ${path.relative(SRC, location)}`);
  if (metrics.unstyled.length) {
    console.log("\nFiles with the most unstyled class names:");
    for (const entry of metrics.unstyled.slice(0, 12)) {
      console.log(`  ${String(entry.classes.length).padStart(3)}  ${path.relative(SRC, entry.file)}  ${entry.classes.slice(0, 6).join(" ")}${entry.classes.length > 6 ? " …" : ""}`);
    }
  }
}

export function main(argv = process.argv.slice(2)) {
  const metrics = collectMetrics(walk(SRC));
  if (argv.includes("--json")) {
    console.log(JSON.stringify({ ...metrics, malformed: metrics.malformed.map((location) => path.relative(SRC, location)), unstyled: metrics.unstyled.map((e) => ({ ...e, file: path.relative(SRC, e.file) })) }, null, 2));
  } else {
    report(metrics);
  }
  if (!argv.includes("--strict")) return;
  const failures = strictFailures(metrics);
  if (failures.length) {
    console.error(`\nStyle metrics failed:\n${failures.map((line) => `  - ${line}`).join("\n")}`);
    if (metrics.legacyColorTokens) console.error("  Legacy colour names (--bg-*, --border-color): use --surface-* / --border-subtle.");
    if (metrics.important) console.error("  !important outside prefers-reduced-motion: raise the selector's specificity, or put a cross-cutting rule in styles/overrides.css.");
    process.exitCode = 1;
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) main();
