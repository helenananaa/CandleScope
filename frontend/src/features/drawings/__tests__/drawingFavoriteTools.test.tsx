import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import DrawingToolbar from "../../../components/DrawingToolbar.js";
import ToolFlyout from "../../../components/drawing/ToolFlyout.js";
import { LINE_VARIANTS } from "../../../components/drawing/drawingToolbarDefinitions.js";
import { getLocale, setLocale } from "../../../i18n/index.js";
import {
  FAVORITE_TOOLS_KEY,
  MAX_FAVORITE_TOOLS,
  favoriteShortcutIndex,
  parseFavoriteTools,
  readFavoriteTools,
  toggleFavoriteTool,
} from "../drawingFavoriteTools.js";

class MemoryStorage {
  readonly values = new Map<string, string>();
  getItem(key: string) { return this.values.get(key) ?? null; }
  setItem(key: string, value: string) { this.values.set(key, value); }
  removeItem(key: string) { this.values.delete(key); }
}

const KNOWN = new Set(["line-segment", "line-ray", "shape-rectangle", "pen", "position-long", "cursor-dot",
  "line-infinite", "line-arrow", "highlighter", "shape-ellipse"]);
const known = (id: string) => KNOWN.has(id);

function inEnglish<T>(run: () => T): T {
  const previous = getLocale();
  try {
    setLocale("en");
    return run();
  } finally {
    setLocale(previous);
  }
}

test("favorites keep known tools once each, in order, and at most nine", () => {
  assert.deepEqual(parseFavoriteTools(JSON.stringify({ version: 1, tools: ["line-ray", "nope", "line-ray", 3, "pen"] }), known), ["line-ray", "pen"]);
  for (const raw of [null, "", "{", "[]", JSON.stringify({ version: 2, tools: ["pen"] }), JSON.stringify({ version: 1, tools: "pen" })]) {
    assert.deepEqual(parseFavoriteTools(raw, known), [], String(raw));
  }
  const storage = new MemoryStorage();
  assert.deepEqual(toggleFavoriteTool("line-ray", known, storage), ["line-ray"]);
  assert.deepEqual(toggleFavoriteTool("pen", known, storage), ["line-ray", "pen"]);
  assert.deepEqual(readFavoriteTools(known, storage), ["line-ray", "pen"]);
  assert.deepEqual(toggleFavoriteTool("line-ray", known, storage), ["pen"]);
  assert.equal(toggleFavoriteTool("not-a-tool" as never, known, storage), null);
  for (const id of [...KNOWN].filter((tool) => tool !== "pen")) toggleFavoriteTool(id as never, known, storage);
  assert.equal(readFavoriteTools(known, storage).length, MAX_FAVORITE_TOOLS);
  const failing = { getItem: () => null, setItem: () => { throw new Error("quota"); } };
  assert.equal(toggleFavoriteTool("pen", known, failing), null);
});

test("Alt+1…9 pick by physical key, so Option on a Mac still works", () => {
  const key = (code: string, extra: Partial<KeyboardEvent> = {}) => favoriteShortcutIndex({ altKey: true, ctrlKey: false, metaKey: false, shiftKey: false, code, ...extra });
  assert.equal(key("Digit1"), 0);
  assert.equal(key("Digit9"), 8);
  assert.equal(key("Numpad3"), 2);
  assert.equal(key("Digit0"), null);
  assert.equal(key("KeyA"), null);
  assert.equal(key("Digit1", { altKey: false }), null);
  assert.equal(key("Digit1", { ctrlKey: true }), null);
  assert.equal(key("Digit1", { metaKey: true }), null);
  assert.equal(key("Digit1", { shiftKey: true }), null);
});

test("tool menus show a star per row that reports whether the tool is a favorite", () => {
  const html = inEnglish(() => renderToStaticMarkup(
    <ToolFlyout
      variants={LINE_VARIANTS}
      currentId="line-segment"
      onSelect={() => {}}
      onClose={() => {}}
      anchorRef={{ current: null }}
      favorites={{ isFavorite: (id) => id === "line-ray", toggle: () => true, full: false }}
    />,
  ));
  const star = (id: string) => html.match(new RegExp(`<button[^>]*data-favorite-tool="${id}"[^>]*>`))?.[0] ?? "";
  assert.match(star("line-ray"), /aria-pressed="true"/);
  assert.match(star("line-ray"), /Remove Ray from favorites/);
  assert.match(star("line-segment"), /aria-pressed="false"/);
  assert.match(star("line-segment"), /Add Segment to favorites/);
  assert.match(star("line-segment"), /tabindex="-1"/);
  const withoutFavorites = renderToStaticMarkup(
    <ToolFlyout variants={LINE_VARIANTS} currentId="line-segment" onSelect={() => {}} onClose={() => {}} anchorRef={{ current: null }} />,
  );
  assert.doesNotMatch(withoutFavorites, /data-favorite-tool/);

  const full = inEnglish(() => renderToStaticMarkup(
    <ToolFlyout variants={LINE_VARIANTS} currentId="line-segment" onSelect={() => {}} onClose={() => {}} anchorRef={{ current: null }}
      favorites={{ isFavorite: () => false, toggle: () => false, full: true }} />,
  ));
  assert.match(full.match(/<button[^>]*data-favorite-tool="line-ray"[^>]*>/)?.[0] ?? "", /disabled=""[^>]*|Favorites are full/);
});

test("the toolbar shows starred tools in their own strip with their Alt shortcut", () => {
  const previous = (globalThis as { localStorage?: unknown }).localStorage;
  const storage = new MemoryStorage();
  storage.setItem(FAVORITE_TOOLS_KEY, JSON.stringify({ version: 1, tools: ["line-ray", "shape-rectangle"] }));
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: storage });
  try {
    const html = inEnglish(() => renderToStaticMarkup(
      <DrawingToolbar activeTool="line-ray" penColor="#f59e0b" penSize={2} onClearAll={() => {}} onToggleDrawingsHidden={() => {}} onPositionSizeChange={() => {}} />,
    ));
    const strip = html.match(/<div class="drawing-toolbar-favorites"[\s\S]*?<\/div><\/div>/)?.[0] ?? "";
    assert.match(html, /role="group" aria-label="Favorite tools"/);
    assert.match(strip, /data-drawing-tool="line-ray"[^>]*/);
    assert.match(html, /title="Ray · Shortcut Alt\+1"/);
    assert.match(html, /title="Rectangle · Shortcut Alt\+2"/);
    assert.match(html.match(/<button[^>]*title="Ray · Shortcut Alt\+1"[^>]*>/)?.[0] ?? "", /aria-pressed="true"/);

    storage.setItem(FAVORITE_TOOLS_KEY, JSON.stringify({ version: 1, tools: [] }));
    const empty = renderToStaticMarkup(
      <DrawingToolbar activeTool="line-ray" penColor="#f59e0b" penSize={2} onClearAll={() => {}} onToggleDrawingsHidden={() => {}} onPositionSizeChange={() => {}} />,
    );
    assert.doesNotMatch(empty, /drawing-toolbar-favorites/);
  } finally {
    if (previous === undefined) delete (globalThis as { localStorage?: unknown }).localStorage;
    else Object.defineProperty(globalThis, "localStorage", { configurable: true, value: previous });
  }
});
