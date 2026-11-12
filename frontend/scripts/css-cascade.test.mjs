import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  alignDeclarations, atoms, canShareElement, cascadeChanges, classExpression, compatible, flatten, layerOrder,
  resolveImports, scanClassUsage, specificity, subjectVariants, winner,
} from "./css-cascade.mjs";
import { vendorCssLayerPlugin, wrapInLayer } from "./vite-css-layers.mjs";

test("specificity follows Selectors Level 4", () => {
  assert.deepEqual(specificity(".a .b"), [0, 2, 0]);
  assert.deepEqual(specificity("html :is(.a, #b > p)"), [1, 0, 2]);
  assert.deepEqual(specificity(":where(.a) button"), [0, 0, 1]);
  assert.deepEqual(specificity(".a:not(.b, .c .d)::before"), [0, 3, 1]);
  assert.deepEqual(specificity("[data-x='1'] li:nth-child(2 of .on)"), [0, 3, 1]);
});

test("shorthands conflict with their longhands", () => {
  assert.ok(atoms("background").includes("background-color"));
  assert.ok(atoms("font").includes("line-height"));
  assert.deepEqual(atoms("inset-inline-start"), ["left"]);
  assert.deepEqual(atoms("--surface-0"), ["--surface-0"]);
});

test("layers decide before specificity, and important declarations reverse them", () => {
  const order = ["reset", "features"];
  const decl = (layer, spec, important = false, at = 0) => ({ layer, spec, important, order: at });
  assert.equal(winner(decl("reset", [1, 0, 0]), decl("features", [0, 0, 1]), order), -1);
  assert.equal(winner(decl(null, [0, 0, 1]), decl("features", [1, 0, 0]), order), 1);
  assert.equal(winner(decl("reset", [0, 0, 1], true), decl("features", [1, 0, 0], true), order), 1);
  assert.equal(winner(decl("features", [0, 1, 0], false, 2), decl("features", [0, 1, 0], false, 1), order), 1);
});

test("class expressions yield tokens, prefixes and value identifiers", () => {
  const expr = classExpression("`ob-status ob-status-${snapshot.status} ${open ? \"active\" : \"\"} ${className}`");
  assert.deepEqual(expr.tokens, ["ob-status", "active"]);
  assert.deepEqual(expr.prefixes, ["ob-status-"]);
  assert.deepEqual(expr.identifiers, ["className"]);
  assert.deepEqual(classExpression('clsx("a b", isOn && "c")').identifiers, []);
});

function fixture(files) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "css-cascade-"));
  for (const [name, text] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(dir, name)), { recursive: true });
    fs.writeFileSync(path.join(dir, name), text);
  }
  return dir;
}

test("classes share an element only where the source puts them together", () => {
  const dir = fixture({
    "Panel.tsx": `export function Panel({ className }) { return <div className={\`panel \${className}\`} />; }
      export function Page() { return <><Panel className="page-panel" /><span className="note" /><b className={on ? "x y" : "z"} /></>; }`,
  });
  try {
    const share = canShareElement(scanClassUsage(dir, { cssClasses: new Set(["panel", "page-panel", "note", "x", "y", "z", "dead"]) }));
    assert.equal(share("panel", "page-panel"), true, "forwarded to Panel's className");
    assert.equal(share("x", "y"), true);
    assert.equal(share("x", "z"), true, "one expression can produce both branches' classes");
    assert.equal(share("panel", "note"), false);
    assert.equal(share("note", "page-panel"), false);
    assert.equal(share("dead", "dead"), false, "a class no code applies matches nothing");
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("html, body and #root are never confused with classed elements", () => {
  const [root] = subjectVariants("#root");
  const [classed] = subjectVariants(".panel");
  const [nested] = subjectVariants(".app div");
  assert.equal(compatible(root, classed), false);
  assert.equal(compatible(root, nested), false);
  assert.equal(compatible(subjectVariants("body")[0], subjectVariants("html > body")[0]), true);
});

test("moving a rule into another layer reports the winner change", () => {
  const before = [{ file: "a.css", css: ".a { color: red }\n.b .a { color: blue }", layer: null }];
  const after = [
    { file: "layers.css", css: "@layer reset, features;", layer: null },
    { file: "a.css", css: "@layer features { .a { color: red } }\n@layer reset { .b .a { color: blue } }", layer: null },
  ];
  const { aligned, missing, extra } = alignDeclarations(flatten(before), flatten(after));
  assert.equal(missing.length + extra.length, 0);
  const changes = cascadeChanges(aligned, { beforeLayers: layerOrder(before), afterLayers: layerOrder(after), shareElement: null });
  assert.equal(changes.length, 1);
  assert.equal(changes[0].first.value, "red");
});

test("reordering rules with equal specificity is reported; a pure move is not", () => {
  const original = [{ file: "x.css", css: ".a { color: red }\n.b { color: blue }\n.c { margin: 0 }", layer: null }];
  const moved = [{ file: "x.css", css: ".c { margin: 0 }\n.a { color: red }\n.b { color: blue }", layer: null }];
  const swapped = [{ file: "x.css", css: ".b { color: blue }\n.a { color: red }\n.c { margin: 0 }", layer: null }];
  const run = (after) => cascadeChanges(alignDeclarations(flatten(original), flatten(after)).aligned, { beforeLayers: [], afterLayers: [], shareElement: null });
  assert.equal(run(moved).length, 0);
  assert.equal(run(swapped).length, 1);
});

test("imports resolve in order and carry their layer", () => {
  const dir = fixture({ "index.css": '@import "./a.css" layer(features);\n.z { color: red }', "a.css": ".a { color: blue }" });
  try {
    const sources = resolveImports(path.join(dir, "index.css"));
    assert.deepEqual(sources.map((s) => [path.basename(s.file), s.layer]), [["a.css", "features"], ["index.css", null]]);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("the Vite plugin wraps Monaco's CSS in the features layer and leaves other CSS alone", () => {
  const plugin = vendorCssLayerPlugin();
  assert.equal(plugin.transform(".x{}", "/app/node_modules/monaco-editor/esm/vs/a.css").code, wrapInLayer(".x{}", "features"));
  assert.equal(plugin.transform(".x{}", "/app/src/index.css"), null);
  assert.equal(plugin.transform("x", "/app/node_modules/monaco-editor/esm/vs/a.js"), null);
});
