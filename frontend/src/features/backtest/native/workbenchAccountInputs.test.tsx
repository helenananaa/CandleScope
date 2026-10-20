import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { WorkbenchAccountSettings } from "./WorkbenchAccountSettings.js";
import { defaultWorkbenchAccount, parseAccountData, workbenchAccountError, workbenchAccountInputs } from "./workbenchAccountInputs.js";
import { automaticHostExecution, executionInputs } from "./nativeInputs.js";
import { defaultExecutionDraft, executionSettingsChanged, restoreExecutionDraft } from "./nativeExecutionSettings.js";

const data = { symbol: "BTCUSDT", events: [{ time_ms: -1, role: "MARK_INDEX", payload: { mark_price: "10" } }] };
const account = { ...defaultWorkbenchAccount(), accountModel: "LINEAR_PERP_ONE_WAY_V2", fundingMode: "HISTORICAL_REQUIRED",
  participationEnabled: true, participationRate: .5, uploaded: true };

test("account import rejects unordered, unsupported and non-object event data", () => {
  assert.deepEqual(parseAccountData(JSON.stringify(data)), data);
  for (const invalid of [[], { ...data, events: [] }, { ...data, events: [{ ...data.events[0], role: "TRADES" }] },
    { ...data, events: [{ ...data.events[0], time_ms: 1.5 }] }, { ...data, events: [...data.events, { ...data.events[0], time_ms: -2 }] }])
    assert.throws(() => parseAccountData(JSON.stringify(invalid)));
});

test("manual and automatic submission preserve BAR callbacks and the same frozen account fields", () => {
  const host = defaultExecutionDraft().hostSettings;
  const options = { language: "pine" as const, account, accountData: data };
  const manual = executionInputs("CANDLESCOPE", host, "BAR_APPROX", true, null, options);
  const automatic = automaticHostExecution("CANDLESCOPE", host, "BAR_APPROX", true, null, options);
  assert.deepEqual(manual, { ...automatic, execution_data: null });
  assert.equal(manual.fill_recalculation, true);
  assert.equal(manual.account_data, data);
  assert.equal(manual.participation_rate, .5);
  assert.equal(manual.funding_mode, "HISTORICAL_REQUIRED");
  assert.equal(automaticHostExecution("CANDLESCOPE", host, "TRADE_TAPE", true, null, options), undefined);
  assert.throws(() => executionInputs("CANDLESCOPE", host, "BAR_APPROX", false, null, options));
});

test("restored uploads stay blocked and invalid finite inputs are retained for correction", () => {
  const restored = restoreExecutionDraft(JSON.stringify({ ...defaultExecutionDraft(), account: { ...account, leverage: 0 } }));
  assert.equal(restored.account?.leverage, 0);
  assert.equal(restored.account?.uploaded, true);
  assert.ok(workbenchAccountError(account, null, "missing", "pine", "BAR_APPROX", true));
  assert.ok(workbenchAccountError(account, data, "ready", "pyne", "BAR_APPROX", true));
  assert.ok(workbenchAccountError(account, data, "ready", "pine", "BAR_APPROX", true, "spot"));
  assert.equal(workbenchAccountError(account, data, "ready", "pine", "BAR_APPROX", true, "futures"), "");
  assert.throws(() => workbenchAccountInputs({ ...account, participationRate: 0 }, data));
});

test("BAR callbacks, account settings and changed account content invalidate frozen reports", () => {
  const draft = { ...defaultExecutionDraft(), fillRecalculation: true, account };
  const frozen = { host_settings: draft.hostSettings, fill_recalculation: true, ...workbenchAccountInputs(account, data) };
  assert.equal(executionSettingsChanged(frozen, draft, true, true), false);
  assert.equal(executionSettingsChanged(frozen, { ...draft, fillRecalculation: false }, true, true), true);
  assert.equal(executionSettingsChanged(frozen, { ...draft, account: { ...account, leverage: 20 } }, true, true), true);
  assert.equal(executionSettingsChanged(frozen, draft, true, false), true);
  assert.equal(executionSettingsChanged({ host_settings: draft.hostSettings, fill_recalculation: false },
    { ...defaultExecutionDraft(), fillRecalculation: true }, true), true);
  assert.equal(executionSettingsChanged({ host_settings: draft.hostSettings, account_model: "LINEAR_PERP_ONE_WAY_V1" },
    defaultExecutionDraft(), true), false);
});

test("account controls expose real input fields and an explicit missing-upload state", () => {
  const html = renderToStaticMarkup(<WorkbenchAccountSettings value={account} data={null} state="missing" inputKey={1}
    disabled={false} error="Select the account file again" onChange={() => {}} onFile={() => {}} />);
  assert.match(html, /type="file"/);
  assert.match(html, /HISTORICAL_REQUIRED/);
  assert.match(html, /LINEAR_PERP_ONE_WAY_V2/);
  assert.match(html, /role="alert"/);
  assert.match(html, /Select the account file again/);
});
