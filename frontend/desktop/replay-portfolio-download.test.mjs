import assert from "node:assert/strict";
import test from "node:test";
import { downloadReplayPortfolio } from "./replay-portfolio-download.mjs";

test("portfolio download uses only the host backend and starts a native stream", () => {
  const calls = [];
  const sender = { isDestroyed: () => false, downloadURL: url => calls.push(url) };
  assert.deepEqual(downloadReplayPortfolio(sender, 29123, "prepared-a:1"), { started: true });
  assert.deepEqual(calls, ["http://127.0.0.1:29123/api/v1/replay/runs/prepared-a%3A1/portfolio-equity/export"]);
});

test("download rejects arbitrary paths, URLs, unknown endpoints and closed windows", () => {
  const sender = { isDestroyed: () => false, downloadURL: () => assert.fail("must not download") };
  for (const id of [null, {}, "", "..", "a/../../settings", "http://example.com", "a?x=1", "a%2fb", "a\\b", "a\n", "x".repeat(129)]) {
    assert.throws(() => downloadReplayPortfolio(sender, 29123, id), /run id/);
  }
  for (const port of [0, -1, 65536, NaN, 1.5, "29123"]) assert.throws(() => downloadReplayPortfolio(sender, port, "run-a"), /backend/);
  assert.throws(() => downloadReplayPortfolio({ ...sender, isDestroyed: () => true }, 29123, "run-a"), /closed/);
});
