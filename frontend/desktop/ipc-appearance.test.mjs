import assert from "node:assert/strict";
import test from "node:test";

import { DESKTOP_IPC, validateAppearancePayload } from "./ipc-contract.mjs";

test("appearance payloads accept only a #rrggbb background", () => {
  assert.equal(DESKTOP_IPC.appearance, "candlescope:desktop:appearance");
  assert.deepEqual(validateAppearancePayload({ background: "#0D0E10" }), { background: "#0d0e10" });
  for (const bad of [null, "#fff", { background: "#fff" }, { background: "red" }, { background: "url(x)" }, { background: 1 }]) {
    assert.throws(() => validateAppearancePayload(bad), /#rrggbb/);
  }
});
