import assert from "node:assert/strict";
import test from "node:test";

import { shouldFollowLiveTail, shouldPreserveProjectionViewport } from "../projectionViewportPolicy.js";

test("viewport preservation requires an existing projected display", () => {
  for (const delta of [
    { type: "prepend" },
    { type: "mid-merge" },
    { type: "replace" },
    { type: "trim-left" },
    { type: "trim-right" },
    { type: "tick", trimmedLeft: 1 },
    { type: "append", trimmedRight: 1 },
  ]) {
    assert.equal(shouldPreserveProjectionViewport(delta), false);
  }
});

test("structural merge and trim deltas preserve an existing viewport", () => {
  for (const type of ["prepend", "mid-merge", "trim-left", "trim-right"]) {
    assert.equal(
      shouldPreserveProjectionViewport({ type }, { hasDisplay: true }),
      true,
    );
  }
});

test("replace preserves only a user-owned existing viewport", () => {
  assert.equal(
    shouldPreserveProjectionViewport(
      { type: "replace" },
      { hasDisplay: true, userInteracted: false },
    ),
    false,
  );
  assert.equal(
    shouldPreserveProjectionViewport(
      { type: "replace" },
      { hasDisplay: true, userInteracted: true },
    ),
    true,
  );
});

test("tick and append preserve only when they also trim the window", () => {
  assert.equal(
    shouldPreserveProjectionViewport(
      { type: "tick", trimmedLeft: 1 },
      { hasDisplay: true },
    ),
    true,
  );
  assert.equal(
    shouldPreserveProjectionViewport(
      { type: "append", trimmedRight: 2 },
      { hasDisplay: true },
    ),
    true,
  );
  assert.equal(
    shouldPreserveProjectionViewport(
      { type: "tick", trimmedLeft: 0, trimmedRight: 0 },
      { hasDisplay: true },
    ),
    false,
  );
  assert.equal(
    shouldPreserveProjectionViewport({ type: "append" }, { hasDisplay: true }),
    false,
  );
});

test("noop, clear, and unknown deltas never preserve the viewport", () => {
  for (const delta of [
    { type: "noop" },
    { type: "clear" },
    { type: "unknown", trimmedLeft: 1 },
    null,
  ]) {
    assert.equal(
      shouldPreserveProjectionViewport(delta, { hasDisplay: true }),
      false,
    );
  }
});

// RC 5/16 reopen: the stored rows end at 03:35, the missed bars arrive as one
// window commit up to 04:00. The view that showed 03:35 must show 04:00.
const reopenCommit = {
  latestBarVisible: true,
  previousLastTime: 1_795_577_700,
  nextLastTime: 1_795_579_200,
  rightEdgeCurrent: true,
  sessionViewportPlaced: true,
  userInteracted: false,
};

test("a live chart showing its latest bar follows rows added after it", () => {
  assert.equal(shouldFollowLiveTail(reopenCommit), true);
});

test("the live tail is not followed when the view or the window says otherwise", () => {
  for (const [name, change] of [
    ["latest bar off screen (user is in history)", { latestBarVisible: false }],
    ["jumped-to window whose right edge is not current", { rightEdgeCurrent: false }],
    ["first view not placed yet (session restore owns it)", { sessionViewportPlaced: false }],
    ["user moved the view", { userInteracted: true }],
    ["no rows after the previous latest bar", { nextLastTime: reopenCommit.previousLastTime }],
    ["rows only removed on the right", { nextLastTime: reopenCommit.previousLastTime - 60 }],
    ["no previous rows", { previousLastTime: null }],
    ["no committed rows", { nextLastTime: null }],
    ["non-finite time", { nextLastTime: Number.NaN }],
  ] as const) {
    assert.equal(shouldFollowLiveTail({ ...reopenCommit, ...change }), false, name);
  }
  assert.equal(shouldFollowLiveTail(), false);
});
