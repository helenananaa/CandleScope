import assert from "node:assert/strict";
import test from "node:test";
import { LOCALE_OPTIONS, loadLocaleCatalog, t } from "../../i18n/index.js";
import { validateAccountStatus } from "./accountApi.js";
import { accountErrorHelp, hostCredentialStore } from "./accountErrors.js";

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

test("key-store help names the store that keeps the key (Keychain on macOS, Credential Manager on Windows)", async () => {
  for (const code of ["KEYCHAIN_READ_FAILED", "KEYCHAIN_RECORD_INVALID", "KEYCHAIN_STORE_FAILED", "CREDENTIAL_STORE_UNAVAILABLE"]) {
    assert.equal(accountErrorHelp(code, null), "account.keychainHelp");
    assert.equal(accountErrorHelp(code, "macos-keychain"), "account.keychainHelp");
    assert.equal(accountErrorHelp(code, "windows-credential-manager"), "account.credentialManagerHelp");
  }
  assert.equal(accountErrorHelp("ACCOUNT_SYNC_FAILED", "windows-credential-manager"), "account.errorHelp");
  // Without a store the help follows the computer the panel runs on.
  assert.equal(hostCredentialStore("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Electron/38"), "windows-credential-manager");
  assert.equal(hostCredentialStore("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Electron/38"), "macos-keychain");
  assert.equal(hostCredentialStore(""), "macos-keychain");
  await Promise.all(LOCALE_OPTIONS.map((option) => loadLocaleCatalog(option.id)));
  for (const { id } of LOCALE_OPTIONS) {
    for (const key of ["account.credentialsHelpWindows", "account.credentialManagerHelp", "account.desktopRequired"] as const) {
      assert.match(t(key, {}, id), /Windows/, `${id} ${key}`);
    }
    for (const key of ["account.credentialsHelpWindows", "account.credentialManagerHelp", "account.authTimestampHelp"] as const) {
      assert.doesNotMatch(t(key, {}, id), /\bMac\b|Keychain/, `${id} ${key}`);
    }
  }
});

test("the status names a known key store or none", () => {
  const status = { schemaVersion: 1, readOnly: true, venue: "okx", available: true, account: null, snapshots: {}, counts: {},
    scans: [], coverage: [], gaps: [], stream: { state: "stopped", lastReceivedMs: null, error: null }, reconciliation: "not_verified" };
  for (const credentialStore of [undefined, null, "macos-keychain", "windows-credential-manager"]) {
    assert.equal(validateAccountStatus({ ...status, credentialStore }).credentialStore, credentialStore);
  }
  for (const credentialStore of ["linux-secret-service", 1, {}]) {
    assert.throws(() => validateAccountStatus({ ...status, credentialStore }));
  }
});
