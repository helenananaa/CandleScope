import { LOCALES as lazyTestLocales, loadLocaleCatalog } from "../../../i18n/registry.js";

test.before(async () => { await Promise.all(lazyTestLocales.map(loadLocaleCatalog)); });

import assert from "node:assert/strict";
import test from "node:test";
import { setLocale } from "../../../i18n/index.js";
import {
  liveModeLabel,
  permissionDecisionLabel,
  releaseChannelLabel,
  releaseChannelOrder,
  runtimeVerificationLabel,
  sandboxStatusLabel,
  trustModeLabel,
} from "../pluginLabels.js";

test("plugin platform codes are named, and an unknown code stays visible", () => {
  setLocale("zh-CN");
  assert.equal(liveModeLabel("armed"), "已启用");
  assert.equal(liveModeLabel("killed"), "已熔断");
  assert.equal(releaseChannelOrder(), "内部 → 本机试用 → 预览 → 稳定");
  assert.equal(trustModeLabel("trusted-local"), "本机信任");
  setLocale("en");
  assert.equal(liveModeLabel("disarmed"), "Off");
  assert.equal(releaseChannelLabel("opted-in-local"), "Local opt-in");
  assert.equal(permissionDecisionLabel("granted"), "Granted");
  assert.equal(runtimeVerificationLabel("revoked"), "Revoked");
  assert.equal(sandboxStatusLabel("windows-appcontainer"), "Windows app container sandbox");
  assert.equal(trustModeLabel("some-new-mode"), "some-new-mode");
  assert.equal(liveModeLabel(undefined), "—");
});
