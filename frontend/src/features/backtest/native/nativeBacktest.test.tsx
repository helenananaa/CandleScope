import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { nativeTimeframe, nativeTerminal, type NativeRun } from "./nativeBacktestApi.js";
import { NativeCurve, NativeStrategyReport } from "./NativeStrategyReport.js";
import { NativeReplayControls } from "./NativeReplayControls.js";
import { t } from "../../../i18n/index.js";

test("sampled book reports disclose bounded taker-only policy separately from full depth", () => {
  const run: NativeRun = { run_id: "sampled", execution_mode: "CANDLESCOPE", state: "COMPLETED", created_at_ms: 1,
    runtime_identity: { engine: { package: "pyne-runtime", version: "0.4.0", code_sha256: "hash" } },
    result: { account_authority: "candlescope", fill_model: "SAMPLED_L2_VISIBLE_TAKER_ONLY_V1", fidelity: "BOOK_SAMPLED", report_hash: "hash",
      equity: [], trades: [], orders: [], bars: [], graphics: [], raw_output: {}, diagnostics: [] } };
  const html = renderToStaticMarkup(<NativeStrategyReport run={run} />);
  assert.ok(html.includes(t("native.external.sampledHint")));
  assert.ok(!html.includes(t("native.external.depthHint")));
  assert.match(html, /BOOK_SAMPLED/);
});

test("external reports label host authority and cannot open native replay", () => {
  const run: NativeRun = { run_id: "host_test", execution_mode: "CANDLESCOPE", state: "COMPLETED", created_at_ms: 1,
    runtime_identity: { engine: { package: "pyne-runtime", version: "0.4.0", code_sha256: "hash" } },
    result: { account_authority: "candlescope", fill_model: "BAR_NEXT_BAR_WORST_CASE_V1", report_hash: "hash",
      equity: [{ time: 1, value: 999 }], trades: [], orders: [], bars: [], graphics: [], raw_output: {}, diagnostics: [] } };
  const html = renderToStaticMarkup(<NativeStrategyReport run={run} />);
  assert.match(html, /external\/runs\/host_test\/export/);
  assert.match(html, /pyne-runtime/);
  assert.doesNotMatch(html, /native-replay-controls/);
});

test("replay starts paused with a server cursor and no future account output", () => {
  const html = renderToStaticMarkup(<NativeReplayControls runId="run" onChange={() => {}} replay={{
    replay_id: "replay", run_id: "run", state: "PAUSED", revision: 0, cursor: 0, total: 200,
    result: null, snapshots: [], error: null,
  }} />);
  assert.match(html, /0 \/ 200/);
  assert.match(html, /PAUSED/);
  assert.doesNotMatch(html, /<svg/);
});

test("a report without replay output keeps controls mounted instead of blanking the panel", () => {
  const run: NativeRun = { run_id: "empty-replay", execution_mode: "NATIVE", state: "COMPLETED", created_at_ms: 1,
    runtime_identity: { engine: { package: "pine-compat-runtime", version: "test", code_sha256: "hash" } }, result: null };
  const html = renderToStaticMarkup(<NativeStrategyReport run={run} />);
  assert.match(html, /native-report-toolbar/);
  assert.match(html, /native-replay-controls/);
  assert.ok(html.includes(t("native.replay.empty")));
  assert.doesNotMatch(html, /native-report-metrics|<svg|download=/);
});

test("native chart markers retain engine fill prices", () => {
  const html = renderToStaticMarkup(<NativeCurve title="Native fills" points={[{ time: 1, value: 10 }, { time: 2, value: 20 }]}
    markers={[{ time: 1, value: 9.5, kind: "entry" }, { time: 2, value: 20.5, kind: "exit" }]} />);
  assert.equal((html.match(/<circle/g) ?? []).length, 2);
  assert.match(html, /9\.5/);
  assert.match(html, /20\.5/);
});

test("native timeframe conversion preserves minute/month distinctions", () => {
  assert.equal(nativeTimeframe("1m"), "1");
  assert.equal(nativeTimeframe("1M"), "1M");
  assert.equal(nativeTimeframe("4h"), "240");
  assert.equal(nativeTimeframe("30s"), "30S");
  assert.throws(() => nativeTimeframe("unknown"));
  assert.ok(nativeTerminal("INTERRUPTED"));
  assert.ok(!nativeTerminal("RUNNING"));
});

test("native report shows authority, native trades and export independently of host ledger", () => {
  const run: NativeRun = { run_id: "native_test", state: "COMPLETED", created_at_ms: 1,
    runtime_identity: { engine: { package: "pine-compat-runtime", version: "0.3.0rc1", code_sha256: "hash" } },
    result: { account_authority: "pine-compat-runtime", fill_model: "pine-native-standard-ohlcv", report_hash: "hash",
      equity: [{ time: 1, value: 10000 }, { time: 2, value: 10005 }],
      trades: [{ id: "native-trade-1", profit: 5 }], orders: [], bars: [], graphics: [], raw_output: { strategy: {} }, diagnostics: [] },
  };
  const html = renderToStaticMarkup(<NativeStrategyReport run={run} />);
  assert.match(html, /pine-compat-runtime/);
  assert.match(html, /native-trade-1/);
  assert.match(html, /native\/runs\/native_test\/export/);
  assert.match(html, /0\.05%/);
  assert.ok(html.includes(t("report.change")));
  assert.doesNotMatch(html, /SimulationKernel/);
});
