import type { MessageKey } from "../../i18n/index.js";
import type { CredentialStore } from "./accountApi.js";

const AUTH_HELP: Readonly<Record<string, MessageKey>> = {
  OKX_AUTH_50100: "account.authFrozenHelp",
  OKX_AUTH_50101: "account.authEnvironmentHelp",
  OKX_AUTH_50102: "account.authTimestampHelp",
  OKX_AUTH_50103: "account.authHeadersHelp",
  OKX_AUTH_50104: "account.authHeadersHelp",
  OKX_AUTH_50105: "account.authPassphraseHelp",
  OKX_AUTH_50106: "account.authHeadersHelp",
  OKX_AUTH_50107: "account.authHeadersHelp",
  OKX_AUTH_50110: "account.authIpHelp",
  OKX_AUTH_50111: "account.authKeyHelp",
  OKX_AUTH_50112: "account.authTimestampHelp",
  OKX_AUTH_50113: "account.authSignatureHelp",
  OKX_AUTH_50114: "account.authAuthorizationHelp",
  OKX_AUTH_50119: "account.authRegionHelp",
};

/**
 * The key store of the computer the panel runs on. The desktop backend runs on
 * the same computer, so this matches the status's credentialStore.
 */
export function hostCredentialStore(userAgent: string = globalThis.navigator?.userAgent ?? ""): CredentialStore {
  return /\bWindows\b/.test(userAgent) ? "windows-credential-manager" : "macos-keychain";
}

export function accountErrorHelp(code: string, store: CredentialStore | null = hostCredentialStore()): MessageKey {
  if (Object.hasOwn(AUTH_HELP, code)) return AUTH_HELP[code]!;
  if (code === "READONLY_KEY_REQUIRED") return "account.readonlyKeyHelp";
  if (code === "HEDGE_ACCOUNT_REQUIRED") return "account.hedgeHelp";
  if (code.includes("KEYCHAIN") || code === "CREDENTIAL_STORE_UNAVAILABLE") {
    return store === "windows-credential-manager" ? "account.credentialManagerHelp" : "account.keychainHelp";
  }
  if (code.includes("DIFFERENT_ACCOUNT") || code === "ACCOUNT_IDENTITY_CHANGED") return "account.identityHelp";
  if (code === "ACCOUNT_PROXY_ROUTE_UNAVAILABLE") return "account.proxyRouteHelp";
  return "account.errorHelp";
}
