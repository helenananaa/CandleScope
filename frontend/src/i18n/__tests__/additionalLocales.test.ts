import assert from "node:assert/strict";
import test from "node:test";
import { en } from "../catalogs/en.js";
import {
  LOCALE_OPTIONS, getDateTimeLocale, getLocale, getNumberLocale,
  normalizeLocale, setLocale, subscribeLocale, t, tPlural,
} from "../index.js";
import { localeDefinition, type LocaleId } from "../registry.js";

const additions = [
  ["de", "de-DE", "Deutsch"],
  ["it", "it-IT", "Italiano"],
  ["id", "id-ID", "Bahasa Indonesia"],
  ["tr", "tr-TR", "Türkçe"],
  ["vi", "vi-VN", "Tiếng Việt"],
  ["pl", "pl-PL", "Polski"],
] as const;

for (const [language, region, label] of additions) {
  test(`${language} resolves regional tags, switches live, and exposes localized host surfaces`, () => {
    const previous = getLocale();
    setLocale("en");
    let changes = 0;
    const unsubscribe = subscribeLocale(() => { changes++; });
    try {
      assert.equal(normalizeLocale(`${region.toUpperCase()}-u-nu-latn`), language);
      assert.ok(LOCALE_OPTIONS.some(option => option.id === language && option.nativeLabel === label));
      assert.equal(setLocale(region), language);
      assert.equal(changes, 1);
      assert.equal(setLocale(language), language);
      assert.equal(changes, 1, "the same language must not trigger another update");
      assert.equal(new Intl.Locale(getNumberLocale()).language, language);
      assert.equal(new Intl.Locale(getDateTimeLocale()).language, language);
      for (const key of [
        "settings.language.title", "settings.language.description", "shell.settings",
        "workbench.manualHistory.title", "research.drawer.title", "strategy.firstOpenLead",
      ] as const) {
        assert.notEqual(t(key), key, `${language}: missing ${key}`);
        assert.notEqual(t(key), en[key], `${language}: English fallback for ${key}`);
        assert.doesNotMatch(t(key), /\p{Script=Han}/u, `${language}: Chinese text in ${key}`);
      }
      assert.ok(t("status.connectedTo", { exchange: "EXCHANGE_TEST" }).includes("EXCHANGE_TEST"));
    } finally {
      unsubscribe();
      setLocale(previous);
    }
  });

  test(`${language} supplies and selects every required plural category across all host plural families`, () => {
    const previous = getLocale();
    const rules = new Intl.PluralRules(language);
    const catalog = localeDefinition(language as LocaleId).messages as Readonly<Record<string, string>>;
    const bases = Object.keys(en).filter(key => key.endsWith(".one")).map(key => key.slice(0, -4));
    const counts = [0, 1, 2, 3, 5, 12, 21, 22, 25, 101, 1.5, 1_000_000];
    try {
      setLocale(language);
      for (const base of bases) {
        for (const category of rules.resolvedOptions().pluralCategories) {
          assert.equal(typeof catalog[category === "other" ? base : `${base}.${category}`], "string",
            `${language}: missing ${base}.${category}`);
        }
        for (const count of counts) {
          const category = rules.select(count);
          const key = Object.hasOwn(catalog, `${base}.${category}`) ? `${base}.${category}` : base;
          const variables = Object.fromEntries([...catalog[key]!.matchAll(/\{([A-Za-z0-9_]+)\}/g)]
            .map(match => [match[1]!, match[1] === "count" ? count : "VALUE"]));
          const expected = catalog[key]!.replace(/\{([A-Za-z0-9_]+)\}/g, (_, name: string) => String(variables[name]));
          assert.equal(tPlural(base as Parameters<typeof tPlural>[0], count, variables), expected);
        }
      }
    } finally {
      setLocale(previous);
    }
  });
}
