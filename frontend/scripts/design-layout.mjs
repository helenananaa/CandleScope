#!/usr/bin/env node
// Design layout audit: opens the named design states (design-snapshots.mjs) at several window
// widths and interface languages, and lists what does not fit, as rendered:
//
//   Cut text     text an element cuts off (an ellipsis, or clipped), a select whose chosen option
//                is wider than the select, and text cut by an ancestor that clips it.
//   Spills       text wider than its own box that runs over what is next to it.
//   Overlaps     controls that sit on top of each other (in the same toolbar or row).
//
// Text that scrolls (a scroll container) is not cut. A finding whose full text is one hover away
// (a title or the accessible name) is marked `hover`: names, ids and messages of any length may be
// shortened that way; labels the interface writes itself should fit. Every visit is also captured.
// Requires the Vite dev server and the backend, like the snapshots. Writes are refused.
//
//   node scripts/design-layout.mjs                                   # all states, 4 widths, zh-CN en de ru
//   node scripts/design-layout.mjs --states market --locales en,de --viewports 1024x768
//   (report: output/design-layout/<label>/report.json, captures alongside)
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { BLOCK_WRITES, SETTINGS_KEY, STATES, findChrome, openBrowser, parseArgs as parseSnapshotArgs, visitState } from "./design-snapshots.mjs";

export const DEFAULT_VIEWPORTS = [
  { width: 1024, height: 768 }, { width: 1366, height: 768 }, { width: 1440, height: 900 }, { width: 1920, height: 1080 },
];
export const DEFAULT_LOCALES = ["zh-CN", "en", "de", "ru"];

/** Whether a box of `content` px fits in `room` px, with a pixel of rounding. */
export function overflows(content, room) {
  return content > room + 1;
}

/** Two boxes overlap by more than `slack` px on both axes. */
export function boxesOverlap(a, b, slack = 2) {
  const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
  const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
  return x > slack && y > slack;
}

/** The full text of a shortened finding is one hover away (its title or accessible name). */
export function hasFullText(item) {
  const text = (item.text ?? "").replace(/[…\s]+$/, "");
  return Boolean(text) && item.kind !== "overlap" && item.kind !== "spill" && (item.full ?? "").includes(text) && (item.full ?? "").length >= text.length;
}

/** Groups findings that share a kind, component and text, across visits. */
export function groupFindings(findings) {
  const groups = new Map();
  for (const item of findings) {
    const key = [item.kind, item.where, item.text].join("|");
    const group = groups.get(key) ?? { kind: item.kind, where: item.where, text: item.text, full: item.full, hover: hasFullText(item), visits: [] };
    group.visits.push(`${item.state} ${item.locale} ${item.viewport}`);
    groups.set(key, group);
  }
  return [...groups.values()].sort((a, b) => b.visits.length - a.visits.length);
}

// Runs in the page. Helpers come in as source so the page and the tests share them.
export const AUDIT = `(helpers) => {
  const { overflows, boxesOverlap } = Object.fromEntries(
    Object.entries(helpers).map(([name, source]) => [name, (0, eval)("(" + source + ")")]));
  const found = [];
  const SKIP = "svg, canvas, .monaco-editor, .ui-visually-hidden, .sr-only, [inert], option, script, style";
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || r.bottom <= 0 || r.right <= 0 || r.top >= innerHeight || r.left >= innerWidth) return false;
    // Also hidden: what a closed <details> holds (Chrome still gives it boxes) and anything faded out.
    if (el.checkVisibility && !el.checkVisibility({ opacityProperty: true, visibilityProperty: true, contentVisibilityAuto: true })) return false;
    const s = getComputedStyle(el);
    return s.visibility !== "hidden" && s.display !== "none" && Number(s.opacity) > 0;
  };
  const describe = (el) => {
    const parts = [];
    for (let node = el; node && node !== document.body && parts.length < 3; node = node.parentElement) {
      const cls = [...node.classList].filter((c) => !/^_|^\\d/.test(c)).slice(0, 2).join(".");
      parts.unshift(node.tagName.toLowerCase() + (cls ? "." + cls : ""));
    }
    return parts.join(" > ");
  };
  const ownText = (el) => [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join("").replace(/\\s+/g, " ").trim();
  // Sideways only: a list that scrolls down but hides what is wider than it still cuts.
  const clips = (s) => s.overflowX !== "visible";
  const scrolls = (s) => /auto|scroll/.test(s.overflowX);
  const canvas = document.createElement("canvas").getContext("2d");
  const textWidth = (text, s) => { canvas.font = s.fontWeight + " " + s.fontSize + " " + s.fontFamily; return canvas.measureText(text).width; };
  const add = (kind, el, text, full) => found.push({ kind, where: describe(el), text: text.slice(0, 48), full: (full || "").slice(0, 120) });
  // Each element's box as shown: cut to every ancestor that clips (a scrolled strip hides its chips,
  // a header hides what wrapped onto its second line).
  const shown = (el) => {
    const r = el.getBoundingClientRect();
    let box = { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
    for (let node = el.parentElement; node && node !== document.body; node = node.parentElement) {
      const ns = getComputedStyle(node);
      if (ns.overflowX === "visible" && ns.overflowY === "visible") continue;
      const c = node.getBoundingClientRect();
      box = { left: Math.max(box.left, c.left), top: Math.max(box.top, c.top), right: Math.min(box.right, c.right), bottom: Math.min(box.bottom, c.bottom) };
    }
    return box.right - box.left > 2 && box.bottom - box.top > 2 ? box : null;
  };
  for (const el of document.querySelectorAll("body *")) {
    if (el.closest(SKIP) || !visible(el) || !shown(el)) continue;
    const s = getComputedStyle(el);
    if (el.tagName === "SELECT") {
      const option = el.selectedOptions?.[0];
      if (!option) continue;
      // Room for the chosen option: the content box, less the native arrow (16 px in Chrome) and
      // any icon drawn over the content box (a chevron placed on top of the select, past its padding).
      const box = el.getBoundingClientRect();
      const left = box.left + parseFloat(s.borderLeftWidth) + parseFloat(s.paddingLeft);
      const right = box.right - parseFloat(s.borderRightWidth) - parseFloat(s.paddingRight);
      let room = right - left - (s.appearance === "none" ? 0 : 16);
      for (const sibling of el.parentElement?.children ?? []) {
        if (sibling === el || !visible(sibling)) continue;
        const r = sibling.getBoundingClientRect();
        const covered = Math.min(r.right, right) - Math.max(r.left, left);
        if (covered > 0 && r.top < box.bottom && r.bottom > box.top) room -= covered;
      }
      if (overflows(textWidth(option.textContent.trim(), s), room)) add("select", el, option.textContent.trim(), el.getAttribute("title") || "");
      continue;
    }
    if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") continue;
    const text = ownText(el);
    if (!text) continue;
    // The element cuts its own text (an ellipsis, or clip).
    const clamped = s.webkitLineClamp !== "none" && s.overflowY !== "visible" && overflows(el.scrollHeight, el.clientHeight);
    if ((clips(s) && !scrolls(s) && overflows(el.scrollWidth, el.clientWidth)) || clamped) {
      add("cut", el, text, el.getAttribute("title") || el.closest("[title]")?.getAttribute("title") || el.getAttribute("aria-label") || "");
      continue;
    }
    // The text is wider than its own box and runs over what is next to it.
    if (!clips(s) && !/^(inline|contents)$/.test(s.display) && overflows(el.scrollWidth, el.clientWidth)) {
      add("spill", el, text, el.getAttribute("title") || el.getAttribute("aria-label") || "");
      continue;
    }
    // An ancestor clips it: the text runs past the nearest clipping box.
    const range = document.createRange();
    range.selectNodeContents(el);
    const r = range.getBoundingClientRect();
    for (let node = el.parentElement; node && node !== document.body; node = node.parentElement) {
      const ns = getComputedStyle(node);
      if (!clips(ns)) continue;
      if (scrolls(ns)) break;
      const box = node.getBoundingClientRect();
      if (overflows(r.right, box.right) || overflows(box.left, r.left)) add("clipped", el, text, el.closest("[title]")?.getAttribute("title") || "");
      break;
    }
  }
  // Controls on top of each other inside the same group (a toolbar, a header, a row).
  // A button drawn inside a field, over room the field keeps for it (a date picker, a clear button).
  const insideField = (field, button) => {
    if (!/^(INPUT|SELECT|TEXTAREA)$/.test(field.tagName)) return false;
    const f = field.getBoundingClientRect(), b = button.getBoundingClientRect(), fs = getComputedStyle(field);
    const right = f.right - b.left, left = b.right - f.left;
    return (b.left >= f.left + f.width / 2 && parseFloat(fs.paddingRight) + 2 >= right) || (b.right <= f.left + f.width / 2 && parseFloat(fs.paddingLeft) + 2 >= left);
  };
  const controls = [...document.querySelectorAll("button, a[href], input:not([type=hidden]), select, [role=button], [role=tab]")]
    .filter((el) => !el.closest(SKIP) && visible(el)).map((el) => ({ el, box: shown(el) })).filter((c) => c.box);
  const near = (a, b) => { let n = a; for (let i = 0; i < 3 && n; i++) { n = n.parentElement; if (n && n.contains(b)) return true; } return false; };
  for (let i = 0; i < controls.length; i++) {
    for (let j = i + 1; j < controls.length; j++) {
      const a = controls[i].el, b = controls[j].el;
      if (a.contains(b) || b.contains(a) || !near(a, b) || insideField(a, b) || insideField(b, a)) continue;
      if (boxesOverlap(controls[i].box, controls[j].box)) {
        add("overlap", a, (a.getAttribute("aria-label") || a.textContent || "").trim() + " ↔ " + (b.getAttribute("aria-label") || b.textContent || "").trim().slice(0, 20), describe(b));
      }
    }
  }
  return found;
}`;

function parseViewport(value) {
  const match = /^(\d{3,4})x(\d{3,4})$/.exec(value.trim());
  if (!match) throw new Error(`Viewport must look like 1440x900: ${value}`);
  return { width: Number(match[1]), height: Number(match[2]) };
}

export function parseArgs(argv) {
  const rest = [];
  let locales = DEFAULT_LOCALES;
  let viewports = null;
  let capture = true;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--locales") locales = argv[++i].split(",").map((v) => v.trim()).filter(Boolean);
    else if (argv[i] === "--viewports") viewports = argv[++i].split(",").map(parseViewport);
    else if (argv[i] === "--no-capture") capture = false;
    else rest.push(argv[i]);
  }
  const args = parseSnapshotArgs(rest);
  if (!rest.includes("--themes")) args.themes = ["dark"];
  if (!rest.includes("--out")) args.out = path.resolve(import.meta.dirname, "../../output/design-layout", args.label);
  return { ...args, locales, viewports: viewports ?? DEFAULT_VIEWPORTS, capture };
}

async function audit(args) {
  const chromePath = findChrome(args.chromePath);
  if (!chromePath) throw new Error("Chrome or Edge was not found. Set CHROME_PATH or pass --chrome.");
  fs.mkdirSync(args.out, { recursive: true });
  const states = args.states.length ? STATES.filter((state) => args.states.includes(state.name)) : STATES;
  const helpers = Object.fromEntries([overflows, boxesOverlap].map((fn) => [fn.name, fn.toString()]));
  const findings = [];
  const visited = [];
  for (const theme of args.themes) {
    for (const locale of args.locales) {
      // A fresh profile per language: the app reads its language at start.
      const browser = await openBrowser(chromePath);
      try {
        await browser.send("Page.enable");
        await browser.send("Page.addScriptToEvaluateOnNewDocument", {
          source: `try { const k = ${JSON.stringify(SETTINGS_KEY)}; const s = JSON.parse(localStorage.getItem(k) || "{}");
            s.theme = ${JSON.stringify(theme)}; s.locale = ${JSON.stringify(locale)}; localStorage.setItem(k, JSON.stringify(s)); } catch {}`,
        });
        await browser.send("Page.addScriptToEvaluateOnNewDocument", { source: BLOCK_WRITES });
        for (const viewport of args.viewports) {
          await browser.send("Emulation.setDeviceMetricsOverride", { ...viewport, deviceScaleFactor: 1, mobile: false });
          for (const state of states) {
            const problems = await visitState(browser, { ...args, locale }, state);
            const result = await browser.send("Runtime.evaluate", { expression: `(${AUDIT})(${JSON.stringify(helpers)})`, returnByValue: true });
            if (result.result?.exceptionDetails) problems.push(`audit error: ${result.result.exceptionDetails.exception?.description ?? result.result.exceptionDetails.text}`);
            const items = result.result?.result?.value ?? [];
            const size = `${viewport.width}x${viewport.height}`;
            for (const item of items) findings.push({ state: state.name, theme, locale, viewport: size, ...item });
            const file = `${state.name}--${locale}--${size}--${theme}.jpg`;
            if (args.capture) {
              const shot = await browser.send("Page.captureScreenshot", { format: "jpeg", quality: 70 });
              fs.writeFileSync(path.join(args.out, file), Buffer.from(shot.result.data, "base64"));
            }
            const counts = items.reduce((acc, item) => ({ ...acc, [item.kind]: (acc[item.kind] ?? 0) + 1 }), {});
            visited.push({ state: state.name, theme, locale, viewport: size, counts, problems, file });
            console.log(`${items.length ? "✗" : "✓"} ${state.name} ${locale} ${size}: ${Object.entries(counts).map(([k, n]) => `${k} ${n}`).join(", ") || "fits"}${problems.length ? `  (${problems.join("; ")})` : ""}`);
          }
        }
      } finally {
        await browser.close();
      }
    }
  }
  const groups = groupFindings(findings);
  const hover = findings.filter(hasFullText).length;
  const report = { label: args.label, url: args.url, auditedAt: new Date().toISOString(), visited, total: findings.length, hover, groups };
  fs.writeFileSync(path.join(args.out, "report.json"), `${JSON.stringify(report, null, 2)}\n`);
  console.log(`\n${findings.length} findings (${hover} with the full text on hover) in ${groups.length} groups: ${path.join(args.out, "report.json")}`);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  audit(parseArgs(process.argv.slice(2))).catch((error) => {
    console.error(error instanceof Error ? error.stack : error);
    process.exitCode = 1;
  });
}
