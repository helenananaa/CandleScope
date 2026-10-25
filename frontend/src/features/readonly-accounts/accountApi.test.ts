import assert from "node:assert/strict";
import test from "node:test";
import { AccountApiError, accountSession, connectAccount, getAccountStatus, getJournal, saveJournal } from "./accountApi.js";

const session = { apiBase: "http://127.0.0.1:8123/api/v2/plugins", sessionToken: "s".repeat(40), csrfToken: "c".repeat(40) };
const status = { schemaVersion: 1, readOnly: true, venue: "okx", available: true, account: null,
  snapshots: {}, counts: {}, scans: [], coverage: [], gaps: [], stream: { state: "stopped", lastReceivedMs: null, error: null }, reconciliation: "not_verified" };

async function environment(run: (setSession: (value: typeof session) => void) => Promise<void>) {
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

test("account transport denies nonlocal destinations before credentials or session tokens leave", async () => {
  await environment(async (setSession) => {
    let calls = 0;
    globalThis.fetch = async () => { calls++; return new Response("{}"); };
    for (const apiBase of ["https://example.com/api/v2/plugins", "http://127.0.0.1:8123/api/v2/plugins?redirect=example.com", "http://user:pass@127.0.0.1:8123/api/v2/plugins"]) {
      setSession({ ...session, apiBase });
      assert.equal(accountSession(), null);
      await assert.rejects(connectAccount({ apiKey: "fixture", secret: "fixture", password: "fixture" }), /DESKTOP_SESSION_REQUIRED/);
    }
    assert.equal(calls, 0);
  });
});

test("connection writes require both desktop authority headers, never URL credentials or redirect following", async () => {
  await environment(async () => {
    const calls: [string, RequestInit | undefined][] = [];
    globalThis.fetch = async (url, init) => { calls.push([String(url), init]); return Response.json(String(url).endsWith("/status") ? status : { connected: true }); };
    await connectAccount({ apiKey: "SENTINEL_KEY", secret: "SENTINEL_SECRET", password: "SENTINEL_PASSPHRASE" });
    const [url, init] = calls[0]!;
    assert.equal(url, "http://127.0.0.1:8123/api/v1/readonly-accounts/connect");
    assert.equal(init?.redirect, "error");
    assert.equal(init?.cache, "no-store");
    assert.equal(init?.credentials, "omit");
    const headers = init?.headers as Record<string, string>;
    assert.equal(headers["X-CandleScope-CSRF"], session.csrfToken);
    assert.equal(headers["X-CandleScope-Plugin-Session"], session.sessionToken);
    assert.equal(headers["X-CandleScope-User-Action"], "account.connect");
    await getAccountStatus();
    assert.equal(calls[1]![1]?.body, undefined);
    assert.equal(JSON.stringify(calls[1]).includes("SENTINEL"), false);
  });
});

test("upstream error messages and malformed journal values never enter the UI as accepted data", async () => {
  await environment(async () => {
    globalThis.fetch = async () => Response.json({ error: { code: "OKX_AUTH_50105", message: "SENTINEL_SECRET" } }, { status: 409 });
    await assert.rejects(connectAccount({ apiKey: "fixture", secret: "fixture", password: "fixture" }),
      (error: unknown) => error instanceof AccountApiError && error.code === "OKX_AUTH_50105" && !error.message.includes("SENTINEL"));
    globalThis.fetch = async () => Response.json({ error: { code: "secret SENTINEL", message: "SENTINEL" } }, { status: 409 });
    await assert.rejects(getAccountStatus(), (error: unknown) => error instanceof AccountApiError && error.code === "ACCOUNT_UNAVAILABLE" && !error.message.includes("SENTINEL"));
    globalThis.fetch = async () => Response.json({ versions: [{ noteId: "a".repeat(32), version: 1, payload: { text: {} } }] });
    await assert.rejects(getJournal(), /ACCOUNT_RESPONSE_INVALID/);
    globalThis.fetch = async () => Response.json({ schemaVersion: 1, readOnly: false, venue: "okx" });
    await assert.rejects(getAccountStatus(), /ACCOUNT_RESPONSE_INVALID/);
  });
});

test("journal autosave preserves base version and event time and accepts the new recorded version", async () => {
  await environment(async () => {
    const note = { noteId: "a".repeat(32), baseVersion: 3, text: "revised plan", tags: ["fixture"], kind: "plan" as const, eventMs: 100 };
    globalThis.fetch = async (_url, init) => {
      assert.deepEqual(JSON.parse(String(init?.body)), note);
      return Response.json({ noteId: note.noteId, version: 4, eventMs: 100, recordedMs: 200, fillId: null, payload: { text: note.text, tags: note.tags, kind: note.kind } });
    };
    const result = await saveJournal(note);
    assert.equal(result.version, 4);
    assert.equal(result.recordedMs, 200);
    assert.equal(result.eventMs, 100);
  });
});

test("journal reads exhaust pages and reject a repeated cursor instead of returning incomplete history", async () => {
  await environment(async () => {
    const row = { noteId: "a".repeat(32), version: 2, eventMs: 10, recordedMs: 20, fillId: null, payload: { text: "plan", tags: [], kind: "plan" } };
    const next = { noteId: row.noteId, version: 2, recordedMs: 20 };
    let calls = 0;
    globalThis.fetch = async (url) => {
      calls++;
      if (calls === 1) return Response.json({ versions: [row], next });
      assert.match(String(url), /before_recorded_ms=20/);
      return Response.json({ versions: [{ ...row, version: 1 }], next: null });
    };
    assert.deepEqual((await getJournal()).map((item) => item.version), [2, 1]);
    globalThis.fetch = async () => Response.json({ versions: [row], next });
    await assert.rejects(getJournal(), /JOURNAL_CURSOR_STALLED/);
  });
});
