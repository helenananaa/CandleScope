import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_FAVORITE_INTERVALS,
  sanitizeFavoriteIntervals,
  toggleFavoriteInterval,
} from "../intervalFavoritesStore.js";
import { withLocalStorage } from "./localStorageHarness.js";

test("favorite intervals are canonicalized, deduplicated by meaning and sorted by duration", () => {
  assert.deepEqual(
    sanitizeFavoriteIntervals(["4h", "60m", "1h", "bogus", 7, "1m"]),
    ["1m", "1h", "4h"],
  );
  assert.equal(sanitizeFavoriteIntervals({ value: "1m" }), null);
  assert.deepEqual(sanitizeFavoriteIntervals([]), []);
});

test("toggling favorites persists the shared list and removes semantic aliases", () => {
  withLocalStorage({}, (storage) => {
    toggleFavoriteInterval("3m");
    assert.deepEqual(
      JSON.parse(storage.getItem("candlescope-interval-favorites-v1") ?? "null"),
      sanitizeFavoriteIntervals([...DEFAULT_FAVORITE_INTERVALS, "3m"]),
    );

    toggleFavoriteInterval("60m");
    const stored: unknown = JSON.parse(storage.getItem("candlescope-interval-favorites-v1") ?? "null");
    assert.ok(Array.isArray(stored));
    assert.ok(!stored.includes("1h"));
    assert.ok(stored.includes("3m"));
  });
});
