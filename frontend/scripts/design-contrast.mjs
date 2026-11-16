#!/usr/bin/env node
// Design contrast audit: opens the named design states (design-snapshots.mjs) in each theme and
// measures every visible piece of text against the background it is drawn on, as rendered.
// Text below WCAG AA (4.5:1, or 3:1 for large text) is reported, grouped by colour pair and
// component so one fix covers many elements.
//
// Requires the Vite dev server and the backend, like the snapshots.
//
//   node scripts/design-contrast.mjs                         # all states, dark and light
//   node scripts/design-contrast.mjs --states market,alerts --themes light
//   node scripts/design-contrast.mjs --label before          # writes output/design-contrast/<label>/report.json
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { BLOCK_WRITES, SETTINGS_KEY, STATES, findChrome, openBrowser, parseArgs as parseSnapshotArgs, visitState } from "./design-snapshots.mjs";

/** Parses `rgb(...)` / `rgba(...)` (as getComputedStyle returns them) into [r, g, b, a]. */
export function parseColor(value) {
  const match = /^rgba?\(([^)]+)\)$/.exec(String(value).trim());
  if (!match) return null;
  const parts = match[1].split(/[\s,/]+/).filter(Boolean).map(Number);
  if (parts.length < 3 || parts.slice(0, 3).some((n) => !Number.isFinite(n))) return null;
  return [parts[0], parts[1], parts[2], parts.length > 3 && Number.isFinite(parts[3]) ? parts[3] : 1];
}

/** `top` drawn over an opaque `bottom`. */
export function composite(top, bottom) {
  const alpha = top[3];
  return [0, 1, 2].map((i) => top[i] * alpha + bottom[i] * (1 - alpha)).concat(1);
}

export function relativeLuminance([r, g, b]) {
  const [R, G, B] = [r, g, b].map((v) => v / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * R + 0.7152 * G + 0.0722 * B;
}

export function contrastRatio(a, b) {
  const [hi, lo] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** WCAG AA: 3:1 for large text (24px, or 18.66px bold), 4.5:1 otherwise. */
export function requiredRatio(fontSizePx, fontWeight) {
  return fontSizePx >= 24 || (fontSizePx >= 18.66 && fontWeight >= 700) ? 3 : 4.5;
}

// Runs in the page. The helpers above are passed in as source so the page and the tests share them.
export const AUDIT = `(helpers) => {
  const { parseColor, composite, contrastRatio, requiredRatio } = Object.fromEntries(
    Object.entries(helpers).map(([name, source]) => [name, (0, eval)("(" + source + ")")]));
  const results = [];
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1 || r.bottom < 0 || r.right < 0 || r.top > innerHeight || r.left > innerWidth) return false;
    const s = getComputedStyle(el);
    return s.visibility !== "hidden" && s.display !== "none";
  };
  const describe = (el) => {
    const parts = [];
    for (let node = el; node && node !== document.body && parts.length < 3; node = node.parentElement) {
      const cls = [...node.classList].filter((c) => !/^_|^\\d/.test(c)).slice(0, 2).join(".");
      parts.unshift(node.tagName.toLowerCase() + (cls ? "." + cls : ""));
    }
    return parts.join(" > ");
  };
  // Background behind an element: its own and its ancestors' colours, composited down to the page.
  const background = (el) => {
    const layers = [];
    for (let node = el; node; node = node.parentElement) {
      const s = getComputedStyle(node);
      if (s.backgroundImage && s.backgroundImage !== "none") return { uncertain: true };
      const color = parseColor(s.backgroundColor);
      if (color && color[3] > 0) layers.push(color);
      if (color && color[3] >= 1) break;
    }
    let base = [255, 255, 255, 1];
    for (const layer of layers.reverse()) base = composite(layer, base);
    return { color: base };
  };
  const opacity = (el) => { let o = 1; for (let n = el; n; n = n.parentElement) o *= Number(getComputedStyle(n).opacity || 1); return o; };
  const check = (el, text, fgValue) => {
    if (el.closest(":disabled, [aria-disabled=true], [inert], svg, canvas")) return;
    const fg = parseColor(fgValue);
    if (!fg) return;
    const bg = background(el);
    if (bg.uncertain) return;
    const s = getComputedStyle(el);
    const alpha = fg[3] * opacity(el);
    const shown = composite([fg[0], fg[1], fg[2], alpha], bg.color);
    const ratio = contrastRatio(shown, bg.color);
    const need = requiredRatio(parseFloat(s.fontSize), Number(s.fontWeight) || 400);
    if (ratio + 0.005 < need) {
      results.push({
        where: describe(el), text: text.slice(0, 40), ratio: Math.round(ratio * 100) / 100, need,
        fg: "rgb(" + shown.slice(0, 3).map(Math.round).join(",") + ")", bg: "rgb(" + bg.color.slice(0, 3).map(Math.round).join(",") + ")",
        size: s.fontSize,
      });
    }
  };
  for (const el of document.querySelectorAll("body *")) {
    if (!visible(el)) continue;
    const text = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join("").replace(/\\s+/g, " ").trim();
    if (text) check(el, text, getComputedStyle(el).color);
    if ((el.tagName === "INPUT" || el.tagName === "TEXTAREA") && el.placeholder && !el.value) {
      check(el, el.placeholder, getComputedStyle(el, "::placeholder").color);
    }
  }
  return results;
}`;

/** Groups failures that share colours and component, so one fix covers them. */
export function groupFailures(failures) {
  const groups = new Map();
  for (const item of failures) {
    const key = [item.state, item.theme, item.fg, item.bg, item.where].join("|");
    const group = groups.get(key) ?? { ...item, count: 0, texts: [] };
    group.count += 1;
    if (group.texts.length < 4 && !group.texts.includes(item.text)) group.texts.push(item.text);
    groups.set(key, group);
  }
  return [...groups.values()].sort((a, b) => a.ratio - b.ratio);
}

export function parseArgs(argv) {
  const args = parseSnapshotArgs(argv);
  if (!argv.includes("--out")) args.out = path.resolve(import.meta.dirname, "../../output/design-contrast", args.label);
  return args;
}

async function audit(args) {
  const chromePath = findChrome(args.chromePath);
  if (!chromePath) throw new Error("Chrome or Edge was not found. Set CHROME_PATH or pass --chrome.");
  fs.mkdirSync(args.out, { recursive: true });
  const states = args.states.length ? STATES.filter((state) => args.states.includes(state.name)) : STATES;
  const helpers = Object.fromEntries([parseColor, composite, contrastRatio, requiredRatio].map((fn) => [fn.name, fn.toString()]));
  // relativeLuminance is used by contrastRatio; inline it in its source.
  helpers.contrastRatio = `(a, b) => { const relativeLuminance = ${relativeLuminance.toString()}; return (${contrastRatio.toString()})(a, b); }`;
  const failures = [];
  const visited = [];
  for (const theme of args.themes) {
    const browser = await openBrowser(chromePath);
    try {
      await browser.send("Page.enable");
      await browser.send("Page.addScriptToEvaluateOnNewDocument", {
        source: `try { const k = ${JSON.stringify(SETTINGS_KEY)}; const s = JSON.parse(localStorage.getItem(k) || "{}");
          s.theme = ${JSON.stringify(theme)}; s.locale = ${JSON.stringify(args.locale)}; localStorage.setItem(k, JSON.stringify(s)); } catch {}`,
      });
      await browser.send("Page.addScriptToEvaluateOnNewDocument", { source: BLOCK_WRITES });
      for (const viewport of args.viewports) {
        await browser.send("Emulation.setDeviceMetricsOverride", { ...viewport, deviceScaleFactor: 1, mobile: false });
        for (const state of states) {
          const problems = await visitState(browser, args, state);
          const result = await browser.send("Runtime.evaluate", {
            expression: `(${AUDIT})(${JSON.stringify(helpers)})`, returnByValue: true,
          });
          const found = result.result?.result?.value ?? [];
          if (result.result?.exceptionDetails) problems.push(`audit error: ${result.result.exceptionDetails.exception?.description ?? result.result.exceptionDetails.text}`);
          for (const item of found) failures.push({ state: state.name, theme, ...item });
          visited.push({ state: state.name, theme, viewport, failures: found.length, problems });
          console.log(`${found.length ? "✗" : "✓"} ${state.name} ${theme} ${viewport.width}x${viewport.height}: ${found.length} below AA${problems.length ? `  (${problems.join("; ")})` : ""}`);
        }
      }
    } finally {
      await browser.close();
    }
  }
  const groups = groupFailures(failures);
  const report = { label: args.label, url: args.url, locale: args.locale, auditedAt: new Date().toISOString(), visited, total: failures.length, groups };
  fs.writeFileSync(path.join(args.out, "report.json"), `${JSON.stringify(report, null, 2)}\n`);
  console.log(`\n${failures.length} text elements below AA in ${groups.length} groups: ${path.join(args.out, "report.json")}`);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  audit(parseArgs(process.argv.slice(2))).catch((error) => {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  });
}
