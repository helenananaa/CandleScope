import assert from "node:assert/strict";
import test from "node:test";
import { admitDrawingUserMutation } from "../drawingInteractionController.js";

test("review refuses edit admission before touching the document or renderer", () => {
  let calls = 0;
  const prepare = () => { calls++; return true; };
  assert.equal(admitDrawingUserMutation(true, false, prepare), false);
  assert.equal(admitDrawingUserMutation(false, true, prepare), false);
  assert.equal(calls, 0);
  assert.equal(admitDrawingUserMutation(false, false, prepare), true);
  assert.equal(calls, 1);
  assert.equal(admitDrawingUserMutation(false, false, () => false), false);
});
