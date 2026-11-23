import assert from "node:assert/strict";
import test from "node:test";
import { contrastRatio, legibleOn, parseColor } from "../legibleColor.js";

const ratio = (a: string, b: string) => contrastRatio(parseColor(a)!, parseColor(b)!);

test("candle colours that already read well are kept", () => {
  assert.equal(legibleOn("#22c55e", "#0f1115"), "#22c55e");
  assert.equal(legibleOn("#ef4444", "#141518"), "#ef4444");
});

test("candle colours on a light or custom background are darkened just enough to read", () => {
  for (const color of ["#22c55e", "#ef4444", "#26a69a", "#f7525f"]) {
    const shown = legibleOn(color, "#ffffff");
    assert.notEqual(shown, color);
    assert.ok(ratio(shown, "#ffffff") >= 4.5, `${color} → ${shown}`);
  }
  const onDarkCustom = legibleOn("#3a0000", "#101010");
  assert.ok(ratio(onDarkCustom, "#101010") >= 4.5, onDarkCustom);
});

test("colours it cannot read are left as they are", () => {
  assert.equal(legibleOn("var(--x)", "#ffffff"), "var(--x)");
  assert.equal(legibleOn("#22c55e", "transparent"), "#22c55e");
  assert.deepEqual(parseColor("rgba(1, 2, 3, 0.5)"), [1, 2, 3]);
  assert.deepEqual(parseColor("#abc"), [170, 187, 204]);
});
