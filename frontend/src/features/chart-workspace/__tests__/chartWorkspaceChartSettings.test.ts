import assert from "node:assert/strict";
import test from "node:test";
import { DEFAULT_SETTINGS, normalizeSettings, type ChartSettings } from "../../settings/chartAppearanceSettings.js";
import {
  applicationSettingsPatch,
  buildAppearanceTargets,
  cellAppearanceOverride,
  cellsWithAppearanceOverride,
  nextCellChartSettings,
  sharedCellAppearanceTheme,
  withCellAppearanceOverride,
  withoutCellAppearanceOverrides,
} from "../chartWorkspaceChartSettings.js";
import { applyLinkedChartSettingsUpdate, cloneChartLinkSettings } from "../chartWorkspaceLinkModel.js";
import { createDefaultChartWorkspace, normalizeChartWorkspaceWithDiagnostics } from "../chartWorkspaceStorage.js";
import { DEFAULT_CHART_LINK_GROUP_ID, DEFAULT_CHART_LINK_GROUP_SETTINGS } from "../chartWorkspaceTypes.js";

test("legacy workspaces inherit saved global colors without manufacturing appearance overrides", () => {
  for (const schemaVersion of [7, 8]) {
    const original = { ...createDefaultChartWorkspace(), schemaVersion };
    const result = normalizeChartWorkspaceWithDiagnostics(original);
    assert.equal(result.usedFallback, false);
    const cell = result.document.cells['cell-1']!;
    assert.equal(Object.hasOwn(cell.chartSettings, 'theme'), false);
    assert.equal(Object.hasOwn(cell.chartSettings, 'upColor'), false);
    const global = { ...DEFAULT_SETTINGS, theme: 'light' as const, upColor: '#123456' };
    assert.equal({ ...global, ...cell.chartSettings }.upColor, '#123456');
    assert.equal({ ...global, ...cell.chartSettings }.theme, 'light');
  }
});

test("application preference edits do not freeze inherited chart appearance", () => {
  const cell = createDefaultChartWorkspace().cells['cell-1']!.chartSettings;
  const current = { ...DEFAULT_SETTINGS, ...cell, upColor: '#123456' };
  const next = { ...current, locale: 'en' as const, frontendCacheBudgetBytes: 128 * 1024 * 1024 };
  assert.deepEqual(nextCellChartSettings(cell, current, next), cell);
  assert.deepEqual(applicationSettingsPatch(current, next), {
    locale: 'en', frontendCacheBudgetBytes: 128 * 1024 * 1024,
  });
  const local = { ...current, upColor: '#abcdef', theme: 'light' as const, chartType: 'line' as const };
  const changed = nextCellChartSettings(cell, current, local);
  assert.equal(changed.upColor, '#abcdef');
  assert.equal(changed.theme, 'light');
  assert.equal(changed.downColor, undefined);
  assert.deepEqual(applicationSettingsPatch(current, normalizeSettings(local)), {});
});

test("unlinked chart appearance persists and leaves all sibling settings untouched", () => {
  const document = createDefaultChartWorkspace();
  const source = document.cells['cell-1']!;
  const next = applyLinkedChartSettingsUpdate(document, source.id, {
    ...source.chartSettings, theme: 'custom', customBg: '#123456', upColor: '#abcdef', downColor: '#fedcba',
  });
  assert.equal(next.cells['cell-2'], document.cells['cell-2']);
  assert.equal(next.cells['cell-3'], document.cells['cell-3']);
  const restored = normalizeChartWorkspaceWithDiagnostics(JSON.parse(JSON.stringify(next)));
  assert.equal(restored.usedFallback, false);
  assert.deepEqual(restored.document.cells['cell-1']!.chartSettings, next.cells['cell-1']!.chartSettings);
  assert.equal(restored.document.linkGroups[DEFAULT_CHART_LINK_GROUP_ID]!.peerPolicy.chartStyle, false);
});

test("style edits follow only selected directed links and preserve unrelated configuration", () => {
  const document = createDefaultChartWorkspace();
  document.linkGroups[DEFAULT_CHART_LINK_GROUP_ID]!.peerPolicy.chartStyle = true;
  document.linkGroups.child = { id: 'child', name: 'Child', color: '#123456',
    parentId: DEFAULT_CHART_LINK_GROUP_ID,
    peerPolicy: { ...cloneChartLinkSettings(DEFAULT_CHART_LINK_GROUP_SETTINGS), chartStyle: true },
    receiveFromParent: { ...cloneChartLinkSettings(DEFAULT_CHART_LINK_GROUP_SETTINGS), chartStyle: true } };
  document.cells['cell-3']!.linkGroupId = 'child';
  document.cells['cell-4']!.linkGroupId = null;
  document.cells['cell-2']!.chartSettings.downColor = '#112233';
  const source = document.cells['cell-1']!;
  const next = applyLinkedChartSettingsUpdate(document, source.id, { ...source.chartSettings, upColor: '#abcdef' });
  for (const id of ['cell-1', 'cell-2', 'cell-3']) assert.equal(next.cells[id]!.chartSettings.upColor, '#abcdef');
  assert.equal(next.cells['cell-4'], document.cells['cell-4']);
  assert.equal(next.cells['cell-2']!.chartSettings.downColor, '#112233');
  for (const id of Object.keys(document.cells)) {
    assert.equal(next.cells[id]!.session, document.cells[id]!.session);
    assert.equal(next.cells[id]!.indicators, document.cells[id]!.indicators);
    assert.equal(next.cells[id]!.strategyAttachment, document.cells[id]!.strategyAttachment);
  }
  const fromChild = applyLinkedChartSettingsUpdate(next, 'cell-3', { ...next.cells['cell-3']!.chartSettings, theme: 'light' });
  assert.equal(fromChild.cells['cell-1'], next.cells['cell-1']);
  assert.equal(fromChild.cells['cell-2'], next.cells['cell-2']);
  assert.equal(applyLinkedChartSettingsUpdate(fromChild, 'cell-3', fromChild.cells['cell-3']!.chartSettings), fromChild);
  document.linkGroups.child.receiveFromParent.chartStyle = false;
  const blocked = applyLinkedChartSettingsUpdate(document, source.id, { ...source.chartSettings, upColor: '#abcdef' });
  assert.equal(blocked.cells['cell-3'], document.cells['cell-3']);
});


test("a chart's own appearance can be read, replaced and cleared without touching other settings", () => {
  const cell = { ...createDefaultChartWorkspace().cells['cell-1']!.chartSettings, theme: 'custom' as const, customBg: '#f4efe2', upColor: '#00ff00' };
  assert.deepEqual(cellAppearanceOverride(cell), { theme: 'custom', customBg: '#f4efe2', upColor: '#00ff00' });
  const light = withCellAppearanceOverride(cell, { theme: 'light' });
  assert.deepEqual(cellAppearanceOverride(light), { theme: 'light' });
  assert.equal(light.chartType, cell.chartType);
  const following = withCellAppearanceOverride(cell, null);
  assert.deepEqual(cellAppearanceOverride(following), {});
  assert.equal(Object.hasOwn(following, 'theme'), false);
});

test("Settings opened from a chart sends app edits to the app and own appearance to the chart", () => {
  const cell = createDefaultChartWorkspace().cells['cell-1']!.chartSettings;
  let application: ChartSettings = { ...DEFAULT_SETTINGS, theme: 'dark' };
  let chart = cell;
  const targets = () => buildAppearanceTargets({
    application,
    setApplication: (update) => { application = typeof update === 'function' ? update(application) : update; },
    cell: chart,
    setCell: (next) => { chart = next; },
  });
  targets().application.update({ theme: 'light' });
  assert.equal(application.theme, 'light');
  assert.equal(Object.hasOwn(chart, 'theme'), false, "the app theme never writes the chart");
  targets().chart.set({ theme: 'custom', customBg: '#102030' });
  assert.deepEqual(targets().chart.override, { theme: 'custom', customBg: '#102030' });
  targets().application.update({ theme: 'dark' });
  assert.equal({ ...application, ...chart }.customBg, '#102030', "the app theme does not override the chart's own appearance");
  targets().chart.set(null);
  assert.deepEqual(targets().chart.override, {});
});

test("returning a style-linked chart to the app theme clears its linked peers too", () => {
  const document = createDefaultChartWorkspace();
  document.linkGroups[DEFAULT_CHART_LINK_GROUP_ID]!.peerPolicy.chartStyle = true;
  const source = document.cells['cell-1']!;
  const own = applyLinkedChartSettingsUpdate(document, source.id, withCellAppearanceOverride(source.chartSettings, { theme: 'light' }));
  assert.equal(own.cells['cell-2']!.chartSettings.theme, 'light');
  const reset = applyLinkedChartSettingsUpdate(own, source.id, withCellAppearanceOverride(own.cells['cell-1']!.chartSettings, null));
  for (const id of ['cell-1', 'cell-2']) assert.equal(Object.hasOwn(reset.cells[id]!.chartSettings, 'theme'), false);
});

test("workspace appearance overrides can be counted, reset together, and recognised as one shared theme", () => {
  const base = createDefaultChartWorkspace();
  const cell = base.cells["cell-1"]!;
  const document = {
    ...base,
    cells: {
      "cell-1": { ...cell, chartSettings: { ...cell.chartSettings, theme: "light" as const } },
      "cell-2": { ...cell, id: "cell-2", chartSettings: { ...cell.chartSettings, theme: "light" as const } },
      "cell-3": { ...cell, id: "cell-3", chartSettings: { ...cell.chartSettings } },
    },
  };
  assert.deepEqual(cellsWithAppearanceOverride(document, ["cell-1", "cell-2", "cell-3"]), ["cell-1", "cell-2"]);
  // A chart that follows the app means the layout does not share one override.
  assert.equal(sharedCellAppearanceTheme(document, ["cell-1", "cell-2", "cell-3"]), null);
  assert.equal(sharedCellAppearanceTheme(document, ["cell-1", "cell-2"]), "light");
  const custom = { ...document, cells: { ...document.cells, "cell-2": { ...document.cells["cell-2"], chartSettings: { ...cell.chartSettings, theme: "custom" as const, customBg: "#123456" } } } };
  assert.equal(sharedCellAppearanceTheme(custom, ["cell-1", "cell-2"]), null);
  const reset = withoutCellAppearanceOverrides(document, ["cell-1", "cell-2", "cell-3"]);
  assert.deepEqual(cellsWithAppearanceOverride(reset, ["cell-1", "cell-2", "cell-3"]), []);
  assert.equal(Object.hasOwn(reset.cells["cell-1"]!.chartSettings, "theme"), false);
  assert.equal(withoutCellAppearanceOverrides(reset, ["cell-1"]), reset, "nothing to reset keeps the same document");
});
