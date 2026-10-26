import assert from "node:assert/strict";
import test from "node:test";
import { loadLocaleCatalog, t } from "../../i18n/index.js";
import { accountErrorHelp } from "./accountErrors.js";

test.before(async () => { await Promise.all((["ko", "pt-BR"] as const).map(loadLocaleCatalog)); });

test("provider authentication failures have specific translated help with the original code", () => {
  const expected = {
    "50100": "account.authFrozenHelp", "50101": "account.authEnvironmentHelp",
    "50102": "account.authTimestampHelp", "50103": "account.authHeadersHelp",
    "50104": "account.authHeadersHelp", "50105": "account.authPassphraseHelp",
    "50106": "account.authHeadersHelp", "50107": "account.authHeadersHelp",
    "50110": "account.authIpHelp", "50111": "account.authKeyHelp",
    "50112": "account.authTimestampHelp", "50113": "account.authSignatureHelp",
    "50114": "account.authAuthorizationHelp", "50119": "account.authRegionHelp",
  };
  for (const [code, message] of Object.entries(expected)) {
    const key = accountErrorHelp(`OKX_AUTH_${code}`);
    assert.equal(key, message);
    for (const locale of ["en", "zh-CN", "ko", "pt-BR"] as const) {
      assert.notEqual(t(key, {}, locale), key);
      assert.ok(t(key, {}, locale).length > 15);
    }
  }
});

test("unknown authentication failures stay generic and existing account guidance is preserved", () => {
  for (const code of ["ACCOUNT_AUTHENTICATION_FAILED", "OKX_AUTH_59999", "toString", "__proto__"]) {
    assert.equal(accountErrorHelp(code), "account.errorHelp");
  }
  assert.equal(accountErrorHelp("READONLY_KEY_REQUIRED"), "account.readonlyKeyHelp");
  assert.equal(accountErrorHelp("HEDGE_ACCOUNT_REQUIRED"), "account.hedgeHelp");
  assert.equal(accountErrorHelp("KEYCHAIN_STORE_FAILED"), "account.keychainHelp");
  assert.equal(accountErrorHelp("ACCOUNT_IDENTITY_CHANGED"), "account.identityHelp");
});
