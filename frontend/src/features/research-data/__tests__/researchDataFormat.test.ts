import { LOCALES as lazyTestLocales, loadLocaleCatalog } from "../../../i18n/registry.js";

test.before(async () => { await Promise.all(lazyTestLocales.map(loadLocaleCatalog)); });

import assert from "node:assert/strict";
import test from "node:test";
import { setLocale } from "../../../i18n/index.js";
import { formatQualityStatus } from "../researchDataFormat.js";

test("dataset quality statuses read in the user's language", () => {
  setLocale("zh-CN");
  assert.equal(formatQualityStatus("accepted"), "已通过");
  assert.equal(formatQualityStatus("accepted_with_gaps"), "已通过（有缺口）");
  // A status this build does not know yet is shown as sent rather than hidden.
  assert.equal(formatQualityStatus("quarantined"), "quarantined");
  setLocale("en");
  assert.equal(formatQualityStatus("accepted_with_gaps"), "Accepted with gaps");
});
