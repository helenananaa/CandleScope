import assert from "node:assert/strict";
import test from "node:test";
import { MarketWindowRegistry } from "../window/marketWindowSession.js";
import { SeriesWindowStore } from "../window/seriesWindowStore.js";
import { captureStableSeries } from "../window/stableSeriesSnapshot.js";

const row = (time: number, close = 1, is_closed = false) => ({ time, open: 1, high: 5, low: 0, close, volume: 1, is_closed });
function fixture() {
  const owner = new MarketWindowRegistry().createWindow("a");
  const selection = owner.prepareSelection("btc"); owner.activate(selection);
  owner.transact(selection, () => { owner.getOrCreate("btc"); owner.apply("btc", { type: "replace", rows: [row(60, 1, true), row(120, 2, true), row(180)] }); });
  return { owner, selection, reader: owner.get("btc")! };
}

test("async captures are frozen and exact versions reject a same-identity tail mutation", () => {
  const { owner, selection, reader } = fixture();
  const input = reader.capture({ limit: 2 }), hot = reader.snapshot();
  assert.equal(input.isCurrent(), true);
  assert.throws(() => { (input.rows[0] as { close: number }).close = 99; }, TypeError);
  owner.transact(selection, () => owner.apply("btc", { type: "tick", row: row(180, 4) }));
  assert.equal(reader.snapshot(), hot);
  assert.equal(input.rows.at(-1)?.close, 1);
  assert.equal(input.isCurrent(), false);
  assert.equal(input.isCurrent("forming-preview"), true, "bounded previews may finish during continuous updates of the same open bar");
  owner.transact(selection, () => owner.apply("btc", { type: "tick", row: row(180, 4, true) }));
  assert.equal(input.isCurrent("forming-preview"), false, "close is a semantic barrier");
});

test("range captures accept unrelated forming updates, reject correction/deletion and owner ABA", () => {
  const { owner, selection, reader } = fixture();
  const input = reader.capture({ to: 120 });
  owner.transact(selection, () => owner.apply("btc", { type: "tick", row: row(180, 3) }));
  assert.equal(input.isCurrent("range"), true);
  owner.transact(selection, () => owner.apply("btc", { type: "replace", rows: [row(60, 4, true), row(180)] }));
  assert.equal(input.isCurrent("range"), false);
  const next = reader.capture();
  owner.activate(owner.prepareSelection("eth"));
  owner.activate(owner.prepareSelection("btc"));
  assert.equal(next.isCurrent(), false, "reader.commitState alone cannot detect selection ABA");
  const active = reader.capture(); owner.close();
  assert.equal(active.isCurrent(), false);
});

test("mutable static/replay inputs are copied and use exact version checks", () => {
  const store = new SeriesWindowStore({ seriesKey: "replay" });
  store.replace([row(60)]);
  const input = captureStableSeries(store);
  store.snapshot()[0]!.close = 4;
  assert.equal(input.rows[0]?.close, 1);
  store.applyTick(row(120));
  assert.equal(input.isCurrent("forming-preview"), false);
});
