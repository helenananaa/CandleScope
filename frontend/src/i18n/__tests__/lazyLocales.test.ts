import assert from "node:assert/strict";
import test from "node:test";
import { getLocale, initializeLocale, setLocale, setLocaleAsync, subscribeLocale } from "../locale.js";
import { isLocaleCatalogLoaded, loadLocaleCatalog, LOCALE_OPTIONS, LOCALE_REGISTRY } from "../registry.js";
import { t } from "../t.js";
import type { MessageCatalog } from "../messageCatalog.js";

test("language metadata is available without loading optional catalogs", () => {
  assert.ok(LOCALE_OPTIONS.some((locale) => locale.id === "ar"));
  assert.equal(isLocaleCatalogLoaded("zh-CN"), true);
  assert.equal(isLocaleCatalogLoaded("en"), true);
  assert.equal(isLocaleCatalogLoaded("fr"), false);
  assert.equal(isLocaleCatalogLoaded("ar"), false);
});

test("concurrent catalog requests share one load and preserve the selected catalog", async () => {
  const first = loadLocaleCatalog("fr");
  assert.equal(loadLocaleCatalog("fr"), first);
  await first;
  setLocale("fr");
  assert.equal(t("shell.replay"), "Relecture");
  assert.equal(isLocaleCatalogLoaded("ar"), false);
  setLocale("en");
});

test("a late catalog load cannot overwrite a newer language selection", async () => {
  setLocale("en");
  const definition = LOCALE_REGISTRY.es as { loadMessages: () => Promise<MessageCatalog> };
  const original = definition.loadMessages;
  let finish!: () => void;
  const gate = new Promise<void>((resolve) => { finish = resolve; });
  definition.loadMessages = async () => { await gate; return original(); };
  const observed: string[] = [];
  const unsubscribe = subscribeLocale(() => observed.push(getLocale()));
  try {
    const pending = setLocaleAsync("es");
    assert.equal(getLocale(), "en");
    setLocale("zh-CN");
    finish();
    assert.equal(await pending, "zh-CN");
    assert.deepEqual(observed, ["zh-CN"]);
  } finally {
    definition.loadMessages = original;
    unsubscribe();
  }
});

test("catalog failure retains the previous language and permits a fresh retry", async () => {
  setLocale("zh-CN");
  const definition = LOCALE_REGISTRY.de as { loadMessages: () => Promise<MessageCatalog> };
  const original = definition.loadMessages;
  definition.loadMessages = () => Promise.reject(new Error("asset unavailable"));
  try {
    await assert.rejects(setLocaleAsync("de"), /asset unavailable/);
    assert.equal(getLocale(), "zh-CN");
    assert.equal(isLocaleCatalogLoaded("de"), false);
  } finally {
    definition.loadMessages = original;
  }
  assert.equal(await setLocaleAsync("de"), "de");
  assert.equal(t("shell.replay"), "Wiedergabe");
  setLocale("zh-CN");
});

test("hydrating an already active language preserves a pending user selection", async () => {
  setLocale("en");
  const definition = LOCALE_REGISTRY.it as { loadMessages: () => Promise<MessageCatalog> };
  const original = definition.loadMessages;
  let finish!: () => void;
  const gate = new Promise<void>((resolve) => { finish = resolve; });
  definition.loadMessages = async () => { await gate; return original(); };
  try {
    const pending = setLocaleAsync("it");
    assert.equal(await initializeLocale("en"), "en");
    finish();
    assert.equal(await pending, "it");
    assert.equal(getLocale(), "it");
  } finally {
    finish();
    definition.loadMessages = original;
    setLocale("zh-CN");
  }
});

test("an explicit saved-language revert cancels an in-flight language load", async () => {
  setLocale("en");
  const definition = LOCALE_REGISTRY.tr as { loadMessages: () => Promise<MessageCatalog> };
  const original = definition.loadMessages;
  let finish!: () => void;
  const gate = new Promise<void>((resolve) => { finish = resolve; });
  definition.loadMessages = async () => { await gate; return original(); };
  try {
    const pending = setLocaleAsync("tr");
    assert.equal(await setLocaleAsync("en"), "en");
    finish();
    assert.equal(await pending, "en");
    assert.equal(getLocale(), "en");
  } finally {
    finish();
    definition.loadMessages = original;
    setLocale("zh-CN");
  }
});
