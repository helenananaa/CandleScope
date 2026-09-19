import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import * as refreshHelpers from '../src/features/plugins/pluginRefreshRuntime.ts';

// Execute the production hook with controlled hook storage and network promises.
// Effects are started explicitly so each test can schedule the poll/write race.
const source = fs.readFileSync(new URL('../src/features/plugins/usePluginPlatformRuntime.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
} }).outputText;
const catalog = revision => ({ platform: { registryRevision: revision }, plugins: [] });
const snapshot = revision => ({ registryRevision: revision, views: [], chartLayers: [] });
const status = mode => ({ available: true, mode, generation: 1 });
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
function harness(overrides = {}) {
  const slots = [];
  let cursor = 0;
  let effects = [];
  const timers = [];
  const api = {
    pluginManagementAvailable: () => false,
    fetchPluginCatalog: async () => catalog(1),
    fetchPluginUiSnapshot: async () => snapshot(1),
    fetchPluginLiveControlStatus: async () => status('disarmed'),
    invalidatePluginControlReads: () => {},
    setLiveControlMode: async mode => status(mode),
    killLiveControl: async () => status('killed'),
    revokeLiveAuthority: async () => status('revoked'),
    PluginPlatformApiError: class extends Error {},
    ...overrides,
  };
  const react = {
    useState(initial) {
      const i = cursor++;
      if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial;
      return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }];
    },
    useRef(initial) {
      const i = cursor++;
      if (!(i in slots)) slots[i] = { current: initial };
      return slots[i];
    },
    useMemo: fn => fn(),
    useCallback: fn => fn,
    useEffect: fn => { effects.push(fn); },
  };
  class Source { update() {} }
  const imports = {
    react,
    './pluginPlatformApi.js': api,
    './pluginMarkerSource.js': { PluginMarkerSource: Source },
    './pluginChartLayerSource.js': { PluginChartLayerSource: Source },
    './pluginRegistries.js': { buildPluginRegistries: () => ({ sidePanel: [], bottomPanel: [], settings: [] }) },
    './pluginRefreshRuntime.js': {
      ...refreshHelpers,
      createDeferredAbortableTask: () => ({ start() {}, stop() {} }),
      pluginCatalogNeedsUiPolling: value => value !== null,
      pluginCatalogNeedsChartContextSync: () => false,
      pluginLivePollIntervalMs: () => 2000,
    },
    '../../i18n/useLocale.js': { useLocale: () => 'en' },
    '../../i18n/index.js': { t: key => key },
  };
  const exports = {};
  vm.runInNewContext(compiled, {
    exports,
    require: name => {
      assert.ok(name in imports, `unmocked module ${name}`);
      return imports[name];
    },
    AbortController, Error, Promise,
    window: {
      setInterval: (fn, delay) => { timers.push({ fn, delay }); return timers.length; },
      clearInterval() {},
    },
  });
  function render() {
    cursor = 0;
    effects = [];
    return exports.usePluginPlatformRuntime({ exchange: 'test', interval: '1m', marketType: 'spot', symbol: 'BTC' });
  }
  return {
    api, render,
    startPolls() { timers.length = 0; effects.forEach(fn => fn()); return timers; },
  };
}

for (const [action, args, expected] of [
  ['setLiveControlMode', ['armed', 'test', false], 'armed'],
  ['killLiveControl', ['test'], 'killed'],
  ['revokeLiveAuthority', ['plugin', 'example.plugin', 'test'], 'revoked'],
]) {
  test(`a stale status poll cannot overwrite ${action}`, async () => {
    const h = harness();
    await h.render().actions.refresh();
    let runtime = h.render();
    const polls = h.startPolls();
    const slow = deferred();
    h.api.fetchPluginLiveControlStatus = () => slow.promise;
    polls.at(-1).fn();
    await runtime.actions[action](...args);
    slow.resolve(status('disarmed'));
    await flush();
    runtime = h.render();
    assert.equal(runtime.view.liveControl.mode, expected);
  });
}

test('revision skew retries both catalog and snapshot with fresh reads', async () => {
  let catalogReads = 0;
  let snapshotReads = 0;
  let invalidations = 0;
  const h = harness({
    fetchPluginCatalog: async () => catalog(++catalogReads === 1 ? 1 : 2),
    fetchPluginUiSnapshot: async () => { snapshotReads++; return snapshot(2); },
    invalidatePluginControlReads: () => { invalidations++; },
  });
  await h.render().actions.refresh();
  const runtime = h.render();
  assert.equal(runtime.view.catalog.platform.registryRevision, 2);
  assert.equal(runtime.view.snapshot.registryRevision, 2);
  assert.equal(catalogReads, 2);
  assert.equal(snapshotReads, 2);
  assert.ok(invalidations > 0);
});

test('an overlapping UI poll cannot discard a coordinated snapshot refresh', async () => {
  const h = harness();
  await h.render().actions.refresh();
  const runtime = h.render();
  const polls = h.startPolls();
  const nextCatalog = deferred();
  const nextSnapshot = deferred();
  h.api.fetchPluginCatalog = () => nextCatalog.promise;
  const pollSnapshot = deferred();
  let snapshotCalls = 0;
  h.api.fetchPluginUiSnapshot = () => ++snapshotCalls === 1 ? nextSnapshot.promise : pollSnapshot.promise;
  const refresh = runtime.actions.refresh();
  polls[1].fn();
  nextCatalog.resolve(catalog(2));
  nextSnapshot.resolve(snapshot(2));
  await refresh;
  pollSnapshot.resolve(snapshot(2));
  await flush();
  assert.equal(h.render().view.snapshot?.registryRevision, 2);
});

test('persistent revision skew stops after one retry and fails closed', async () => {
  let reads = 0;
  const h = harness({
    fetchPluginCatalog: async () => { reads++; return catalog(1); },
    fetchPluginUiSnapshot: async () => snapshot(2),
  });
  await assert.rejects(h.render().actions.refresh(), /catalog changed/);
  assert.equal(reads, 2);
  assert.equal(h.render().view.catalog, null);
  assert.equal(h.render().view.snapshot, null);
  h.api.fetchPluginCatalog = async () => catalog(2);
  await h.render().actions.refresh();
  assert.equal(h.render().view.snapshot.registryRevision, 2);
});
