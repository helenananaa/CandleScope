import assert from "node:assert/strict";
import test from "node:test";
import { streamAccountState } from "./accountStateStream.js";
import { ReadOnlyAccountDataManager } from "./accountDataManager.js";
import type { AccountStatus } from "./accountApi.js";

const epoch = "a".repeat(32);
const state = { schemaVersion: 1, readOnly: true, venue: "okx", available: true, account: null,
  snapshots: {}, counts: {}, scans: [], coverage: [], gaps: [], stream: { state: "stopped", lastReceivedMs: null, error: null }, reconciliation: "not_verified" };
const event = (sequence: number) => ({ schema: "candlescope.readonly-account-state/1", type: "snapshot", replacement: true,
  identity: { venue: "okx", venueUid: null, epoch }, cursor: { epoch, sequence }, state: { ...state, cursor: { epoch, sequence } } });

async function environment(run: () => Promise<void>) {
  const original = Object.getOwnPropertyDescriptor(globalThis, "window"), fetch = globalThis.fetch;
  Object.defineProperty(globalThis, "window", { configurable: true, value: { candlescopeDesktop: { getPluginManagementSession: () => ({
    apiBase: "http://127.0.0.1:8123/api/v2/plugins", sessionToken: "s".repeat(40), csrfToken: "c".repeat(40) }) } } });
  try { await run(); } finally { globalThis.fetch = fetch; if (original) Object.defineProperty(globalThis, "window", original); else Reflect.deleteProperty(globalThis, "window"); }
}

test("private snapshots use authenticated local headers and tolerate split UTF8 frames, abort releases the reader", async () => {
  await environment(async () => {
    let cancelled = false, calls = 0;
    globalThis.fetch = async (url, init) => {
      calls++;
      assert.equal(String(url), "http://127.0.0.1:8123/api/v1/readonly-accounts/events");
      assert.equal(init?.redirect, "error"); assert.equal(init?.cache, "no-store"); assert.equal(init?.credentials, "omit");
      assert.equal((init?.headers as Record<string,string>)["X-CandleScope-Plugin-Session"], "s".repeat(40));
      const bytes = new TextEncoder().encode(JSON.stringify(event(1)) + "\n");
      return new Response(new ReadableStream({ start(c) { c.enqueue(bytes.slice(0, 15)); c.enqueue(bytes.slice(15)); }, cancel() { cancelled = true; } }),
        { headers: { "Content-Type": "application/x-ndjson" } });
    };
    const controller = new AbortController(); let updates = 0;
    await assert.rejects(streamAccountState(controller.signal, () => { updates++; controller.abort(); }));
    assert.equal(updates, 1); assert.equal(calls, 1); assert.equal(cancelled, true);
  });
});

test("a stale or mismatched account cursor cannot replace the current snapshot", async () => {
  await environment(async () => {
    for (const bad of [event(1), { ...event(3), identity: { venue: "okx", venueUid: "other", epoch } },
      { ...event(3), cursor: { epoch: "b".repeat(32), sequence: 3 } }]) {
      let updates = 0;
      globalThis.fetch = async () => new Response(JSON.stringify(event(2))+"\n"+JSON.stringify(bad)+"\n", { headers: { "Content-Type": "application/x-ndjson" } });
      await assert.rejects(streamAccountState(new AbortController().signal, () => { updates++; }), /ACCOUNT_RESPONSE_INVALID/);
      assert.equal(updates, 1);
    }
  });
});

test("one shared connection owns all views; releasing one retains sync, releasing all fences old callbacks", async () => {
  const attempts: { signal: AbortSignal; update: (value: AccountStatus) => void }[] = [];
  const manager = new ReadOnlyAccountDataManager((signal, update) => {
    attempts.push({ signal, update });
    return new Promise((_, reject) => signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true }));
  });
  let first = 0, second = 0;
  const a = manager.subscribe(() => { first++; }, () => {}), b = manager.subscribe(() => { second++; }, () => {});
  assert.equal(attempts.length, 1);
  attempts[0]!.update(state as unknown as AccountStatus);
  assert.equal(first, 1); assert.equal(second, 1);
  a(); assert.equal(attempts[0]!.signal.aborted, false);
  b(); assert.equal(attempts[0]!.signal.aborted, true);
  const c = manager.subscribe(() => { first++; }, () => {});
  attempts[0]!.update(state as unknown as AccountStatus);
  assert.equal(first, 1); assert.equal(attempts.length, 2);
  c(); manager.dispose();
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(manager.diagnostics().connections, 0);
  assert.equal(manager.diagnostics().subscriptions, 0);
});
