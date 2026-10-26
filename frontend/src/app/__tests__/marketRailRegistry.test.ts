import assert from "node:assert/strict";
import test from "node:test";

import {
  listContributedMarketRailViews,
  mergeMarketRailViews,
  registerMarketRailView,
  subscribeMarketRailRegistry,
} from "../marketRailRegistry.js";

test("market rail registry snapshots stay stable until the registry changes", () => {
  const initial = listContributedMarketRailViews();
  assert.strictEqual(listContributedMarketRailViews(), initial);

  let notifications = 0;
  const unsubscribe = subscribeMarketRailRegistry(() => {
    notifications += 1;
  });
  const unregister = registerMarketRailView({
    id: "test-contribution",
    title: "Test contribution",
    icon: null,
    order: 100,
    sizing: "fixed",
  });

  try {
    const registered = listContributedMarketRailViews();
    assert.notStrictEqual(registered, initial);
    assert.strictEqual(listContributedMarketRailViews(), registered);
    assert.deepEqual(registered.map((view) => view.id), ["test-contribution"]);
    assert.equal(notifications, 1);
  } finally {
    unregister();
    unsubscribe();
  }

  assert.strictEqual(listContributedMarketRailViews(), initial);
  assert.equal(notifications, 2);
});

test("account credentials view cannot be replaced by a plugin contribution", () => {
  const owned = { id: "readonly-accounts", title: "Host account", icon: null, order: 50, sizing: "fixed" as const };
  const replacement = { ...owned, title: "Plugin replacement" };
  assert.throws(() => registerMarketRailView(replacement), /owned by the desktop host/);
  assert.deepEqual(mergeMarketRailViews([owned], [replacement]), [owned]);
});

test("plugin contributions cannot replace host-owned rail views", () => {
  const builtIn = [
    { id: "watchlist", title: "Watchlist", icon: null, order: 10, sizing: "flex" as const },
    { id: "accounts", title: "Accounts", icon: null, order: 50, sizing: "flex" as const, hostOwned: true },
  ];
  const merged = mergeMarketRailViews(builtIn, [
    { id: "watchlist", title: "Plugin watchlist", icon: null, order: 10, sizing: "flex" },
    { id: "accounts", title: "Plugin accounts", icon: null, order: 50, sizing: "flex" },
  ]);
  assert.deepEqual(merged.map((view) => view.title), ["Plugin watchlist", "Accounts"]);
});
