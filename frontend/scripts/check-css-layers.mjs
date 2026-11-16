#!/usr/bin/env node
// Keeps every app stylesheet inside a cascade layer (src/styles/layers.css):
//   - layers.css declares CSS_LAYERS in order, and every entry page imports it first;
//   - src/index.css only imports files, each into a known layer;
//   - every other stylesheet (imported from JavaScript) wraps itself in one known layer;
//   - <style> strings in *Styles.tsx are wrapped the same way.
// Unlayered app CSS would beat every layered rule regardless of specificity.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { CSS_LAYERS } from "./vite-css-layers.mjs";

const require = createRequire(import.meta.url);
const postcss = require("postcss");
const FRONTEND = path.resolve(import.meta.dirname, "..");
const SRC = path.join(FRONTEND, "src");
const ENTRIES = ["main.tsx", "replay-main.tsx", "strategy-main.tsx", "local-main.tsx", "backtest-main.tsx"];

function walk(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) { if (!["__tests__", "test"].includes(entry.name)) walk(full, out); }
    else out.push(full);
  }
  return out;
}

const rel = (file) => path.relative(FRONTEND, file);

/** Problems with a stylesheet that must wrap itself in one known layer. */
export function selfLayeredProblems(css, name) {
  const problems = [];
  let blocks = 0;
  postcss.parse(css, { from: name }).each((node) => {
    if (node.type === "comment") return;
    if (node.type === "atrule" && ["import", "charset"].includes(node.name)) return;
    if (node.type === "atrule" && node.name === "layer" && node.nodes) {
      if (!CSS_LAYERS.includes(node.params.trim())) problems.push(`${name}: unknown layer "${node.params.trim()}"`);
      blocks++;
      return;
    }
    const line = node.source?.start?.line ?? 0;
    problems.push(`${name}:${line}: ${node.type === "rule" ? node.selector : `@${node.name}`} is outside a cascade layer; wrap the file in @layer features { … }`);
  });
  if (!blocks && !problems.length) problems.push(`${name}: no @layer block`);
  return problems;
}

/** Problems with src/index.css: only `@import "…" layer(name);` lines after the layers file. */
export function manifestProblems(css) {
  const problems = [];
  const imports = [];
  postcss.parse(css, { from: "src/index.css" }).each((node) => {
    if (node.type === "comment") return;
    const line = node.source?.start?.line ?? 0;
    if (node.type !== "atrule" || node.name !== "import") {
      problems.push(`src/index.css:${line}: only @import lines belong here; put rules in a feature file`);
      return;
    }
    const match = /^["']([^"']+)["'](?:\s+layer\(([\w-]+)\))?$/.exec(node.params.trim());
    if (!match) { problems.push(`src/index.css:${line}: unexpected @import ${node.params}`); return; }
    imports.push({ file: match[1], layer: match[2] ?? null, line });
  });
  if (imports[0]?.file !== "./styles/layers.css") problems.push("src/index.css: the first import must be ./styles/layers.css");
  for (const { file, layer, line } of imports.slice(1)) {
    if (!layer) problems.push(`src/index.css:${line}: ${file} needs layer(…)`);
    else if (!CSS_LAYERS.includes(layer)) problems.push(`src/index.css:${line}: unknown layer "${layer}"`);
  }
  return { problems, imports };
}

export function checkCssLayers() {
  const problems = [];
  const layersCss = fs.readFileSync(path.join(SRC, "styles/layers.css"), "utf8");
  const declared = /@layer\s+([\w\s,-]+);/.exec(layersCss)?.[1].split(",").map((n) => n.trim());
  if (JSON.stringify(declared) !== JSON.stringify(CSS_LAYERS)) {
    problems.push(`src/styles/layers.css must declare: @layer ${CSS_LAYERS.join(", ")};`);
  }
  for (const entry of ENTRIES) {
    const text = fs.readFileSync(path.join(SRC, entry), "utf8");
    const first = /^import\s+(?:[^'"]*from\s+)?["']([^"']+)["']/m.exec(text)?.[1];
    if (first !== "./styles/layers.css") problems.push(`src/${entry}: the first import must be "./styles/layers.css" (it sets the layer order)`);
  }
  const manifest = manifestProblems(fs.readFileSync(path.join(SRC, "index.css"), "utf8"));
  problems.push(...manifest.problems);
  const fromManifest = new Set(manifest.imports.map(({ file }) => path.resolve(SRC, file)));
  for (const file of walk(SRC)) {
    if (file.endsWith(".css")) {
      if (file === path.join(SRC, "index.css") || fromManifest.has(file)) {
        // Imported into a layer by index.css: a layer block inside would nest (features.features).
        const css = fs.readFileSync(file, "utf8");
        if (/@layer\s+[\w-]+\s*\{/.test(css)) problems.push(`${rel(file)}: imported with layer() in src/index.css, so it must not wrap itself in @layer`);
        continue;
      }
      problems.push(...selfLayeredProblems(fs.readFileSync(file, "utf8"), rel(file)));
    } else if (/Styles\.tsx$/.test(file)) {
      for (const m of fs.readFileSync(file, "utf8").matchAll(/<style>\{`([\s\S]*?)`\}<\/style>/g)) problems.push(...selfLayeredProblems(m[1], rel(file)));
    }
  }
  return problems;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const problems = checkCssLayers();
  for (const problem of problems) console.error(`✖ ${problem}`);
  if (problems.length) process.exitCode = 1;
  else console.log("✓ every stylesheet is in a cascade layer");
}
