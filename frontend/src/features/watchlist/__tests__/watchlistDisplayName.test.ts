import assert from "node:assert/strict";
import test from "node:test";
import { watchlistDisplayName } from "../watchlistDisplayName.js";
import { setLocale } from "../../../i18n/index.js";

test("default list display follows the interface language without renaming custom lists", () => {
  setLocale("zh-CN");
  assert.equal(watchlistDisplayName({ id: "default", name: "Watchlist" }), "自选");
  assert.equal(watchlistDisplayName({ id: "custom", name: "Watchlist" }), "Watchlist");
  assert.equal(watchlistDisplayName({ id: "default", name: "我的交易计划" }), "我的交易计划");
  setLocale("en");
  assert.equal(watchlistDisplayName({ id: "default", name: "Watchlist" }), "Watchlist");
  setLocale("zh-CN");
});
