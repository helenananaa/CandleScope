// Static cascade model for the app's stylesheets.
//
// Flattens stylesheets into declarations (selector, specificity, layer, order) and compares
// two arrangements of the same declarations: which pairs that can style the same element
// would change winner? Used to prove that moving CSS between files or layers is a no-op,
// and to list exactly what changes when a move is not.
//
// "Can style the same element" is decided from the selectors' subject compounds and from
// which classes the TSX source can put on one element (scanClassUsage). The model is
// conservative where the source is not explicit: a class that reaches an element through a
// variable or a component prop may meet any class that element can take.
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);
const postcss = require("postcss");

// ── Selectors ──────────────────────────────────────────────────────

/** Splits on a separator outside (), [] and quotes. */
export function splitTop(text, separator) {
  const parts = [];
  let depth = 0, quote = null, start = 0;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quote) { if (ch === "\\") i++; else if (ch === quote) quote = null; continue; }
    if (ch === '"' || ch === "'") quote = ch;
    else if (ch === "(" || ch === "[") depth++;
    else if (ch === ")" || ch === "]") depth--;
    else if (depth === 0 && ch === separator) { parts.push(text.slice(start, i)); start = i + 1; }
  }
  parts.push(text.slice(start));
  return parts.map((part) => part.trim()).filter(Boolean);
}

/** Compounds of a complex selector, left to right (combinators dropped). */
export function compounds(selector) {
  const out = [];
  let depth = 0, quote = null, current = "";
  for (let i = 0; i < selector.length; i++) {
    const ch = selector[i];
    if (quote) {
      current += ch;
      if (ch === "\\") current += selector[++i];
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") { quote = ch; current += ch; continue; }
    if (ch === "(" || ch === "[") depth++;
    if (ch === ")" || ch === "]") depth--;
    if (depth === 0 && /[\s>+~]/.test(ch)) {
      if (current.trim()) out.push(current.trim());
      current = "";
      continue;
    }
    current += ch;
  }
  if (current.trim()) out.push(current.trim());
  return out;
}

const LEGACY_PSEUDO_ELEMENTS = new Set(["before", "after", "first-line", "first-letter"]);

export function parseCompound(compound) {
  const parts = { tag: null, ids: [], classes: [], attrs: [], pseudoClasses: [], pseudoElement: null };
  let i = 0;
  const ident = () => {
    const start = i;
    while (i < compound.length && /[\w\-\\\u00a0-\uffff]/.test(compound[i])) i += compound[i] === "\\" ? 2 : 1;
    return compound.slice(start, i);
  };
  const paren = () => {
    if (compound[i] !== "(") return null;
    let depth = 0;
    const start = i;
    for (; i < compound.length; i++) {
      if (compound[i] === "(") depth++;
      else if (compound[i] === ")" && --depth === 0) { i++; break; }
    }
    return compound.slice(start + 1, i - 1);
  };
  while (i < compound.length) {
    const ch = compound[i];
    if (ch === "*") { i++; continue; }
    if (ch === "#") { i++; parts.ids.push(ident()); continue; }
    if (ch === ".") { i++; parts.classes.push(ident()); continue; }
    if (ch === "[") {
      let depth = 0;
      const start = i;
      for (; i < compound.length; i++) {
        if (compound[i] === "[") depth++;
        else if (compound[i] === "]" && --depth === 0) { i++; break; }
      }
      parts.attrs.push(compound.slice(start + 1, i - 1));
      continue;
    }
    if (ch === ":") {
      if (compound[i + 1] === ":") {
        i += 2;
        const name = ident();
        const arg = paren();
        parts.pseudoElement = arg == null ? name : `${name}(${arg})`;
        continue;
      }
      i++;
      const name = ident().toLowerCase();
      const arg = paren();
      if (LEGACY_PSEUDO_ELEMENTS.has(name)) parts.pseudoElement = name;
      else parts.pseudoClasses.push({ name, arg });
      continue;
    }
    if (/[\w-]/.test(ch)) { parts.tag = ident().toLowerCase(); continue; }
    i++;
  }
  return parts;
}

const addSpec = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const compareSpecificity = (a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2];
const maxSpec = (list) => list.reduce((best, s) => (compareSpecificity(s, best) > 0 ? s : best), [0, 0, 0]);

/** Selectors Level 4 specificity of one complex selector. */
export function specificity(selector) {
  let total = [0, 0, 0];
  for (const compound of compounds(selector)) {
    const p = parseCompound(compound);
    total = addSpec(total, [p.ids.length, p.classes.length + p.attrs.length, (p.tag ? 1 : 0) + (p.pseudoElement ? 1 : 0)]);
    for (const { name, arg } of p.pseudoClasses) {
      if (name === "where") continue;
      if (["is", "not", "has", "matches", "-webkit-any"].includes(name) && arg != null) {
        total = addSpec(total, maxSpec(splitTop(arg, ",").map(specificity)));
      } else if (["nth-child", "nth-last-child"].includes(name) && arg && / of /.test(arg)) {
        total = addSpec(total, addSpec([0, 1, 0], maxSpec(splitTop(arg.split(/ of /)[1], ",").map(specificity))));
      } else {
        total = addSpec(total, [0, 1, 0]);
      }
    }
  }
  return total;
}

/**
 * What the subject (rightmost compound) requires of an element, expanded through
 * :is()/:where() alternatives. Ancestors are kept for structural checks.
 */
export function subjectVariants(selector) {
  const parts = compounds(selector);
  const p = parseCompound(parts[parts.length - 1] ?? "*");
  const base = {
    tag: p.tag, ids: p.ids, classes: p.classes, pseudoElement: p.pseudoElement,
    pseudoClasses: p.pseudoClasses.filter((pc) => !["is", "where", "not", "has", "matches"].includes(pc.name)).map((pc) => pc.name),
    ancestors: parts.slice(0, -1).map(parseCompound),
  };
  let variants = [base];
  for (const pc of p.pseudoClasses) {
    if (!["is", "where", "matches"].includes(pc.name) || pc.arg == null) continue;
    const alternatives = splitTop(pc.arg, ",").flatMap(subjectVariants);
    variants = variants.flatMap((v) => alternatives.map((alt) => ({
      tag: v.tag ?? alt.tag, ids: [...v.ids, ...alt.ids], classes: [...v.classes, ...alt.classes],
      pseudoElement: v.pseudoElement ?? alt.pseudoElement, pseudoClasses: [...v.pseudoClasses, ...alt.pseudoClasses],
      ancestors: [...v.ancestors, ...alt.ancestors],
    })));
  }
  return variants;
}

// ── Properties ─────────────────────────────────────────────────────

const SIDES = ["top", "right", "bottom", "left"];
const side = (prefix, suffix = "") => SIDES.map((s) => `${prefix}${s}${suffix}`);
const borderSide = (s) => [`border-${s}-width`, `border-${s}-style`, `border-${s}-color`];
const SHORTHANDS = {
  background: ["background-color", "background-image", "background-position", "background-size", "background-repeat", "background-attachment", "background-origin", "background-clip"],
  margin: side("margin-"), padding: side("padding-"), inset: SIDES,
  "inset-inline": ["left", "right"], "inset-block": ["top", "bottom"],
  "inset-inline-start": ["left"], "inset-inline-end": ["right"], "inset-block-start": ["top"], "inset-block-end": ["bottom"],
  "margin-inline": ["margin-left", "margin-right"], "margin-block": ["margin-top", "margin-bottom"],
  "margin-inline-start": ["margin-left"], "margin-inline-end": ["margin-right"], "margin-block-start": ["margin-top"], "margin-block-end": ["margin-bottom"],
  "padding-inline": ["padding-left", "padding-right"], "padding-block": ["padding-top", "padding-bottom"],
  "padding-inline-start": ["padding-left"], "padding-inline-end": ["padding-right"], "padding-block-start": ["padding-top"], "padding-block-end": ["padding-bottom"],
  border: [...SIDES.flatMap(borderSide), "border-image"],
  "border-width": side("border-", "-width"), "border-style": side("border-", "-style"), "border-color": side("border-", "-color"),
  ...Object.fromEntries(SIDES.map((s) => [`border-${s}`, borderSide(s)])),
  "border-inline": [...borderSide("left"), ...borderSide("right")], "border-block": [...borderSide("top"), ...borderSide("bottom")],
  "border-inline-start": borderSide("left"), "border-inline-end": borderSide("right"),
  "border-block-start": borderSide("top"), "border-block-end": borderSide("bottom"),
  "border-radius": ["border-top-left-radius", "border-top-right-radius", "border-bottom-right-radius", "border-bottom-left-radius"],
  font: ["font-style", "font-variant", "font-weight", "font-stretch", "font-size", "line-height", "font-family", "font-variant-numeric", "font-feature-settings", "font-kerning", "font-variant-ligatures", "font-variant-caps"],
  flex: ["flex-grow", "flex-shrink", "flex-basis"], "flex-flow": ["flex-direction", "flex-wrap"],
  gap: ["row-gap", "column-gap"], "grid-gap": ["row-gap", "column-gap"],
  overflow: ["overflow-x", "overflow-y"], outline: ["outline-color", "outline-style", "outline-width"],
  transition: ["transition-property", "transition-duration", "transition-timing-function", "transition-delay"],
  animation: ["animation-name", "animation-duration", "animation-timing-function", "animation-delay", "animation-iteration-count", "animation-direction", "animation-fill-mode", "animation-play-state"],
  "text-decoration": ["text-decoration-line", "text-decoration-color", "text-decoration-style", "text-decoration-thickness"],
  "list-style": ["list-style-type", "list-style-position", "list-style-image"],
  "place-items": ["align-items", "justify-items"], "place-content": ["align-content", "justify-content"], "place-self": ["align-self", "justify-self"],
  grid: ["grid-template-rows", "grid-template-columns", "grid-template-areas", "grid-auto-rows", "grid-auto-columns", "grid-auto-flow"],
  "grid-template": ["grid-template-rows", "grid-template-columns", "grid-template-areas"],
  "grid-area": ["grid-row-start", "grid-column-start", "grid-row-end", "grid-column-end"],
  "grid-row": ["grid-row-start", "grid-row-end"], "grid-column": ["grid-column-start", "grid-column-end"],
  "inline-size": ["width"], "block-size": ["height"], "min-inline-size": ["min-width"], "min-block-size": ["min-height"],
  "max-inline-size": ["max-width"], "max-block-size": ["max-height"],
  columns: ["column-width", "column-count"], "column-rule": ["column-rule-color", "column-rule-style", "column-rule-width"],
  container: ["container-name", "container-type"],
  mask: ["mask-image", "mask-position", "mask-size", "mask-repeat"], "-webkit-mask": ["mask-image", "mask-position", "mask-size", "mask-repeat"],
  "scroll-margin": side("scroll-margin-"), "scroll-padding": side("scroll-padding-"),
  "overscroll-behavior": ["overscroll-behavior-x", "overscroll-behavior-y"],
  "white-space": ["white-space-collapse", "text-wrap-mode"], "text-wrap": ["text-wrap-mode", "text-wrap-style"],
  "word-wrap": ["overflow-wrap"], "contain-intrinsic-size": ["contain-intrinsic-width", "contain-intrinsic-height"],
};

/** Longhands a declaration sets; two declarations conflict when these intersect. */
export function atoms(prop) {
  const name = prop.toLowerCase();
  if (name.startsWith("--")) return [name];
  const unprefixed = name.replace(/^-(webkit|moz|ms)-(?!mask$)/, "");
  return SHORTHANDS[unprefixed] ?? SHORTHANDS[name] ?? [unprefixed];
}

// ── Stylesheets ────────────────────────────────────────────────────

/**
 * Inlines `@import "file" [layer(name)];` like postcss-import. Returns sources in cascade
 * order: { file, css, layer }.
 */
export function resolveImports(file, readFile = (f) => fs.readFileSync(f, "utf8"), layer = null, seen = new Set()) {
  const css = readFile(file);
  const out = [];
  const importRe = /^@import\s+["']([^"']+)["']\s*(?:layer\(([\w.-]+)\))?\s*;[ \t]*$/gm;
  let last = 0, match;
  while ((match = importRe.exec(css))) {
    out.push({ file, css: css.slice(last, match.index), layer });
    const target = path.resolve(path.dirname(file), match[1]);
    if (!seen.has(target)) {
      seen.add(target);
      const inner = match[2] ? [layer, match[2]].filter(Boolean).join(".") : layer;
      out.push(...resolveImports(target, readFile, inner, seen));
    }
    last = match.index + match[0].length;
  }
  out.push({ file, css: css.slice(last), layer });
  return out.filter((source) => source.css.trim());
}

/** Layer order in order of first appearance (statements and blocks). */
export function layerOrder(sources) {
  const order = [];
  const note = (name) => { if (name && !order.includes(name)) order.push(name); };
  for (const source of sources) {
    note(source.layer);
    postcss.parse(source.css, { from: source.file }).walkAtRules("layer", (rule) => {
      const outer = [];
      for (let node = rule.parent; node && node.type !== "root"; node = node.parent) {
        if (node.type === "atrule" && node.name === "layer") outer.unshift(node.params.trim());
      }
      for (const name of rule.params.split(",").map((n) => n.trim()).filter(Boolean)) {
        note([source.layer, ...outer, name].filter(Boolean).join("."));
      }
    });
  }
  return order;
}

/** Selectors of a rule with CSS nesting resolved (`&` or a descendant of the parent rule). */
function nestedSelectors(rule) {
  const own = splitTop(rule.selector, ",");
  let parent = rule.parent;
  while (parent && parent.type === "atrule") parent = parent.parent;
  if (!parent || parent.type !== "rule") return own;
  const outer = nestedSelectors(parent);
  return outer.flatMap((p) => own.map((c) => (c.includes("&") ? c.replaceAll("&", outer.length > 1 ? `:is(${p})` : p) : `${p} ${c}`)));
}

/** Declarations in cascade order. Rules inside @keyframes are skipped. */
export function flatten(sources) {
  const decls = [];
  let order = 0;
  for (const source of sources) {
    postcss.parse(source.css, { from: source.file }).walkDecls((decl) => {
      const rule = decl.parent;
      if (!rule || rule.type !== "rule") return;
      const selectors = nestedSelectors(rule);
      const layers = [], contexts = [];
      for (let node = rule.parent; node && node.type !== "root"; node = node.parent) {
        if (node.type !== "atrule") continue;
        if (/keyframes$/.test(node.name)) return;
        if (node.name === "layer") layers.unshift(node.params.trim() || "<anonymous>");
        else contexts.unshift(`@${node.name} ${node.params}`);
      }
      for (const selector of selectors) {
        decls.push({
          file: source.file, line: decl.source?.start?.line ?? 0, selector,
          spec: specificity(selector), variants: subjectVariants(selector),
          prop: decl.prop.toLowerCase(), atoms: atoms(decl.prop), value: decl.value.replace(/\s+/g, " ").trim(),
          important: Boolean(decl.important), layer: [source.layer, ...layers].filter(Boolean).join(".") || null,
          context: contexts.join(" "), order: order++,
        });
      }
    });
  }
  return decls;
}

/** Identity of a declaration, independent of file, layer and position. */
export function declarationKey(decl) {
  return `${decl.selector.replace(/\s+/g, " ")}\u0000${decl.context}\u0000${decl.prop}\u0000${decl.value}\u0000${decl.important}`;
}

// ── Which classes can share an element ─────────────────────────────

const CLASS_TOKEN = /^-?[_a-zA-Z][\w-]*$/;
const NON_VALUE = new Set(["true", "false", "null", "undefined", "clsx", "cx", "classNames", "join", "filter", "Boolean", "trim", "map", "length"]);
const TEMPLATE_INTERPOLATION = /\$\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}/g;
const STRING_LITERAL = /"((?:[^"\\\n]|\\.)*)"|'((?:[^'\\\n]|\\.)*)'|`((?:\$\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\}|[^`\\]|\\.)*)`/g;

function closingBrace(text, start) {
  let depth = 0, quote = null;
  for (let i = start; i < text.length; i++) {
    const ch = text[i];
    if (quote) {
      if (ch === "\\") { i++; continue; }
      if (quote === "`" && ch === "$" && text[i + 1] === "{") { i = closingBrace(text, i + 1) - 1; continue; }
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === "`") quote = ch;
    else if (ch === "{") depth++;
    else if (ch === "}" && --depth === 0) return i + 1;
  }
  return text.length;
}

/** Identifiers used as values (not as conditions or helper names) in an expression. */
function valueIdentifiers(code) {
  const rest = code
    .replace(/\.(filter|join|trim|map)\([^()]*\)/g, "")
    .replace(/\b(clsx|cx|classNames)\s*\(/g, "(")
    .replace(/[!\w$.[\]()'"]+\s*(?:===|!==|==|!=|<=|>=|<|>)\s*[!\w$.[\]()'"-]+/g, " ")
    .replace(/[!\w$.[\]]+\s*(?=\?(?!\.)|&&|\|\|)/g, " ");
  return (rest.match(/[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*/g) ?? []).filter((id) => !NON_VALUE.has(id.split(".")[0]));
}

/** Class tokens, class prefixes ("ob-" from `ob-${side}`) and value identifiers of a className expression. */
export function classExpression(expr) {
  const tokens = [], prefixes = [], identifiers = [];
  let stripped = expr;
  for (const m of expr.matchAll(STRING_LITERAL)) {
    stripped = stripped.replace(m[0], '""');
    if (m[3] == null) {
      for (const word of (m[1] ?? m[2] ?? "").split(/\s+/)) if (CLASS_TOKEN.test(word)) tokens.push(word);
      continue;
    }
    const body = m[3];
    const parts = body.split(/\$\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\}/);
    const interpolations = [...body.matchAll(TEMPLATE_INTERPOLATION)].map((x) => x[1]);
    parts.forEach((part, index) => {
      const words = part.split(/\s+/);
      const beforeInterpolation = index < parts.length - 1 && part && !/\s$/.test(part);
      words.forEach((word, wi) => {
        if (!word) return;
        if (wi === 0 && index > 0 && !/^\s/.test(part)) return; // suffix of an interpolation
        if (wi === words.length - 1 && beforeInterpolation) { prefixes.push(word); return; }
        if (CLASS_TOKEN.test(word)) tokens.push(word);
      });
    });
    interpolations.forEach((inner, index) => {
      const sub = classExpression(inner);
      const prefixed = parts[index] && !/\s$/.test(parts[index]);
      tokens.push(...sub.tokens);
      prefixes.push(...sub.prefixes);
      if (!prefixed) identifiers.push(...sub.identifiers);
    });
  }
  identifiers.push(...valueIdentifiers(stripped));
  return { tokens, prefixes, identifiers };
}

function walkFiles(dir, accept, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) { if (entry.name !== "__tests__" && entry.name !== "node_modules") walkFiles(full, accept, out); }
    else if (accept(entry.name)) out.push(full);
  }
  return out;
}

/** Name of the component whose body contains `index` (last PascalCase function before it). */
function enclosingComponent(text, index) {
  const head = text.slice(0, index);
  let name = null;
  for (const m of head.matchAll(/(?:function\s+([A-Z]\w*)\s*\(|(?:const|let)\s+([A-Z]\w*)\s*=\s*(?:\w+\()?\s*(?:\([^)]*\)|\w+)\s*=>|(?:const|let)\s+([A-Z]\w*)\s*=\s*(?:memo|forwardRef)\()/g)) {
    name = m[1] ?? m[2] ?? m[3];
  }
  return name;
}

/**
 * Scans TSX/TS sources for how classes reach elements. Returns a model for `canShareElement`.
 * `extraWildcards` are classes created outside the app source (third-party DOM).
 */
export function scanClassUsage(srcDir, { foreignClasses = [], cssClasses = new Set() } = {}) {
  const pairs = new Set();
  const addPairs = (list) => {
    for (let i = 0; i < list.length; i++) {
      for (let j = i + 1; j < list.length; j++) {
        if (list[i] !== list[j]) pairs.add(list[i] < list[j] ? `${list[i]} ${list[j]}` : `${list[j]} ${list[i]}`);
      }
    }
  };
  const literal = new Set();         // applied literally somewhere
  const wildcards = new Set();       // may meet any class (DOM APIs)
  const prefixGroups = [];           // { tokens, prefixes }
  const wildcardPrefixes = new Set();
  const forwardedTo = new Map();     // component -> classes passed to its className prop
  const sinks = new Map();           // component -> static classes of DOM className expressions that also take its className prop
  const relays = [];                 // [from component, to component]: <To className={...className...}> inside From
  // Classes written as plain strings (variables, helpers) reach className expressions that take
  // values in the same file, or in components that file passes values to. Strings in plain .ts
  // helpers may reach any such expression.
  const routed = new Set();          // all such classes
  const routedIn = new Map();        // file (or "*" for helpers) -> classes
  const sinksIn = new Map();         // file -> static classes of DOM className expressions that also take values
  const routesTo = new Map();        // file -> components it passes className values to
  const templatePrefixes = new Set();
  const add = (map, key, values) => { if (!map.has(key)) map.set(key, new Set()); for (const v of values) map.get(key).add(v); };

  for (const file of walkFiles(srcDir, (name) => /\.(tsx|ts)$/.test(name) && !/\.test\.|\.browser\.|\.d\.ts$/.test(name))) {
    const text = fs.readFileSync(file, "utf8");
    const classValues = [];
    for (const m of text.matchAll(/\b([a-zA-Z]*[cC]lass[Nn]ame)\s*=\s*/g)) {
      const start = m.index + m[0].length;
      let value;
      if (text[start] === "{") value = text.slice(start + 1, closingBrace(text, start) - 1);
      else if (text[start] === '"' || text[start] === "'") value = text.slice(start, text.indexOf(text[start], start + 1) + 1);
      else continue;
      classValues.push([start, start + value.length + 2]);
      const tagMatch = /<\s*([A-Za-z][\w.]*)(?![\s\S]*<\s*[A-Za-z])/.exec(text.slice(Math.max(0, m.index - 2000), m.index));
      const tag = tagMatch?.[1] ?? "";
      const expr = classExpression(value);
      for (const t of expr.tokens) literal.add(t);
      addPairs(expr.tokens);
      if (expr.prefixes.length) prefixGroups.push({ tokens: expr.tokens, prefixes: expr.prefixes });
      const component = enclosingComponent(text, m.index);
      const usesClassNameProp = expr.identifiers.some((id) => /^(props\.)?className$/.test(id));
      const otherValues = expr.identifiers.some((id) => !/^(props\.)?className$/.test(id));
      if (/^[A-Z]/.test(tag.split(".").pop()) && m[1] === "className") {
        const target = tag.split(".").pop();
        add(forwardedTo, target, expr.tokens);
        if (usesClassNameProp && component) relays.push([component, target]);
        if (otherValues) add(routesTo, file, [target]);
      } else if (/^[a-z]/.test(tag) && m[1] === "className") {
        if (usesClassNameProp && component) add(sinks, component, expr.tokens.length ? expr.tokens : ["\u0000none"]);
        if (otherValues) add(sinksIn, file, expr.tokens);
      } else {
        // Another *ClassName prop: where it lands is not known.
        for (const t of expr.tokens) routed.add(t);
        add(routedIn, "*", expr.tokens);
      }
    }
    for (const sm of text.matchAll(STRING_LITERAL)) {
      if (classValues.some(([a, b]) => sm.index >= a && sm.index < b)) continue;
      if (/^\s*(import|export|from)\b/.test(text.slice(text.lastIndexOf("\n", sm.index) + 1, sm.index))) continue;
      const body = sm[1] ?? sm[2] ?? sm[3] ?? "";
      const shaped = sm[3] != null ? body.replace(TEMPLATE_INTERPOLATION, " ") : body;
      if (/^\s*-?[_a-zA-Z][\w-]*(\s+-?[_a-zA-Z][\w-]*)*\s*$/.test(shaped)) {
        for (const word of shaped.split(/\s+/)) {
          if (!word || !CLASS_TOKEN.test(word) || !cssClasses.has(word)) continue;
          routed.add(word);
          add(routedIn, file.endsWith(".tsx") ? file : "*", [word]);
        }
      }
      const context = text.slice(Math.max(0, sm.index - 300), sm.index);
      if (sm[3] != null && /class/i.test(context) && !/(data-testid|testId|aria-[\w-]+)\s*=\s*\{?\s*$/.test(context)) {
        for (const pm of body.matchAll(/(-?[_a-zA-Z][\w-]*-)\$\{/g)) templatePrefixes.add(pm[1]);
      }
    }
    for (const dm of text.matchAll(/classList\.(?:add|toggle|remove|replace)\(([^)]*)\)|setAttribute\(\s*["']class["']\s*,\s*([^)]*)\)|\.className\s*=\s*([^;\n]+)|class=\\?"([^"\\]+)/g)) {
      const body = dm[1] ?? dm[2] ?? dm[3] ?? dm[4] ?? "";
      for (const word of body.match(/[-\w]+/g) ?? []) wildcards.add(word);
      for (const p of classExpression(body).prefixes) wildcardPrefixes.add(p);
    }
  }
  // Classes passed down through wrapper components reach the inner component's sinks too.
  for (let changed = true; changed;) {
    changed = false;
    for (const [from, to] of relays) {
      const before = forwardedTo.get(to)?.size ?? 0;
      add(forwardedTo, to, forwardedTo.get(from) ?? []);
      if ((forwardedTo.get(to)?.size ?? 0) !== before) changed = true;
    }
  }
  // Prefix templates outside className values may generate classes nobody writes literally.
  for (const c of cssClasses) {
    if (!literal.has(c) && !routed.has(c) && [...templatePrefixes].some((p) => c.startsWith(p))) wildcards.add(c);
  }
  // Where a file's routed strings can land: its own value-taking expressions, and the sinks of
  // components it passes values to (and their relays).
  const landing = new Map(); // file -> classes
  const allSinks = new Set([...sinksIn.values()].flatMap((set) => [...set]));
  for (const file of new Set([...routedIn.keys(), ...sinksIn.keys(), ...routesTo.keys()])) {
    const targets = new Set(routesTo.get(file) ?? []);
    for (let changed = true; changed;) {
      changed = false;
      for (const [from, to] of relays) if (targets.has(from) && !targets.has(to)) { targets.add(to); changed = true; }
    }
    add(landing, file, sinksIn.get(file) ?? []);
    for (const target of targets) add(landing, file, sinks.get(target) ?? []);
  }
  const helperLanding = new Set([...allSinks, ...[...sinks.values()].flatMap((set) => [...set])]);
  landing.set("*", helperLanding);
  return { pairs, literal, wildcards, prefixGroups, wildcardPrefixes: [...wildcardPrefixes], forwardedTo, sinks, routed, routedIn, landing, foreign: new Set(foreignClasses) };
}

/** Could two classes be on one element? Unknown routes answer yes; classes no code applies answer no. */
export function canShareElement(usage, containment = null) {
  const sinkOf = new Map();
  for (const [component, classes] of usage.sinks) for (const c of classes) {
    if (!sinkOf.has(c)) sinkOf.set(c, new Set());
    sinkOf.get(c).add(component);
  }
  const forwardedComponents = new Map();
  for (const [component, classes] of usage.forwardedTo) for (const c of classes) {
    if (!forwardedComponents.has(c)) forwardedComponents.set(c, new Set());
    forwardedComponents.get(c).add(component);
  }
  const generated = (c) => usage.prefixGroups.some((g) => g.prefixes.some((p) => c.startsWith(p)));
  const wildPrefix = (c) => usage.wildcardPrefixes.some((p) => c.startsWith(p));
  const live = (c) => usage.foreign.has(c) || usage.literal.has(c) || usage.routed.has(c) || usage.wildcards.has(c) || generated(c) || wildPrefix(c) || forwardedComponents.has(c);
  const reachesSinkOf = (forwarded, sink) => {
    for (const component of forwardedComponents.get(forwarded) ?? []) if (sinkOf.get(sink)?.has(component)) return true;
    return false;
  };
  const routedFiles = new Map();
  for (const [file, classes] of usage.routedIn) for (const c of classes) {
    if (!routedFiles.has(c)) routedFiles.set(c, new Set());
    routedFiles.get(c).add(file);
  }
  /** x arrives through a string in some file whose values can land on an element with y (or x and y both arrive that way). */
  const routedMeets = (x, y) => {
    for (const file of routedFiles.get(x) ?? []) {
      if (usage.landing.get(file)?.has(y) || usage.routedIn.get(file)?.has(y)) return true;
    }
    return false;
  };
  // Third-party DOM (Monaco, the chart library) carries only its own classes; a name both
  // sides use (such as "active") can be on either kind of element.
  const app = (c) => appLive(c);
  const appLive = (c) => usage.literal.has(c) || usage.routed.has(c) || usage.wildcards.has(c) || generated(c) || wildPrefix(c) || forwardedComponents.has(c);
  const share = (x, y) => {
    if (!live(x) || !live(y)) return false;
    if (x === y) return true;
    const fx = usage.foreign.has(x), fy = usage.foreign.has(y);
    if (fx && fy) return true; // both can be on a third-party element
    if ((fx && !app(x)) || (fy && !app(y))) return false; // third-party only meets third-party
    // Otherwise the element is one of the app's own: the app's rules decide.
    if (usage.wildcards.has(x) || usage.wildcards.has(y) || wildPrefix(x) || wildPrefix(y)) return true;
    if (usage.pairs.has(x < y ? `${x} ${y}` : `${y} ${x}`)) return true;
    if (usage.prefixGroups.some((g) => (g.tokens.includes(x) && g.prefixes.some((p) => y.startsWith(p))) || (g.tokens.includes(y) && g.prefixes.some((p) => x.startsWith(p))))) return true;
    if (reachesSinkOf(x, y) || reachesSinkOf(y, x)) return true;
    if (routedMeets(x, y) || routedMeets(y, x)) return true;
    // Two classes forwarded to the same component's className prop by different callers never meet.
    return false;
  };
  if (containment) {
    const known = (x) => containment.has(x);
    /** Can an element with class y sit inside an element with class x? */
    const canContain = (x, y) => {
      if (!known(x)) return true;
      const inside = containment.get(x);
      if (inside.has(CONTAINS_UNKNOWN) || inside.has(y)) return true;
      for (const item of inside) if (item.endsWith("*") && y.startsWith(item.slice(0, -1))) return true;
      return false;
    };
    share.canContain = canContain;
    share.nestable = (x, y) => share(x, y) || canContain(x, y) || canContain(y, x);
  }
  share.live = live;
  /** Only third-party DOM carries this class. */
  share.foreignOnly = (c) => usage.foreign.has(c) && !appLive(c);
  /** Only the app's own DOM carries this class. */
  share.appOnly = (c) => !usage.foreign.has(c) && appLive(c);
  return share;
}

// html, body and #root carry no classes in any entry page.
function structural(v) {
  if (v.tag === "html" || v.pseudoClasses.includes("root")) return "html";
  if (v.tag === "body") return "body";
  if (v.ids.includes("root")) return "root";
  return null;
}

/** Could two subject variants match the same element (and pseudo-element)? */
export function compatible(v1, v2, shareElement) {
  if ((v1.pseudoElement ?? null) !== (v2.pseudoElement ?? null)) return false;
  if (v1.tag && v2.tag && v1.tag !== v2.tag) return false;
  if (v1.ids.length && v2.ids.length && v1.ids.some((id) => !v2.ids.includes(id))) return false;
  const s1 = structural(v1), s2 = structural(v2);
  if (s1 || s2) {
    if (s1 && s2) return s1 === s2;
    const [s, other] = s1 ? [s1, v2] : [s2, v1];
    if (other.classes.length || other.ids.length) return false;
    if (other.tag && other.tag !== { html: "html", body: "body", root: "div" }[s]) return false;
    const allowed = { html: [], body: ["html"], root: ["html", "body"] }[s];
    if (other.ancestors.length > allowed.length) return false;
    return other.ancestors.every((a) => !a.classes.length && !a.ids.length && (!a.tag || allowed.includes(a.tag)));
  }
  if (!shareElement) return true;
  // Elements inside third-party DOM (a selector with a third-party ancestor or class) never
  // carry the app's own classes: the app renders nothing inside Monaco or the chart canvas.
  if (shareElement.foreignOnly) {
    const inside = (v) => [...v.classes, ...v.ancestors.flatMap((a) => a.classes)].some(shareElement.foreignOnly);
    const ours = (v) => v.classes.some(shareElement.appOnly);
    if ((inside(v1) && ours(v2)) || (inside(v2) && ours(v1))) return false;
  }
  if (shareElement.nestable) {
    // Every ancestor of one selector and every ancestor of the other sit on the same chain
    // of ancestors, and the subject sits inside all of them.
    const ancestorClasses = (v) => v.ancestors.map((a) => a.classes).filter((list) => list.length);
    const a1 = ancestorClasses(v1), a2 = ancestorClasses(v2);
    for (const left of a1) for (const right of a2) {
      if (!left.some((x) => right.some((y) => shareElement.nestable(x, y)))) return false;
    }
    const subject = [...new Set([...v1.classes, ...v2.classes])];
    for (const compound of [...a1, ...a2]) {
      for (const s of subject) if (!compound.some((x) => shareElement.canContain(x, s))) return false;
    }
  }
  const classes = [...new Set([...v1.classes, ...v2.classes])];
  for (let i = 0; i < classes.length; i++) {
    for (let j = i + 1; j < classes.length; j++) if (!shareElement(classes[i], classes[j])) return false;
  }
  // A selector that needs a class nobody applies matches nothing.
  if (shareElement.live) {
    for (const v of [v1, v2]) {
      for (const c of [...v.classes, ...v.ancestors.flatMap((a) => a.classes)]) if (!shareElement.live(c)) return false;
    }
  }
  return true;
}

// ── Comparing two arrangements ─────────────────────────────────────

function rank(layer, order) {
  if (layer == null) return Infinity;
  const index = order.indexOf(layer);
  if (index < 0) throw new Error(`Layer ${layer} is not in the layer order`);
  return index;
}

/** 1 when a beats b, -1 when b beats a (same origin, same element). */
export function winner(a, b, order) {
  if (a.important !== b.important) return a.important ? 1 : -1;
  const ra = rank(a.layer, order), rb = rank(b.layer, order);
  if (ra !== rb) {
    if (!a.important) return ra > rb ? 1 : -1;
    return ra < rb ? 1 : -1; // important: earlier layers win, unlayered is weakest
  }
  const s = compareSpecificity(a.spec, b.spec);
  if (s) return s > 0 ? 1 : -1;
  return a.order > b.order ? 1 : -1;
}

/**
 * Pairs every declaration of `before` with the same declaration in `after`; throws when
 * the two sets differ. Returns [beforeDecl, afterDecl] pairs.
 */
export function alignDeclarations(before, after) {
  const pool = new Map();
  for (const decl of after) {
    const key = declarationKey(decl);
    if (!pool.has(key)) pool.set(key, []);
    pool.get(key).push(decl);
  }
  const missing = [];
  const aligned = [];
  for (const decl of before) {
    const match = pool.get(declarationKey(decl))?.shift();
    if (match) aligned.push([decl, match]);
    else missing.push(decl);
  }
  const extra = [...pool.values()].flat();
  return { aligned, missing, extra };
}

/**
 * Declaration pairs whose winner differs between two arrangements, for pairs that can
 * style the same element and set different values.
 */
export function cascadeChanges(aligned, { beforeLayers, afterLayers, shareElement }) {
  const groups = new Map();
  aligned.forEach(([b], index) => {
    const pseudo = b.variants[0]?.pseudoElement ?? "";
    for (const atom of b.atoms) {
      const key = `${atom}\u0000${pseudo}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(index);
    }
  });
  const changes = [];
  const seen = new Set();
  for (const members of groups.values()) {
    for (let x = 0; x < members.length; x++) {
      const [b1, a1] = aligned[members[x]];
      for (let y = x + 1; y < members.length; y++) {
        const [b2, a2] = aligned[members[y]];
        if (b1.value === b2.value && b1.prop === b2.prop) continue;
        if (winner(b1, b2, beforeLayers) === winner(a1, a2, afterLayers)) continue;
        const key = members[x] < members[y] ? `${members[x]}:${members[y]}` : `${members[y]}:${members[x]}`;
        if (seen.has(key)) continue;
        seen.add(key);
        if (!b1.variants.some((v1) => b2.variants.some((v2) => compatible(v1, v2, shareElement)))) continue;
        changes.push({ first: b1, second: b2, before: winner(b1, b2, beforeLayers), after: winner(a1, a2, afterLayers) });
      }
    }
  }
  return changes;
}

export function cssClassNames(sources) {
  const names = new Set();
  for (const source of sources) for (const m of source.css.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)) names.add(m[1]);
  return names;
}

// ── Which classes can contain which (JSX structure) ────────────────

const UNKNOWN = "\u0000unknown";

/**
 * Scans TSX with the TypeScript parser and returns, per class, the classes that elements
 * inside an element with that class can carry. A class whose content is not fully known
 * (children passed from unknown places, render props, variables) contains UNKNOWN.
 */
export function scanContainment(srcDir, { tsconfig = path.join(srcDir, "..", "tsconfig.json") } = {}) {
  const ts = require("typescript");
  // Type information tells text values ({price}) from markup ({children}, {icon}).
  const config = ts.getParsedCommandLineOfConfigFile(tsconfig, {}, { ...ts.sys, onUnRecoverableConfigFileDiagnostic: () => {} });
  const program = ts.createProgram({ rootNames: config.fileNames, options: { ...config.options, noEmit: true } });
  const checker = program.getTypeChecker();
  const TEXT = ts.TypeFlags.StringLike | ts.TypeFlags.NumberLike | ts.TypeFlags.BigIntLike | ts.TypeFlags.BooleanLike |
    ts.TypeFlags.Null | ts.TypeFlags.Undefined | ts.TypeFlags.Void | ts.TypeFlags.Never;
  const isText = (expr) => {
    const type = checker.getTypeAtLocation(expr);
    const parts = type.isUnion() ? type.types : [type];
    return parts.every((t) => (t.flags & TEXT) !== 0);
  };
  const components = new Map(); // name -> { classes:Set, subtreeItems: [] } (all classes it can render + components it renders)
  const elements = [];          // { classes, component (enclosing), items: Set(class | "<Comp>" | UNKNOWN | "{children}") }
  const callChildren = new Map(); // component -> Set(items rendered as its JSX children at call sites)

  const enclosingName = (node) => {
    for (let n = node.parent; n; n = n.parent) {
      if ((ts.isFunctionDeclaration(n) || ts.isFunctionExpression(n)) && n.name && /^[A-Z]/.test(n.name.text)) return n.name.text;
      if ((ts.isArrowFunction(n) || ts.isFunctionExpression(n) || ts.isCallExpression(n)) && ts.isVariableDeclaration(n.parent) && ts.isIdentifier(n.parent.name) && /^[A-Z]/.test(n.parent.name.text)) return n.parent.name.text;
    }
    return null;
  };
  const tagName = (el) => (ts.isJsxElement(el) ? el.openingElement.tagName : el.tagName).getText();
  const attributes = (el) => (ts.isJsxElement(el) ? el.openingElement.attributes : el.attributes).properties;
  const classesOf = (el, sf) => {
    for (const attr of attributes(el)) {
      if (!ts.isJsxAttribute(attr) || attr.name.getText(sf) !== "className" || !attr.initializer) continue;
      const text = ts.isStringLiteral(attr.initializer) ? attr.initializer.getText(sf) : attr.initializer.getText(sf).slice(1, -1);
      const expr = classExpression(text);
      return { tokens: expr.tokens, open: expr.identifiers.length > 0 || expr.prefixes.length > 0, prefixes: expr.prefixes };
    }
    return { tokens: [], open: false, prefixes: [] };
  };

  /** Items directly or indirectly inside a JSX node (same file). */
  function contentItems(node, sf, out) {
    const visit = (n) => {
      if (ts.isJsxElement(n) || ts.isJsxSelfClosingElement(n)) {
        const tag = tagName(n);
        if (/^[a-z]/.test(tag)) {
          const c = classesOf(n, sf);
          for (const t of c.tokens) out.add(t);
          for (const p of c.prefixes) out.add(`${p}*`);
          if (c.open) out.add(UNKNOWN); // routed classes on a descendant: unknown names
        } else {
          out.add(`<${tag.split(".").pop()}>`);
          const forwarded = classesOf(n, sf);
          for (const t of forwarded.tokens) out.add(t);
          if (forwarded.open) out.add(UNKNOWN);
          for (const attr of attributes(n)) {
            // Render props and element props render elsewhere inside that component.
            if (ts.isJsxAttribute(attr) && attr.initializer && ts.isJsxExpression(attr.initializer) && attr.initializer.expression) {
              const inner = new Set();
              collectJsx(attr.initializer.expression, sf, inner);
              for (const item of inner) out.add(item);
            }
          }
        }
        if (ts.isJsxElement(n)) n.children.forEach(visit);
        return;
      }
      if (ts.isJsxFragment(n)) { n.children.forEach(visit); return; }
      if (ts.isJsxExpression(n)) {
        if (!n.expression) return;
        const e = n.expression;
        if (ts.isIdentifier(e) && e.text === "children" || ts.isPropertyAccessExpression(e) && e.name.text === "children") { out.add("{children}"); return; }
        const inner = new Set();
        collectJsx(e, sf, inner);
        for (const item of inner) out.add(item);
        // Identifiers, calls and other values may render anything.
        if (containsOpaqueValue(e) && !isText(e)) out.add(UNKNOWN);
        return;
      }
      if (ts.isJsxText(n)) return;
      ts.forEachChild(n, visit);
    };
    visit(node);
    return out;
  }
  function collectJsx(expr, sf, out) {
    let found = false;
    const walk = (n) => {
      if (ts.isJsxElement(n) || ts.isJsxSelfClosingElement(n) || ts.isJsxFragment(n)) { found = true; contentItems(n, sf, out); return; }
      ts.forEachChild(n, walk);
    };
    walk(expr);
    return found;
  }
  /** True when the expression may produce markup that is not written out as JSX here. */
  function containsOpaqueValue(e) {
    if (ts.isJsxElement(e) || ts.isJsxSelfClosingElement(e) || ts.isJsxFragment(e)) return false;
    if (ts.isParenthesizedExpression(e)) return containsOpaqueValue(e.expression);
    if (ts.isConditionalExpression(e)) return containsOpaqueValue(e.whenTrue) || containsOpaqueValue(e.whenFalse);
    if (ts.isBinaryExpression(e) && [ts.SyntaxKind.AmpersandAmpersandToken, ts.SyntaxKind.BarBarToken, ts.SyntaxKind.QuestionQuestionToken].includes(e.operatorToken.kind)) {
      return (e.operatorToken.kind !== ts.SyntaxKind.AmpersandAmpersandToken && containsOpaqueValue(e.left)) || containsOpaqueValue(e.right);
    }
    if (ts.isCallExpression(e)) {
      const callee = e.expression;
      if (ts.isPropertyAccessExpression(callee) && ["map", "flatMap"].includes(callee.name.text)) {
        const fn = e.arguments[0];
        if (fn && (ts.isArrowFunction(fn) || ts.isFunctionExpression(fn))) {
          if (ts.isBlock(fn.body)) {
            let opaque = false;
            const walk = (n) => { if (ts.isReturnStatement(n) && n.expression && containsOpaqueValue(n.expression)) opaque = true; if (!ts.isFunctionLike(n)) ts.forEachChild(n, walk); };
            ts.forEachChild(fn.body, walk);
            return opaque;
          }
          return containsOpaqueValue(fn.body);
        }
      }
    }
    return !isText(e);
  }

  for (const sf of program.getSourceFiles()) {
    const file = sf.fileName;
    if (!file.endsWith(".tsx") || file.includes("node_modules") || /\.test\.|\.browser\.|__tests__/.test(file)) continue;
    const visit = (n) => {
      if (ts.isJsxElement(n) || ts.isJsxSelfClosingElement(n)) {
        const tag = tagName(n);
        const component = enclosingName(n);
        const items = new Set();
        if (ts.isJsxElement(n)) for (const child of n.children) contentItems(child, sf, items);
        if (/^[a-z]/.test(tag)) {
          const c = classesOf(n, sf);
          elements.push({ classes: c.tokens, prefixes: c.prefixes, items });
          if (component) {
            if (!components.has(component)) components.set(component, new Set());
            for (const t of c.tokens) components.get(component).add(t);
            for (const p of c.prefixes) components.get(component).add(`${p}*`);
            if (c.open) components.get(component).add(UNKNOWN);
          }
        } else {
          const name = tag.split(".").pop();
          if (!callChildren.has(name)) callChildren.set(name, new Set());
          for (const item of items) callChildren.get(name).add(item);
          if (component) {
            if (!components.has(component)) components.set(component, new Set());
            components.get(component).add(`<${name}>`);
          }
        }
        for (const item of items) if (component && item !== "{children}") {
          if (!components.has(component)) components.set(component, new Set());
          components.get(component).add(item);
        }
      }
      ts.forEachChild(n, visit);
    };
    visit(sf);
  }

  // Expand component references and {children} to classes (fixed point).
  const expandItems = (items, seen = new Set()) => {
    const out = new Set();
    for (const item of items) {
      if (item === "{children}") continue; // handled by the caller
      if (item.startsWith("<")) {
        const name = item.slice(1, -1);
        if (seen.has(name)) continue;
        seen.add(name);
        if (!components.has(name)) { out.add(UNKNOWN); continue; } // library or unresolved component
        for (const c of expandItems(components.get(name), seen)) out.add(c);
        // A component's {children} come from its call sites.
        for (const c of expandItems(callChildren.get(name) ?? [], seen)) out.add(c);
      } else out.add(item);
    }
    return out;
  };
  const contains = new Map(); // class -> Set
  for (const el of elements) {
    const items = new Set(el.items);
    if (items.has("{children}")) {
      // The element renders its component's children: everything callers pass.
      items.delete("{children}");
      items.add(UNKNOWN_CHILDREN);
    }
    const expanded = expandItems([...items].filter((i) => i !== UNKNOWN_CHILDREN));
    if (items.has(UNKNOWN_CHILDREN)) expanded.add(UNKNOWN_CHILDREN);
    for (const c of el.classes) {
      if (!contains.has(c)) contains.set(c, new Set());
      for (const x of expanded) contains.get(c).add(x);
    }
  }
  // Resolve {children} per enclosing component is approximated: any element that renders
  // {children} may contain anything any caller of any component passes. Keep it unknown.
  for (const set of contains.values()) if (set.has(UNKNOWN_CHILDREN)) { set.delete(UNKNOWN_CHILDREN); set.add(UNKNOWN); }
  return contains;
}
const UNKNOWN_CHILDREN = "\u0000children";
export const CONTAINS_UNKNOWN = UNKNOWN;
