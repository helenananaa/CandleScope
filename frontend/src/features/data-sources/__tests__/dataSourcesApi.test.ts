import assert from "node:assert/strict";
import test from "node:test";
import {
  DataSourceApiError,
  checkDataSource,
  dataSourceSession,
  getDataSources,
  maskedKey,
  removeDataSourceKey,
  saveDataSourceKey,
  validateDataSourcesStatus,
} from "../dataSourcesApi.js";
import { dataSourceErrorKey, validKeyInput } from "../dataSourceErrors.js";

const KEY = "0123456789abcdef0123456789abWXYZ";
const session = { apiBase: "http://127.0.0.1:8123/api/v2/plugins", sessionToken: "s".repeat(40), csrfToken: "c".repeat(40) };

function field(overrides: Record<string, unknown> = {}) {
  return { id: "apiKey", saved: true, savedHint: "WXYZ", savedAtMs: 1_700_000_000_000, savedError: null,
    environmentVariable: "INGESTION_TWELVE_DATA_API_KEY", environmentSet: false, active: "saved", activeHint: "WXYZ",
    ...overrides };
}
function status(fieldValue: Record<string, unknown> = field()) {
  return { schemaVersion: 1, vaultAvailable: true, error: null, loaded: true, deletionPending: false,
    sources: [{ id: "twelvedata", name: "Twelve Data", signupUrl: "https://twelvedata.com/pricing", fields: [fieldValue] }] };
}

async function desktop(run: (setSession: (value: typeof session) => void) => Promise<void>) {
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const originalFetch = globalThis.fetch;
  let active = session;
  Object.defineProperty(globalThis, "window", { configurable: true, value: { candlescopeDesktop: { getPluginManagementSession: () => active } } });
  try { await run((value) => { active = value; }); }
  finally {
    globalThis.fetch = originalFetch;
    if (originalWindow) Object.defineProperty(globalThis, "window", originalWindow);
    else Reflect.deleteProperty(globalThis, "window");
  }
}

test("keys only go to the loopback desktop service", async () => {
  await desktop(async (setSession) => {
    let calls = 0;
    globalThis.fetch = async () => { calls++; return Response.json(status()); };
    for (const apiBase of ["https://example.com/api/v2/plugins", "http://127.0.0.1:8123/api/v2/plugins?x=1",
      "http://user:pass@127.0.0.1:8123/api/v2/plugins", "http://127.0.0.1:8123/elsewhere"]) {
      setSession({ ...session, apiBase });
      assert.equal(dataSourceSession(), null);
      await assert.rejects(saveDataSourceKey("twelvedata", "apiKey", KEY), /DESKTOP_SESSION_REQUIRED/);
    }
    setSession({ ...session, csrfToken: session.sessionToken });
    assert.equal(dataSourceSession(), null);
    assert.equal(calls, 0);
  });
});

test("saving sends the key once, with the desktop session, CSRF token and user action", async () => {
  await desktop(async () => {
    const calls: [string, RequestInit | undefined][] = [];
    globalThis.fetch = async (url, init) => { calls.push([String(url), init]); return Response.json(status()); };
    const saved = await saveDataSourceKey("twelvedata", "apiKey", KEY);
    assert.equal(saved.sources[0]?.fields[0]?.savedHint, "WXYZ");
    const [url, init] = calls[0]!;
    assert.equal(url, "http://127.0.0.1:8123/api/v1/data-sources/twelvedata/credentials/apiKey");
    assert.equal(init?.method, "POST");
    assert.equal(init?.redirect, "error");
    assert.equal(init?.credentials, "omit");
    assert.equal(init?.cache, "no-store");
    assert.deepEqual(JSON.parse(String(init?.body)), { value: KEY });
    const headers = init?.headers as Record<string, string>;
    assert.equal(headers["X-CandleScope-Plugin-Session"], session.sessionToken);
    assert.equal(headers["X-CandleScope-CSRF"], session.csrfToken);
    assert.equal(headers["X-CandleScope-User-Action"], "data-sources.save");

    await getDataSources();
    assert.equal(calls[1]![0], "http://127.0.0.1:8123/api/v1/data-sources");
    assert.equal(calls[1]![1]?.body, undefined);
    assert.equal((calls[1]![1]?.headers as Record<string, string>)["X-CandleScope-CSRF"], undefined);

    await removeDataSourceKey("twelvedata", "apiKey");
    assert.equal(calls[2]![0], "http://127.0.0.1:8123/api/v1/data-sources/twelvedata/credentials/apiKey/remove");
    assert.equal((calls[2]![1]?.headers as Record<string, string>)["X-CandleScope-User-Action"], "data-sources.remove");
    assert.equal(String(calls[2]![1]?.body).includes(KEY), false);
  });
});

test("a status that would carry more than a masked hint is refused", () => {
  assert.doesNotThrow(() => validateDataSourcesStatus(status()));
  for (const leak of [field({ savedHint: KEY }), field({ activeHint: KEY }), field({ savedHint: "WXYZ1" }), field({ savedHint: "" })]) {
    assert.throws(() => validateDataSourcesStatus(status(leak)), /DATA_SOURCES_RESPONSE_INVALID/);
  }
  assert.throws(() => validateDataSourcesStatus(status(field({ active: "plaintext" }))), /DATA_SOURCES_RESPONSE_INVALID/);
  assert.throws(() => validateDataSourcesStatus({ ...status(), schemaVersion: 2 }), /DATA_SOURCES_RESPONSE_INVALID/);
});

test("masked keys show at most the last four characters", () => {
  assert.equal(maskedKey("WXYZ"), "••••WXYZ");
  assert.equal(maskedKey(null), "••••");
});

test("errors keep the code and drop the service's words", async () => {
  await desktop(async () => {
    globalThis.fetch = async () => Response.json({ error: { code: "DATA_SOURCE_RATE_LIMITED", retryAfterSeconds: 42, message: "SENTINEL" } }, { status: 409 });
    await assert.rejects(checkDataSource("twelvedata"), (error: unknown) => error instanceof DataSourceApiError
      && error.code === "DATA_SOURCE_RATE_LIMITED" && error.retryAfterSeconds === 42 && !error.message.includes("SENTINEL"));
    globalThis.fetch = async () => Response.json({ error: { code: "key SENTINEL" } }, { status: 409 });
    await assert.rejects(checkDataSource("twelvedata"), (error: unknown) => error instanceof DataSourceApiError
      && error.code === "DATA_SOURCES_UNAVAILABLE");
    globalThis.fetch = async () => { throw new Error("SENTINEL offline"); };
    await assert.rejects(getDataSources(), /DATA_SOURCES_NETWORK_UNAVAILABLE/);
  });
});

test("a check result is validated before it is shown", async () => {
  await desktop(async () => {
    const usage = { plan: "basic", minuteCredits: { used: 1, limit: 8 }, dailyCredits: { used: 40, limit: 800 }, websocketSymbols: 8 };
    globalThis.fetch = async () => Response.json({ ok: true, source: "saved", checkedAtMs: 1, usage });
    assert.deepEqual((await checkDataSource("twelvedata")).usage, usage);
    globalThis.fetch = async () => Response.json({ ok: true, source: "saved", checkedAtMs: 1, usage: { ...usage, minuteCredits: { used: 1 } } });
    await assert.rejects(checkDataSource("twelvedata"), /DATA_SOURCES_RESPONSE_INVALID/);
  });
});

test("keys are checked like the local service checks them, and codes map to messages", () => {
  assert.equal(validKeyInput(KEY), true);
  assert.equal(validKeyInput("demo"), true, "Twelve Data's public trial key");
  for (const value of ["", "abc", `${KEY} `, "with space key", "é".repeat(12), "x".repeat(257)]) {
    assert.equal(validKeyInput(value), false, value);
  }
  assert.equal(dataSourceErrorKey("DATA_SOURCE_KEY_REJECTED"), "dataSources.error.keyRejected");
  assert.equal(dataSourceErrorKey("CREDENTIAL_NOT_FOUND"), "dataSources.savedUnreadable");
  assert.equal(dataSourceErrorKey("CREDENTIAL_VAULT_UNAVAILABLE"), "dataSources.vaultUnavailable");
  assert.equal(dataSourceErrorKey("DATA_SOURCES_NETWORK_UNAVAILABLE"), "dataSources.error.generic");
  assert.equal(dataSourceErrorKey("SOMETHING_NEW"), "dataSources.error.generic");
});
