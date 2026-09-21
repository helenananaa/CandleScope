import assert from "node:assert/strict";
import test from "node:test";
import { createSupportBundle, environmentInfo, fetchBackendSupport, issueUrl, parseBackendSupport } from "../supportDiagnostics.js";
import { frontendSupportLogs, recordSupportEvent } from "../supportLog.js";
import { supportArchive } from "../supportArchive.js";

const sample = () => ({ schema_version: 1, version: "0.3.0", data_engine: "active", token: "secret",
  logs: { started_at: 1, capacity: 500, dropped_since_start: 0, events: [
    { time: 2, level: "ERROR", source: "main.py", line: 42, has_exception: true, message: "private-source" },
  ] } });

test("ZIP archive uses standard CRC32 and exact UTF-8 member bytes", () => {
  const zip = supportArchive("123456789");
  const view = new DataView(zip.buffer);
  assert.equal(view.getUint32(0, true), 0x04034b50);
  assert.equal(view.getUint32(14, true), 0xcbf43926);
  const end = zip.length - 22;
  assert.equal(view.getUint32(end, true), 0x06054b50);
  assert.equal(view.getUint16(end + 10, true), 1);
  const directory = view.getUint32(end + 16, true);
  assert.equal(view.getUint32(directory, true), 0x02014b50);
  const unicode = supportArchive('原始文本😀');
  const unicodeView = new DataView(unicode.buffer);
  const offset = 30 + unicodeView.getUint16(26, true);
  assert.equal(new TextDecoder().decode(unicode.slice(offset, offset + unicodeView.getUint32(22, true))), '原始文本😀');
});

test("backend parser drops all non-allowlisted fields and rejects unsafe source paths", () => {
  const result = parseBackendSupport(sample());
  assert.ok(!JSON.stringify(result).includes("secret"));
  assert.ok(!JSON.stringify(result).includes("private-source"));
  for (const source of ["C:/Users/person/main.py", "../secret.py", "/home/person/app.py"]) {
    const value = sample(); value.logs.events[0]!.source = source;
    assert.throws(() => parseBackendSupport(value));
  }
  assert.throws(() => parseBackendSupport({ status: "ok" }));
});

test("frontend buffer is bounded, time filtered and excludes extra properties", () => {
  const now = Date.now();
  for (let i = 0; i < 305; i++) recordSupportEvent({ kind: "request_failed", status: 503, ...{ message: "secret" } }, now);
  const logs = frontendSupportLogs(15, now);
  assert.equal(logs.events.length, 300);
  assert.ok(logs.dropped_since_start >= 5);
  assert.ok(!JSON.stringify(logs).includes("secret"));
  assert.equal(frontendSupportLogs(15, now + 901_000).events.length, 0);
});

test("partial bundle identifies unavailable backend; Issue URL contains environment only", () => {
  const bundle = createSupportBundle(15, null);
  assert.equal(bundle.backend, null);
  assert.equal(bundle.missing.length, 1);
  assert.equal(bundle.environment.backend_connection, "unavailable");
  const url = new URL(issueUrl(environmentInfo(parseBackendSupport(sample()))));
  assert.equal(url.origin, "https://github.com");
  assert.equal(url.pathname, "/helenananaa/CandleScope/issues/new");
  assert.ok(url.searchParams.get("body")!.includes("0.3.0"));
  assert.ok(!url.searchParams.get("body")!.includes("main.py"));
});

test("support fetch reports HTTP failure and validates success without exposing raw server fields", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response("unavailable", { status: 503 });
    await assert.rejects(fetchBackendSupport(15));
    globalThis.fetch = async () => Response.json(sample());
    assert.equal((await fetchBackendSupport(15)).version, "0.3.0");
  } finally { globalThis.fetch = original; }
});
