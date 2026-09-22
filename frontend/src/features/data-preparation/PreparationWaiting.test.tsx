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
