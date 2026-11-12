#!/usr/bin/env node
// Style metrics for the design refactor (FRONTEND_DESIGN_REFACTOR_PLAN.md §5 and §7).
// Reports what the refactor is meant to drive down. Warn-only for now: it exits 0 unless
// --strict is passed. Phase 8 of the plan turns the zero-targets into failures.
//
//   node scripts/check-style-metrics.mjs            # summary + worst offenders
//   node scripts/check-style-metrics.mjs --json     # machine-readable metrics
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const SRC = path.resolve(import.meta.dirname, "../src");

// Class names that are JS or test hooks, not styling hooks. Keep each one justified.
export const HOOK_CLASSES = new Set([
  "export-exclude", // export.ts drops these nodes from screenshots
  "pane-overlay-anchor", // positioning anchor read by pane overlays
  "drawing-text-style-bar", // drawingModel.ts keeps pointer events inside the text toolbar
  "settings-btn", // scripts/smoke.mjs finds the Settings button on every page
  "export-workspace", // scripts/export-matrix.mjs finds the export dialog
  "indicator-editor-console", // frontendScript browser test reads script output
  "indicator-editor-run", // frontendScript browser test runs the script
  "replay-public-time", // replay workspace test reads the public clock
]);

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

export function collectMetrics(files, read = (file) => fs.readFileSync(file, "utf8")) {
  const styleFiles = files.filter((file) => file.endsWith(".css") || file.endsWith("Styles.tsx"));
  const componentFiles = files.filter((file) => file.endsWith(".tsx") && !file.endsWith("Styles.tsx") && !/\.test\.tsx$/.test(file));
  const defined = new Set();
  let important = 0;
  for (const file of styleFiles) {
    const css = read(file);
    for (const name of classNamesInCss(css)) defined.add(name);
    important += (css.match(/!important/g) ?? []).length;
  }
  const unstyled = [];
  let rawButtons = 0;
  let buttonPrimitive = 0;
  let inlineStyles = 0;
  let nativeDialogs = 0;
  for (const file of componentFiles) {
    const source = read(file);
    const missing = [...classNamesInTsx(source)]
      .filter((name) => !defined.has(name) && !HOOK_CLASSES.has(name) && !/^(is|has)-/.test(name));
    if (missing.length) unstyled.push({ file, classes: missing.sort() });
    if (!file.includes(`${path.sep}components${path.sep}ui${path.sep}`)) rawButtons += (source.match(/<button\b/g) ?? []).length;
    buttonPrimitive += (source.match(/<Button\b/g) ?? []).length;
    inlineStyles += (source.match(/style=\{\{/g) ?? []).length;
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
    important,
    nativeDialogs,
  };
}

function report(metrics) {
  const rows = [
    ["Class names with no CSS rule", metrics.unstyledClasses, 0],
    ["Raw <button> outside components/ui", metrics.rawButtons, "≤ 20"],
    ["<Button> primitive uses", metrics.buttonPrimitive, "grows"],
    ["*-btn / *-button class families", metrics.buttonClassFamilies, "primitives"],
    ["Inline style={{}}", metrics.inlineStyles, "dynamic only"],
    ["!important in stylesheets", metrics.important, 0],
    ["window.confirm / window.alert", metrics.nativeDialogs, 0],
  ];
  console.log("Style metrics (warn-only; see FRONTEND_DESIGN_REFACTOR_PLAN.md §7)\n");
  for (const [label, value, target] of rows) console.log(`  ${label.padEnd(38)} ${String(value).padStart(5)}   target ${target}`);
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
    console.log(JSON.stringify({ ...metrics, unstyled: metrics.unstyled.map((e) => ({ ...e, file: path.relative(SRC, e.file) })) }, null, 2));
  } else {
    report(metrics);
  }
  if (argv.includes("--strict") && (metrics.unstyledClasses || metrics.important || metrics.nativeDialogs)) process.exitCode = 1;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) main();
