import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import PreparationWaiting from "./PreparationWaiting.js";
import type { PreparationJob } from "./api.js";

test("rate-limit waiting is disclosed for a running task and hidden after completion", () => {
  const job = { state: "RUNNING", waiting: { reason: "RATE_LIMIT", retry_at_ms: 1709251200000 } } as PreparationJob;
  const html = renderToStaticMarkup(<PreparationWaiting job={job} />);
  assert.match(html, /role="status"/);
  assert.match(html, /2024/);
  assert.doesNotMatch(html, /RATE_LIMIT|rate_limit_bucket/);
  assert.equal(renderToStaticMarkup(<PreparationWaiting job={{ ...job, state: "READY" }} />), "");
  assert.equal(renderToStaticMarkup(<PreparationWaiting job={{ ...job, waiting: null }} />), "");
});

test("a storage-gated task explains the wait and clears the notice when it progresses or stops", () => {
  const job = { state: "RUNNING", stage: "CHECKING_STORAGE", waiting: null } as PreparationJob;
  const html = renderToStaticMarkup(<PreparationWaiting job={job} />);
  assert.match(html, /role="status"/);
  assert.match(html, /核对磁盘文件|Checking stored files/);
  assert.doesNotMatch(html, /CHECKING_STORAGE/);
  for (const state of ["READY", "CANCELLED", "FAILED", "BLOCKED_STORAGE"] as const) {
    assert.equal(renderToStaticMarkup(<PreparationWaiting job={{ ...job, state }} />), "");
  }
  assert.equal(renderToStaticMarkup(<PreparationWaiting job={{ ...job, stage: "FETCHING" }} />), "");
});
