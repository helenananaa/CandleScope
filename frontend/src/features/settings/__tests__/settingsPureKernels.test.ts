import assert from "node:assert/strict";
import test from "node:test";

import { SETTINGS_ACTION_TYPES } from "../settingsActionTypes.js";
import { buildSettingsPanelViewModel } from "../settingsPanelViewModel.js";
import { SETTINGS_CATEGORIES, resolveSettingsTab } from "../settingsTabRegistry.js";
import { proxyConfigChanged, type ProxyConfig } from "../proxySettingsRuntime.js";
import type {
  SettingsRuntimeActions,
  SettingsRuntimeView,
} from "../settingsTypes.js";
import { partialMock } from "../../../test/testHelpers.js";

test("settings registry owns the complete ordered category contract", () => {
  assert.deepEqual(
    SETTINGS_CATEGORIES.map((category) => category.key),
    ["appearance", "network", "exchanges", "data", "plugins", "ai", "about"],
  );
  assert.equal(resolveSettingsTab("missing"), SETTINGS_CATEGORIES[0]);
});

test("every settings category has its own icon", () => {
  const icons = SETTINGS_CATEGORIES.map((category) => category.icon);
  assert.equal(new Set(icons).size, icons.length);
});

test("proxy edits count as unsaved until they match what the backend saved", () => {
  const saved: ProxyConfig = { mode: "custom", customProxy: "http://127.0.0.1:7890", routes: [], strategy: "failover" };
  assert.equal(proxyConfigChanged(null, saved), false, "nothing loaded yet");
  assert.equal(proxyConfigChanged(saved, { ...saved }), false);
  assert.equal(proxyConfigChanged(saved, { ...saved, customProxy: " http://127.0.0.1:7890 " }), false, "surrounding spaces");
  assert.equal(proxyConfigChanged(saved, { ...saved, mode: "none" }), true);
  assert.equal(proxyConfigChanged(saved, { ...saved, customProxy: "socks5://127.0.0.1:1080" }), true);
  assert.equal(proxyConfigChanged(saved, { ...saved, strategy: "balanced" }), true);
  assert.equal(proxyConfigChanged(saved, { ...saved, routes: [{ id: "a", name: "", url: "", egress_group: "shared", enabled: true, exchanges: [], max_concurrency: 4 }] }), true);
});

test("settings action descriptors distinguish local and backend behavior", () => {
  assert.equal(SETTINGS_ACTION_TYPES.chartAppearance.type, "local_only");
  assert.equal(SETTINGS_ACTION_TYPES.proxySettings.type, "backend_endpoint");
});

test("settings panel view model merges only the matching view and action groups", () => {
  const onProxySave = () => {};
  const onRefresh = async () => {};
  const panel = buildSettingsPanelViewModel({
    view: partialMock<SettingsRuntimeView>({
      appearance: partialMock<SettingsRuntimeView["appearance"]>({}),
      proxy: partialMock<SettingsRuntimeView["proxy"]>({ proxyMode: "none" }),
      exchanges: partialMock<SettingsRuntimeView["exchanges"]>({ currentExchange: "binance" }),
      cacheLimits: partialMock<SettingsRuntimeView["cacheLimits"]>({ showAdvanced: true }),
      cacheDiagnostics: partialMock<SettingsRuntimeView["cacheDiagnostics"]>({}),
      maintenance: partialMock<SettingsRuntimeView["maintenance"]>({ gapScanLoading: false }),
    }),
    actions: partialMock<SettingsRuntimeActions>({
      proxy: partialMock<SettingsRuntimeActions["proxy"]>({ onProxySave }),
      exchanges: partialMock<SettingsRuntimeActions["exchanges"]>({ onRefreshExchanges: onRefresh }),
      cacheLimits: partialMock<SettingsRuntimeActions["cacheLimits"]>({}),
      cacheDiagnostics: partialMock<SettingsRuntimeActions["cacheDiagnostics"]>({ onRefresh }),
      maintenance: partialMock<SettingsRuntimeActions["maintenance"]>({}),
    }),
  });

  assert.equal(panel.network.proxyMode, "none");
  assert.equal(panel.network.onProxySave, onProxySave);
  assert.equal(panel.exchanges.currentExchange, "binance");
  assert.equal(panel.exchanges.onRefreshExchanges, onRefresh);
  assert.equal(panel.data.cacheLimits.showAdvanced, true);
  assert.equal(panel.data.cacheDiagnostics.onRefresh, onRefresh);
  assert.equal(panel.data.maintenance.gapScanLoading, false);
  assert.deepEqual(panel.about, {});
});
