import assert from "node:assert/strict";
import test from "node:test";
import { requestNativePortfolioDownload } from "../portfolioDownload.js";

test("browser download leaves the anchor and its stream with the browser", () => {
  assert.equal(requestNativePortfolioDownload("run-1", {}), null);
});

test("native export forwards only the run id and preserves host errors", async () => {
  const calls: string[] = [];
  const request = requestNativePortfolioDownload("run-1", { downloadReplayPortfolio: async id => { calls.push(id); return { started: true }; } });
  assert.deepEqual(await request, { started: true });
  assert.deepEqual(calls, ["run-1"]);
  await assert.rejects(requestNativePortfolioDownload("run-1", { downloadReplayPortfolio: async () => { throw new Error("closed window"); } })!, /closed window/);
});
