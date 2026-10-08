import assert from "node:assert/strict";
import test from "node:test";

import {
  COLLAPSED_LISTS_KEY,
  WATCHLISTS_KEY,
  loadCollapsedLists,
  loadWatchlists,
  STARTER_WATCHLIST_SYMBOLS,
  loadSidebarWidth,
  SIDEBAR_WIDTH_KEY,
} from "../watchlistStore.js";
import { mustBeDefined } from "../../../test/testHelpers.js";

function withStorage(values: Record<string, string | undefined>, run: () => void): void {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => values[key] ?? null,
      setItem() {},
    },
  });
  try {
    run();
  } finally {
    if (previous) Object.defineProperty(globalThis, "localStorage", previous);
    else Reflect.deleteProperty(globalThis, "localStorage");
  }
}

test("wide sidebar preference survives storage without the old 520px cap", () => {
  withStorage({ [SIDEBAR_WIDTH_KEY]: "1275" }, () => {
    assert.equal(loadSidebarWidth(), 1275);
  });
});

test("watchlist storage rejects damaged and malformed groups", () => {
  withStorage({ [WATCHLISTS_KEY]: "{damaged" }, () => {
    assert.deepEqual(loadWatchlists(), [
      { id: "default", name: "Watchlist", symbols: [], color: "#3b82f6" },
    ]);
  });

  withStorage({ [WATCHLISTS_KEY]: JSON.stringify([null, {}, { id: 2, name: [] }]) }, () => {
    assert.equal(mustBeDefined(loadWatchlists()[0]).id, "default");
  });
});

test("first launch seeds a starter watchlist but an emptied list stays empty", () => {
  withStorage({}, () => {
    const [list] = loadWatchlists();
    assert.equal(mustBeDefined(list).id, "default");
    assert.deepEqual(mustBeDefined(list).symbols, [...STARTER_WATCHLIST_SYMBOLS]);
    assert.ok(STARTER_WATCHLIST_SYMBOLS.length > 0);
  });

  withStorage({
    [WATCHLISTS_KEY]: JSON.stringify([{ id: "default", name: "Watchlist", color: "#3b82f6", symbols: [] }]),
  }, () => {
    assert.deepEqual(mustBeDefined(loadWatchlists()[0]).symbols, []);
  });
});

test("watchlist storage keeps valid groups and filters invalid collapsed ids", () => {
  withStorage({
    [WATCHLISTS_KEY]: JSON.stringify([
      { id: "main", name: "Main", color: "#fff", symbols: ["spot:btcusdt", null] },
    ]),
    [COLLAPSED_LISTS_KEY]: JSON.stringify(["main", 3, null]),
  }, () => {
    assert.deepEqual(loadWatchlists(), [
      { id: "main", name: "Main", color: "#fff", symbols: ["spot:BTCUSDT"] },
    ]);
    assert.deepEqual(loadCollapsedLists(), ["main"]);
  });
});
