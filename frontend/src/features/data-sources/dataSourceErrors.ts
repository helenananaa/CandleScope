import type { MessageKey } from "../../i18n/index.js";

/** The message for a data-source error code; the code itself only goes in technical details. */
export function dataSourceErrorKey(code: string): MessageKey {
  switch (code) {
    case "DESKTOP_SESSION_REQUIRED":
      return "dataSources.desktopOnly";
    case "CREDENTIAL_VALUE_INVALID":
      return "dataSources.error.valueInvalid";
    case "DATA_SOURCE_KEY_REJECTED":
      return "dataSources.error.keyRejected";
    case "DATA_SOURCE_RATE_LIMITED":
      return "dataSources.error.rateLimited";
    case "DATA_SOURCE_UNREACHABLE":
      return "dataSources.error.unreachable";
    case "DATA_SOURCE_KEY_MISSING":
      return "dataSources.error.missing";
    case "CREDENTIAL_STORE_FAILED":
    case "CREDENTIAL_INDEX_WRITE_FAILED":
      return "dataSources.error.storeFailed";
    case "CREDENTIAL_VAULT_UNAVAILABLE":
      return "dataSources.vaultUnavailable";
    case "CREDENTIAL_NOT_FOUND":
    case "CREDENTIAL_READ_FAILED":
    case "CREDENTIAL_RECORD_INVALID":
    case "CREDENTIAL_INDEX_INVALID":
      return "dataSources.savedUnreadable";
    default:
      return "dataSources.error.generic";
  }
}

const PRINTABLE = /^[\x21-\x7e]{4,256}$/;

/** What the backend accepts: 4–256 visible ASCII characters, no spaces. */
export function validKeyInput(value: string): boolean {
  return PRINTABLE.test(value);
}
