import assert from "node:assert/strict";
import test from "node:test";
import { parseKlineBar } from "../../../services/apiPayloadParsers.js";
import { MarketWindowRegistry } from "../window/marketWindowSession.js";
import { initialHistoryCacheProof } from "../useChartInitialLoad.js";
import type { KlineFetchResult } from "../klineContracts.js";
import { epochSeconds } from "../../../test/testHelpers.js";

const row = (time = 60) => ({ time: epochSeconds(time), open: 1, high: 2, low: 0, close: 1, volume: 3, is_closed: true });
const proof = (data = [row()]): KlineFetchResult => ({ data, complete: true, retryable: false,
  history_state: "ready", verified_contiguous: true, all_rows_final: true, has_tail_gap: false, missing_ranges: [] });

test("transport rejects impossible OHLC and negative total volume with a field reason", () => {
  for (const patch of [{ high: -1 }, { low: 3 }, { open: 4 }, { close: -1 }, { volume: -1 }]) {
    assert.throws(() => parseKlineBar({ ...row(), ...patch }), /Invalid API payload/);
  }
});

test("valid negative prices and signed order-flow deltas retain their semantics", () => {
  const actual = parseKlineBar({ ...row(), open: -10, high: -5, low: -15, close: -8, volume: 0,
    order_flow: { taker_sell_base: 3, volume_delta_base: -3, taker_buy_ratio_base: 0, cvd_contribution_base: -3 } });
  assert.equal(actual.close, -8);
  assert.equal(actual.order_flow?.volume_delta_base, -3);
});

test("a response cannot prove final history while its own row is explicitly forming", () => {
  assert.equal(initialHistoryCacheProof(proof([{ ...row(), is_closed: false }]), 1).historyComplete, false);
});

test("the owned admission boundary quarantines an entire invalid batch before publishing data", () => {
  const session = new MarketWindowRegistry().createWindow();
  const token = session.prepareSelection("btc");
  session.activate(token);
  session.transact(token, () => { session.getOrCreate("btc"); session.apply("btc", { type: "replace", rows: [row()] }); });
  const reader = session.get("btc")!;
  const revision = reader.version;
  session.transact(token, () => {
    session.apply("btc", { type: "range", rows: [row(120), { ...row(180), volume: -1 }] });
    session.touchMeta("btc", { historyComplete: true });
  });
  assert.equal(reader.version, revision);
  assert.equal(reader.barCount, 1);
  assert.equal(reader.commitState.historyComplete, false);
});

test("a delayed forming row cannot reopen a final row in any window write path", () => {
  for (const type of ["tick", "range", "replace", "correct", "forward"] as const) {
    const session = new MarketWindowRegistry().createWindow();
    const token = session.prepareSelection("btc"); session.activate(token);
    session.transact(token, () => { session.getOrCreate("btc"); session.apply("btc", { type: "replace", rows: [row()] }); });
    session.transact(token, () => {
      const incoming = { ...row(), close: 0.5, is_closed: false };
      session.apply("btc", type === "tick" ? { type, row: incoming } : { type, rows: [incoming] });
    });
    assert.equal(session.get("btc")!.last()?.is_closed, true, type);
    assert.equal(session.get("btc")!.last()?.close, 1, type);
  }
});

test("an invalid desktop seed cannot hydrate an owned window", () => {
  const session = new MarketWindowRegistry({ sharedSnapshot: {
    read: () => [{ ...row(), high: -1 }], publish: () => {},
  } }).createWindow();
  const token = session.prepareSelection("btc"); session.activate(token);
  session.transact(token, () => session.getOrCreate("btc"));
  assert.equal(session.get("btc")!.barCount, 0);
});

test("endpoint quality distinguishes final history, forming continuity and terminal availability", async () => {
  const { assessKlineQuality, hasVerifiedRangeCoverage } = await import("../quality/klineQualityPolicy.js");
  const complete = proof();
  assert.equal(assessKlineQuality(complete, "history").complete, true);
  assert.equal(assessKlineQuality(complete, "before").complete, true);
  assert.equal(assessKlineQuality(complete, "range").complete, false, "range requires explicit truncation proof");
  assert.equal(assessKlineQuality({ ...complete, truncated: false }, "range").complete, true);
  for (const endpoint of ["latest", "seed"] as const) assert.equal(assessKlineQuality(complete, endpoint).complete, false);
  for (const patch of [{ complete: false }, { missing_ranges: undefined }, { has_tail_gap: undefined },
    { verified_contiguous: undefined }, { retryable: undefined }, { history_state: undefined }, { all_rows_final: undefined }]) {
    assert.equal(assessKlineQuality({ ...complete, ...patch } as KlineFetchResult, "history").complete, false);
  }
  const exhausted: KlineFetchResult = { data: [], history_state: "exhausted", retryable: false };
  assert.equal(assessKlineQuality(exhausted, "history").repairPending, false);
  assert.equal(assessKlineQuality(exhausted, "history").complete, false);
  const forming = { ...complete, data: [{ ...row(), is_closed: false }], truncated: false, all_rows_final: false };
  assert.equal(hasVerifiedRangeCoverage(forming), true);
  assert.equal(assessKlineQuality(forming, "range").complete, false);
  assert.equal(hasVerifiedRangeCoverage({ ...forming, all_rows_final: true }), false, "contradictory proof is not recovery proof");
});

test("final/forming, amendment, quote and request-fence conflicts have explicit outcomes", async () => {
  const { assessRealtimeEffect, chooseHttpRow } = await import("../quality/klineQualityPolicy.js");
  const held = row();
  const forming = { ...held, is_closed: false };
  assert.equal(assessRealtimeEffect(forming, "bar.updated", held, 60).accepted, false);
  const amendment = { ...held, close: 1.5 };
  const effect = assessRealtimeEffect(amendment, "bar.amended", held, 120);
  assert.deepEqual([effect.accepted, effect.updatesQuote, effect.updatesFreshness, effect.requiresReadback], [true, false, false, true]);
  assert.equal(assessRealtimeEffect(held, "bar.amended", held, 120).requiresReadback, false);
  assert.equal(assessRealtimeEffect(held, "bar.closed", undefined, 120).updatesFreshness, false);
  assert.equal(assessRealtimeEffect(row(180), "bar.closed", undefined, 120).updatesQuote, true);
  assert.equal(chooseHttpRow({ ...held, source_revision: 999 }, { row: amendment, authoritative: true, version: 2 }, 1, true), "realtime");
  assert.equal(chooseHttpRow(held, { row: forming, authoritative: false, version: 2 }, 1, true), "promote-http");
  assert.equal(chooseHttpRow(forming, { row: forming, authoritative: false, version: 2 }, 1, false), "realtime");
  assert.equal(chooseHttpRow(held, undefined, 1, true), "http");
});

test("quality evidence and retained rows are published with the same owned revision", async () => {
  const { assessKlineQuality } = await import("../quality/klineQualityPolicy.js");
  const session = new MarketWindowRegistry().createWindow(); const token = session.prepareSelection("btc"); session.activate(token);
  session.transact(token, () => session.getOrCreate("btc"));
  const reader = session.get("btc")!;
  let observed = 0;
  reader.subscribe(() => {
    observed += 1;
    const admission = reader.commitState.admission as { dataRevision: number; inputQuality: { scope: string; rowCount: number } };
    assert.equal(admission.dataRevision, reader.commitState.dataRevision);
    assert.equal(admission.inputQuality.scope, "response");
    assert.equal(admission.inputQuality.rowCount, 1);
    assert.equal(reader.last()?.close, 1);
  });
  session.transact(token, () => session.apply("btc", { type: "range", rows: [row()], quality: assessKlineQuality(proof(), "history") }));
  assert.equal(observed, 1);
});

test("endpoint decoder preserves missing proof fields and rejects malformed envelopes before policy", async () => {
  const { parseKlineResponse } = await import("../../../services/apiPayloadParsers.js");
  const { decodeKlineResult } = await import("../feed/klineEndpointDecoder.js");
  const { assessKlineQuality } = await import("../quality/klineQualityPolicy.js");
  for (const endpoint of ["history", "before", "range", "latest"] as const) {
    const decoded = decodeKlineResult(parseKlineResponse(proof()), endpoint);
    assert.equal(decoded.endpoint, endpoint);
    assert.equal(Object.hasOwn(decoded, "truncated"), false);
    assert.equal(assessKlineQuality(decoded, endpoint).complete, endpoint === "history" || endpoint === "before");
  }
  for (const patch of [{ all_rows_final: "true" }, { verified_contiguous: 1 }, { has_tail_gap: null },
    { missing_ranges: [{ start_ms: 2000, end_ms: 1000 }] }]) {
    assert.throws(() => decodeKlineResult(parseKlineResponse({ ...proof(), ...patch }), "range"));
  }
});

test("a contradictory capped parent cannot become complete through valid child proofs", async () => {
  const { aggregateResolvedGapRepairResult } = await import("../feed/seriesDataFeed.js");
  const { isKlineTailFresh } = await import("../quality/klineQualityPolicy.js");
  const parent = { ...proof([{ ...row(), is_closed: false }]), truncated: true };
  const result = aggregateResolvedGapRepairResult(parent, { start: epochSeconds(60), end: epochSeconds(120) },
    [{ ...proof([row(120)]), truncated: false }]);
  assert.equal(result.complete, false);
  assert.equal(isKlineTailFresh({ data: [row()], has_tail_gap: false }), false);
  assert.equal(isKlineTailFresh(proof([{ ...row(), is_closed: false }])), false);
  assert.equal(isKlineTailFresh({ ...proof([{ ...row(), is_closed: false }]), all_rows_final: false }), true);
});
