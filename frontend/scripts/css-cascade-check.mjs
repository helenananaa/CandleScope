#!/usr/bin/env node
// Proves that a stylesheet refactor (moving CSS between files, splitting files, assigning
// cascade layers) leaves every element's styles unchanged, or lists what changes.
//
// Compares the app's stylesheets at a Git ref with the working tree:
//   - the same declarations must exist in both (any edit to a value shows as added/removed);
//   - no pair of declarations that can style the same element may change winner.
//
//   node scripts/css-cascade-check.mjs --base main
//   node scripts/css-cascade-check.mjs --base HEAD --limit 50
//
// See scripts/css-cascade.mjs for the model and its limits.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import {
  alignDeclarations, canShareElement, cascadeChanges, cssClassNames, flatten, layerOrder, resolveImports, scanClassUsage, scanContainment,
} from "./css-cascade.mjs";

const FRONTEND = path.resolve(import.meta.dirname, "..");
const SRC = path.join(FRONTEND, "src");

/** Files of the frontend at a Git ref, or of the working tree when ref is null. */
export function treeReader(ref) {
  if (!ref) {
    return {
      read: (file) => fs.readFileSync(file, "utf8"),
      exists: (file) => fs.existsSync(file),
      list: (dir) => {
        const out = [];
        (function walk(d) {
          for (const e of fs.readdirSync(d, { withFileTypes: true })) {
            const full = path.join(d, e.name);
            if (e.isDirectory()) walk(full); else out.push(full);
          }
        })(dir);
        return out;
      },
    };
  }
  const git = (...args) => execFileSync("git", args, { cwd: FRONTEND, encoding: "utf8", maxBuffer: 256 * 1024 * 1024 });
  const rel = (file) => path.relative(FRONTEND, file).split(path.sep).join("/");
  // ls-tree prints paths relative to the working directory (the frontend).
  const files = new Set(git("ls-tree", "-r", "--name-only", ref, "--", ".").split("\n").filter(Boolean).map((p) => path.join(FRONTEND, p)));
  return {
    read: (file) => git("show", `${ref}:./${rel(file)}`),
    exists: (file) => files.has(file),
    list: (dir) => [...files].filter((file) => file.startsWith(dir + path.sep)),
  };
}

function styleStrings(text) {
  const out = [];
  for (const m of text.matchAll(/<style>\{`([\s\S]*?)`\}<\/style>/g)) out.push(m[1]);
  return out;
}

/** The app's stylesheets in cascade order for one tree. */
export function stylesheets(tree, { vendorFiles = [] } = {}) {
  const sources = [];
  const layersFile = path.join(SRC, "styles/layers.css");
  if (tree.exists(layersFile)) sources.push({ file: layersFile, css: tree.read(layersFile), layer: null });
  const entry = resolveImports(path.join(SRC, "index.css"), tree.read);
  sources.push(...entry);
  const inEntry = new Set([layersFile, ...entry.map((s) => s.file)]);
  const all = tree.list(SRC).sort();
  for (const file of all) {
    if (file.endsWith(".css") && !inEntry.has(file) && !/[\\/]__tests__[\\/]/.test(file)) sources.push({ file, css: tree.read(file), layer: null });
  }
  for (const file of all) {
    if (!/Styles\.tsx$/.test(file)) continue;
    for (const css of styleStrings(tree.read(file))) sources.push({ file, css, layer: null });
  }
  // Third-party CSS: wrapped into a layer by scripts/vite-css-layers.mjs when that exists.
  const pluginFile = path.join(FRONTEND, "scripts/vite-css-layers.mjs");
  const vendorLayer = tree.exists(pluginFile) ? /VENDOR_CSS_LAYER = "([\w-]+)"/.exec(tree.read(pluginFile))?.[1] ?? null : null;
  for (const file of vendorFiles) sources.push({ file, css: fs.readFileSync(file, "utf8"), layer: vendorLayer, vendor: true });
  return sources;
}

export function vendorStylesheets() {
  const dir = path.join(FRONTEND, "node_modules/monaco-editor/esm");
  if (!fs.existsSync(dir)) return [];
  return treeReader(null).list(dir).filter((file) => file.endsWith(".css")).sort();
}

/** Classes that third-party code puts on elements it creates. */
function thirdPartyClasses(vendorSources, appClasses) {
  const classes = cssClassNames(vendorSources);
  const chartBundle = path.join(FRONTEND, "node_modules/lightweight-charts/dist/lightweight-charts.production.mjs");
  if (fs.existsSync(chartBundle)) {
    for (const m of fs.readFileSync(chartBundle, "utf8").matchAll(/["`]([a-z][\w -]*)["`]/g)) {
      for (const word of m[1].split(/\s+/)) if (appClasses.has(word)) classes.add(word);
    }
  }
  return classes;
}

export function parseArgs(argv) {
  const args = { base: "HEAD", limit: 40, json: false };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--base") args.base = argv[++i];
    else if (argv[i] === "--limit") args.limit = Number(argv[++i]);
    else if (argv[i] === "--json") args.json = true;
    else throw new Error(`Unknown option: ${argv[i]}`);
  }
  return args;
}

export function check({ base }) {
  const vendorFiles = vendorStylesheets();
  const beforeSources = stylesheets(treeReader(base), { vendorFiles });
  const afterSources = stylesheets(treeReader(null), { vendorFiles });
  const appClasses = cssClassNames(afterSources.filter((s) => !s.vendor));
  const usage = scanClassUsage(SRC, { cssClasses: appClasses, foreignClasses: thirdPartyClasses(afterSources.filter((s) => s.vendor), appClasses) });
  const before = flatten(beforeSources), after = flatten(afterSources);
  const { aligned, missing, extra } = alignDeclarations(before, after);
  const changes = cascadeChanges(aligned, {
    beforeLayers: layerOrder(beforeSources), afterLayers: layerOrder(afterSources), shareElement: canShareElement(usage, scanContainment(SRC)),
  });
  return { declarations: before.length, missing, extra, changes };
}

const where = (d) => `${path.relative(FRONTEND, d.file)}:${d.line}`;
const describe = (d) => `${d.selector} { ${d.prop}: ${d.value}${d.important ? " !important" : ""} }${d.layer ? ` @layer ${d.layer}` : ""}${d.context ? ` ${d.context}` : ""}`;

export async function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  const result = check(args);
  if (args.json) {
    console.log(JSON.stringify({ ...result, missing: result.missing.map(describe), extra: result.extra.map(describe),
      changes: result.changes.map((c) => ({ first: `${where(c.first)} ${describe(c.first)}`, second: `${where(c.second)} ${describe(c.second)}`, winnerBefore: c.before === 1 ? "first" : "second" })) }, null, 2));
  } else {
    console.log(`${result.declarations} declarations compared with ${args.base}`);
    for (const d of result.missing.slice(0, args.limit)) console.log(`- removed or edited: ${where(d)} ${describe(d)}`);
    for (const d of result.extra.slice(0, args.limit)) console.log(`+ added or edited: ${where(d)} ${describe(d)}`);
    for (const c of result.changes.slice(0, args.limit)) {
      const [won, lost] = c.before === 1 ? [c.first, c.second] : [c.second, c.first];
      console.log(`! winner changes on elements matching both:\n    was: ${where(won)} ${describe(won)}\n    now: ${where(lost)} ${describe(lost)}`);
    }
    console.log(`${result.missing.length} removed, ${result.extra.length} added, ${result.changes.length} winner changes`);
  }
  process.exitCode = result.missing.length || result.extra.length || result.changes.length ? 1 : 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
