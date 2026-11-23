#!/usr/bin/env node
// Design keyboard audit: opens the named design states (design-snapshots.mjs) and uses them with
// the keyboard only, as rendered.
//
//   Tab walk     presses Tab through the page (up to --max-stops) and checks every stop: it is on
//                screen, nothing covers it, and focusing it changes how it looks (an outline, ring,
//                border or background with 3:1 against what is around it).
//   Popups       every stop that opens a popup (aria-haspopup) must open on Enter, move focus into
//                the popup (or point to it with aria-activedescendant), move with the arrow keys
//                when it is a menu or list, close on Escape and give focus back to the trigger.
//   Pointer-only controls that react to the pointer (cursor: pointer, or a button-like role) but
//                cannot be reached with Tab.
//   Motion       with prefers-reduced-motion: reduce, transitions and animations still running.
//
// Requires the Vite dev server and the backend, like the snapshots. Writes are refused.
//
//   node scripts/design-keyboard.mjs                          # all states, dark theme
//   node scripts/design-keyboard.mjs --states market,alerts --label before
//   (report: output/design-keyboard/<label>/report.json)
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { composite, contrastRatio, parseColor, relativeLuminance } from "./design-contrast.mjs";
import { BLOCK_WRITES, SETTINGS_KEY, STATES, findChrome, openBrowser, parseArgs as parseSnapshotArgs, visitState } from "./design-snapshots.mjs";

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Spinners keep turning with reduced motion (slower): the turning is what says "loading". */
export const ALLOWED_REDUCED_MOTION = /spin/i;

/** Focus indicator verdict from the styles a stop had focused and blurred. */
export function focusIndicator(changes, contrastOf) {
  if (!changes.length) return { verdict: "none", ratio: 0, by: "" };
  let best = { verdict: "weak", ratio: 0, by: changes[0].prop };
  for (const change of changes) {
    const ratio = contrastOf(change);
    if (ratio > best.ratio) best = { verdict: ratio >= 3 ? "ok" : "weak", ratio: Math.round(ratio * 100) / 100, by: `${change.target} ${change.prop}` };
  }
  return best;
}

/** How a Tab walk ended: back at the first stop, out of the page, stuck on one element, or the limit. */
export function walkEnd(stops, maxStops) {
  const last = stops.at(-1);
  if (!last) return "empty";
  if (last.body) return "left the page";
  if (stops.length >= 2 && last.index === 0) return "cycled";
  if (stops.length >= 3 && stops.slice(-3).every((stop) => stop.index === last.index)) return "stuck";
  if (stops.length >= maxStops) return "limit";
  return "";
}

// Runs in the page. Helpers come in as source so the page and the tests share them.
export const PAGE = `(helpers) => {
  const { parseColor, composite, contrastRatio } = Object.fromEntries(
    Object.entries(helpers).map(([name, source]) => [name, (0, eval)("(" + source + ")")]));
  const kb = window.__kb = { stops: [], focused: [], parseColor, composite, contrastRatio };
  const deepActive = () => { let a = document.activeElement; while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement; return a; };
  const describe = (el) => {
    const parts = [];
    for (let node = el; node && node !== document.body && parts.length < 3; node = node.parentElement) {
      const cls = [...node.classList].filter((c) => !/^_|^\\d/.test(c)).slice(0, 2).join(".");
      parts.unshift(node.tagName.toLowerCase() + (cls ? "." + cls : ""));
    }
    return parts.join(" > ");
  };
  const name = (el) => {
    const label = el.getAttribute("aria-label") || (el.getAttribute("aria-labelledby") || "").split(" ").map((id) => document.getElementById(id)?.textContent || "").join(" ")
      || el.getAttribute("title") || el.textContent || el.getAttribute("placeholder") || el.value || "";
    return String(label).replace(/\\s+/g, " ").trim().slice(0, 40);
  };
  const PROPS = ["outlineStyle", "outlineWidth", "outlineColor", "boxShadow", "borderTopColor", "borderBottomColor", "borderLeftColor", "backgroundColor", "color", "textDecorationLine"];
  const targets = (el) => ({ self: el, before: [el, "::before"], after: [el, "::after"], parent: el.parentElement, grand: el.parentElement?.parentElement, next: el.nextElementSibling, child: el.firstElementChild });
  const snap = (el) => {
    const out = {};
    for (const [key, target] of Object.entries(targets(el))) {
      if (!target) continue;
      const s = Array.isArray(target) ? getComputedStyle(target[0], target[1]) : getComputedStyle(target);
      if (Array.isArray(target) && (s.content === "none" || s.content === "normal")) continue;
      out[key] = Object.fromEntries(PROPS.map((p) => [p, s[p]]));
    }
    return out;
  };
  const background = (el) => {
    const layers = [];
    for (let node = el; node; node = node.parentElement) {
      const s = getComputedStyle(node);
      const color = parseColor(s.backgroundColor);
      if (color && color[3] > 0) layers.push(color);
      if (color && color[3] >= 1) break;
    }
    let base = [255, 255, 255, 1];
    for (const layer of layers.reverse()) base = composite(layer, base);
    return base;
  };
  kb.background = background;
  const visibleRect = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    if (r.width < 2 || r.height < 2 || s.visibility === "hidden" || Number(s.opacity) === 0) return false;
    return r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth;
  };
  // Focus styles often fade in; finish running transitions so the walk reads the end state.
  const settle = () => { for (const a of document.getAnimations()) if (typeof CSSTransition !== "undefined" && a instanceof CSSTransition) a.finish(); };
  kb.probe = () => {
    settle();
    const el = deepActive();
    if (!el || el === document.body || el === document.documentElement) return { body: true };
    let index = kb.stops.indexOf(el);
    const repeat = index !== -1;
    if (!repeat) { kb.stops.push(el); index = kb.stops.length - 1; kb.focused[index] = snap(el); }
    const r = el.getBoundingClientRect();
    let obscured = false;
    // The code editor focuses a hidden text area under its own caret; the caret is the indicator.
    if (visibleRect(el) && !el.closest(".monaco-editor")) {
      const x = Math.min(Math.max(r.left + r.width / 2, 0), innerWidth - 1), y = Math.min(Math.max(r.top + r.height / 2, 0), innerHeight - 1);
      const hit = document.elementFromPoint(x, y);
      obscured = !!hit && !el.contains(hit) && !hit.contains(el) && !(el.labels && [...el.labels].some((l) => l.contains(hit)));
    }
    return { index, repeat, where: describe(el), name: name(el), role: el.getAttribute("role") || el.tagName.toLowerCase(),
      visible: visibleRect(el), obscured, popup: el.getAttribute("aria-haspopup") && el.getAttribute("aria-haspopup") !== "false" ? el.getAttribute("aria-haspopup") : null,
      inMonaco: !!el.closest(".monaco-editor") };
  };
  // After the walk: blur, then compare each stop's styles focused and not.
  kb.indicators = () => {
    deepActive()?.blur?.();
    settle();
    return kb.stops.map((el, index) => {
      if (!el.isConnected) return { index, verdict: "gone" };
      const before = kb.focused[index], after = snap(el);
      const changes = [];
      for (const [target, props] of Object.entries(before)) {
        for (const [prop, value] of Object.entries(props)) {
          const now = after[target]?.[prop];
          if (now !== undefined && now !== value) changes.push({ target, prop, focused: value, blurred: now });
        }
      }
      // A ring or outline only counts while it is drawn.
      const real = changes.filter((c) => !(c.prop.startsWith("outline") && before[c.target].outlineStyle === "none"));
      const around = background(el.parentElement || el);
      const ratios = real.map((c) => {
        const fg = parseColor(c.prop === "boxShadow" ? (c.focused.match(/(rgba?\\([^)]*\\)|color\\(srgb[^)]*\\))/) || [])[0] || "" : c.focused);
        if (!fg) return 0;
        if (c.prop === "backgroundColor") { const old = parseColor(c.blurred) || [0, 0, 0, 0]; const base = background(el.parentElement || el); return contrastRatio(composite(fg, base), composite(old, base)); }
        if (c.prop === "color") return 0;
        return contrastRatio(composite(fg, around), around);
      });
      return { index, changes: real.map((c, i) => ({ target: c.target, prop: c.prop, ratio: Math.round(ratios[i] * 100) / 100 })) };
    });
  };
  kb.focusStop = (index) => {
    const el = kb.stops[index];
    if (!el || !el.isConnected) return false;
    el.focus();
    for (const node of document.querySelectorAll(kb.POPUPS)) node.dataset.kbBefore = "1";
    return deepActive() === el;
  };
  kb.POPUPS = "[role=dialog], [role=alertdialog], [role=menu], [role=listbox], [role=tree], [role=grid], .ui-popover, dialog[open]";
  kb.openedPopup = (index) => {
    const el = kb.stops[index];
    const controls = el && el.getAttribute("aria-controls") ? document.getElementById(el.getAttribute("aria-controls")) : null;
    const fresh = [...document.querySelectorAll(kb.POPUPS)].filter((n) => !n.dataset.kbBefore && visibleRect(n));
    return (controls && visibleRect(controls) ? controls : null) || fresh[0] || null;
  };
  kb.afterOpen = (index) => {
    const el = kb.stops[index];
    const popup = kb.openedPopup(index);
    const active = deepActive();
    kb.popup = popup;
    const descendant = el?.getAttribute("aria-activedescendant");
    return { opened: !!popup, expanded: el?.getAttribute("aria-expanded"), role: popup ? (popup.getAttribute("role") || popup.tagName.toLowerCase()) : null,
      popupWhere: popup ? describe(popup) : null,
      focusInside: !!popup && !!active && popup.contains(active), pointsInside: !!descendant && !!popup?.querySelector("#" + CSS.escape(descendant)),
      activeWhere: active ? describe(active) : null };
  };
  kb.activeKey = () => { const a = deepActive(); const el = kb.stops[kb.lastIndex]; return (a ? describe(a) + "|" + name(a) : "") + "|" + (el?.getAttribute("aria-activedescendant") || ""); };
  kb.afterClose = (index) => {
    const el = kb.stops[index];
    const popup = kb.popup;
    const open = !!popup && popup.isConnected && visibleRect(popup);
    const active = deepActive();
    for (const node of document.querySelectorAll("[data-kb-before]")) delete node.dataset.kbBefore;
    return { closed: !open, returned: !!el && !!active && (active === el || el.contains(active)), activeWhere: active ? describe(active) : null };
  };
  // Controls a pointer can use that Tab never reaches.
  kb.pointerOnly = () => {
    const FOCUSABLE = "a[href], button, input, select, textarea, summary, [tabindex], [contenteditable=true], label, iframe";
    const ROLES = "[role=button], [role=tab], [role=menuitem], [role=option], [role=checkbox], [role=switch], [role=link], [role=radio], [role=treeitem]";
    const found = [];
    for (const el of document.querySelectorAll("body *")) {
      if (el.closest("[inert], svg, canvas, .monaco-editor, [aria-hidden=true]") || !visibleRect(el)) continue;
      const s = getComputedStyle(el);
      const pointer = s.cursor === "pointer" && getComputedStyle(el.parentElement || el).cursor !== "pointer";
      const roleOnly = el.matches(ROLES) && !el.matches(FOCUSABLE);
      if (!pointer && !roleOnly) continue;
      // A control inside a focusable element (or a label) is reached through it; one that only
      // contains small controls (a clickable row with just a delete button) is not.
      if (el.closest(FOCUSABLE)) continue;
      // A control inside that holds most of it (a row's main button: most of its area or its
      // text) does what clicking it does.
      const box = el.getBoundingClientRect();
      const textLength = (el.textContent || "").trim().length;
      if ([...el.querySelectorAll(FOCUSABLE)].some((inner) => {
        const r = inner.getBoundingClientRect();
        return r.width * r.height >= 0.5 * box.width * box.height
          || (textLength > 0 && (inner.textContent || "").trim().length >= 0.8 * textLength);
      })) continue;
      found.push({ where: describe(el), name: name(el), why: roleOnly ? "role " + el.getAttribute("role") : "cursor: pointer" });
    }
    return found;
  };
  kb.motion = () => {
    const moving = [];
    const seconds = (list) => list.split(",").map((v) => parseFloat(v) * (v.trim().endsWith("ms") ? 0.001 : 1));
    for (const el of document.querySelectorAll("body *")) {
      if (!visibleRect(el)) continue;
      const s = getComputedStyle(el);
      if (s.transitionProperty !== "none" && seconds(s.transitionDuration).some((d) => d > 0.02)) moving.push({ where: describe(el), what: "transition " + s.transitionProperty + " " + s.transitionDuration });
    }
    for (const animation of document.getAnimations()) {
      const timing = animation.effect?.getTiming?.() ?? {};
      const target = animation.effect?.target;
      const label = animation.animationName || animation.transitionProperty || "animation";
      if (Number(timing.duration) > 20 && animation.playState === "running") moving.push({ where: target ? describe(target) : "?", what: "animation " + label + " " + timing.duration + "ms", name: label });
    }
    return moving;
  };
  return true;
}`;

const KEYS = {
  Tab: { key: "Tab", code: "Tab", keyCode: 9 },
  Enter: { key: "Enter", code: "Enter", keyCode: 13, text: "\r" },
  Escape: { key: "Escape", code: "Escape", keyCode: 27 },
  ArrowDown: { key: "ArrowDown", code: "ArrowDown", keyCode: 40 },
};

async function press(browser, name, { shift = false } = {}) {
  const def = KEYS[name];
  const base = { key: def.key, code: def.code, windowsVirtualKeyCode: def.keyCode, nativeVirtualKeyCode: def.keyCode, modifiers: shift ? 8 : 0 };
  await browser.send("Input.dispatchKeyEvent", { type: "keyDown", ...base, ...(def.text ? { text: def.text, unmodifiedText: def.text } : {}) });
  await browser.send("Input.dispatchKeyEvent", { type: "keyUp", ...base });
}

async function evaluate(browser, expression) {
  const result = await browser.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (result.result?.exceptionDetails) throw new Error(result.result.exceptionDetails.exception?.description ?? result.result.exceptionDetails.text);
  return result.result?.result?.value;
}

async function installPage(browser) {
  const helpers = Object.fromEntries([parseColor, composite].map((fn) => [fn.name, fn.toString()]));
  helpers.contrastRatio = `(a, b) => { const relativeLuminance = ${relativeLuminance.toString()}; return (${contrastRatio.toString()})(a, b); }`;
  await evaluate(browser, `(${PAGE})(${JSON.stringify(helpers)})`);
}

async function tabWalk(browser, maxStops) {
  const stops = [];
  // From wherever the state left focus: the top of the page, or inside the layer it opened.
  for (let i = 0; i < maxStops; i++) {
    await press(browser, "Tab");
    await wait(60);
    const stop = await evaluate(browser, "window.__kb.probe()");
    stops.push(stop);
    if (walkEnd(stops, maxStops)) break;
    if (stop.inMonaco) {
      // The code editor keeps Tab for indenting; Ctrl+M (Monaco's own) lets Tab move focus on.
      stops.at(-1).trap = "editor";
      break;
    }
  }
  return stops;
}

async function popupCheck(browser, index) {
  const ready = await evaluate(browser, `window.__kb.focusStop(${index})`);
  if (!ready) return { skipped: "could not focus" };
  await press(browser, "Enter");
  await wait(500);
  const opened = await evaluate(browser, `window.__kb.afterOpen(${index})`);
  const result = { ...opened, moves: null };
  if (opened.opened && /menu|listbox|tree|grid/.test(opened.role ?? "")) {
    await evaluate(browser, `(window.__kb.lastIndex = ${index}, true)`);
    const before = await evaluate(browser, "window.__kb.activeKey()");
    await press(browser, "ArrowDown");
    await wait(150);
    result.moves = (await evaluate(browser, "window.__kb.activeKey()")) !== before;
  }
  await press(browser, "Escape");
  await wait(400);
  let closed = await evaluate(browser, `window.__kb.afterClose(${index})`);
  if (opened.opened && !closed.closed) {
    await press(browser, "Escape");
    await wait(400);
    const again = await evaluate(browser, `window.__kb.afterClose(${index})`);
    closed = { ...closed, closedOnSecondEscape: again.closed };
  }
  return { ...result, ...closed };
}

export function popupProblems(check) {
  if (check.skipped) return [];
  if (!check.opened) return ["does not open on Enter"];
  const problems = [];
  if (!check.focusInside && !check.pointsInside) problems.push("focus stays outside the popup");
  if (check.moves === false) problems.push("arrow keys do not move");
  if (!check.closed) problems.push(check.closedOnSecondEscape ? "Escape closes only on the second press" : "Escape does not close");
  else if (!check.returned) problems.push("focus does not return to the trigger");
  return problems;
}

export function parseArgs(argv) {
  const rest = [];
  let maxStops = 160;
  let motion = true;
  let popups = true;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--max-stops") maxStops = Number(argv[++i]);
    else if (argv[i] === "--no-motion") motion = false;
    else if (argv[i] === "--no-popups") popups = false;
    else rest.push(argv[i]);
  }
  const args = parseSnapshotArgs(rest);
  if (!rest.includes("--themes")) args.themes = ["dark"];
  if (!rest.includes("--out")) args.out = path.resolve(import.meta.dirname, "../../output/design-keyboard", args.label);
  return { ...args, maxStops, motion, popups };
}

async function prepare(browser, args, theme, reducedMotion) {
  await browser.send("Page.enable");
  await browser.send("Emulation.setFocusEmulationEnabled", { enabled: true });
  await browser.send("Page.addScriptToEvaluateOnNewDocument", {
    source: `try { const k = ${JSON.stringify(SETTINGS_KEY)}; const s = JSON.parse(localStorage.getItem(k) || "{}");
      s.theme = ${JSON.stringify(theme)}; s.locale = ${JSON.stringify(args.locale)}; localStorage.setItem(k, JSON.stringify(s)); } catch {}`,
  });
  await browser.send("Page.addScriptToEvaluateOnNewDocument", { source: BLOCK_WRITES });
  if (reducedMotion) await browser.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
  await browser.send("Emulation.setDeviceMetricsOverride", { ...args.viewports[0], deviceScaleFactor: 1, mobile: false });
}

async function audit(args) {
  const chromePath = findChrome(args.chromePath);
  if (!chromePath) throw new Error("Chrome or Edge was not found. Set CHROME_PATH or pass --chrome.");
  fs.mkdirSync(args.out, { recursive: true });
  const states = args.states.length ? STATES.filter((state) => args.states.includes(state.name)) : STATES;
  const report = { label: args.label, url: args.url, locale: args.locale, auditedAt: new Date().toISOString(), states: [] };
  for (const theme of args.themes) {
    const browser = await openBrowser(chromePath);
    try {
      await prepare(browser, args, theme, false);
      for (const state of states) {
        const problems = await visitState(browser, args, state);
        await installPage(browser);
        const pointerOnly = await evaluate(browser, "window.__kb.pointerOnly()");
        const stops = await tabWalk(browser, args.maxStops);
        const end = walkEnd(stops, args.maxStops) || (stops.at(-1)?.trap ? "editor keeps Tab" : "");
        const indicators = await evaluate(browser, "window.__kb.indicators()");
        const unique = stops.filter((stop) => !stop.body && !stop.repeat);
        const stopRows = unique.map((stop) => {
          const found = indicators.find((item) => item.index === stop.index) ?? {};
          const verdict = found.verdict ?? focusIndicator(found.changes ?? [], (change) => change.ratio);
          return { ...stop, indicator: typeof verdict === "string" ? { verdict } : verdict };
        });
        const popupRows = [];
        if (args.popups) {
          for (const stop of stopRows.filter((row) => row.popup && row.visible)) {
            const check = await popupCheck(browser, stop.index);
            popupRows.push({ where: stop.where, name: stop.name, popup: stop.popup, ...check, problems: popupProblems(check) });
          }
        }
        const failures = {
          noIndicator: stopRows.filter((row) => row.indicator.verdict === "none" && row.visible),
          weakIndicator: stopRows.filter((row) => row.indicator.verdict === "weak" && row.visible),
          hidden: stopRows.filter((row) => !row.visible),
          obscured: stopRows.filter((row) => row.visible && row.obscured),
          popups: popupRows.filter((row) => row.problems.length),
          pointerOnly,
        };
        const counts = Object.fromEntries(Object.entries(failures).map(([key, list]) => [key, list.length]));
        report.states.push({ state: state.name, theme, end, stops: stopRows.length, problems, counts, failures, popupsChecked: popupRows.map((row) => `${row.name}: ${row.problems.join(", ") || "ok"}`), stopOrder: stopRows.map((row) => `${row.role} ${row.name}`.trim()) });
        const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
        console.log(`${total ? "✗" : "✓"} ${state.name} ${theme}: ${stopRows.length} stops (${end || "open"}), ${Object.entries(counts).filter(([, n]) => n).map(([k, n]) => `${k} ${n}`).join(", ") || "no problems"}${problems.length ? `  (${problems.join("; ")})` : ""}`);
      }
    } finally {
      await browser.close();
    }
  }
  if (args.motion) {
    const browser = await openBrowser(chromePath);
    try {
      await prepare(browser, args, args.themes[0], true);
      report.motion = [];
      for (const state of states) {
        await visitState(browser, args, state);
        await installPage(browser);
        const moving = (await evaluate(browser, "window.__kb.motion()")).filter((item) => !ALLOWED_REDUCED_MOTION.test(item.name ?? ""));
        report.motion.push({ state: state.name, moving });
        console.log(`${moving.length ? "✗" : "✓"} ${state.name} reduced motion: ${moving.length} still moving`);
      }
    } finally {
      await browser.close();
    }
  }
  fs.writeFileSync(path.join(args.out, "report.json"), `${JSON.stringify(report, null, 2)}\n`);
  console.log(`\nReport: ${path.join(args.out, "report.json")}`);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  audit(parseArgs(process.argv.slice(2))).catch((error) => {
    console.error(error instanceof Error ? error.stack : error);
    process.exitCode = 1;
  });
}
