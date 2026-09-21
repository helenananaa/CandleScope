import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
const compiled = ts.transpileModule(fs.readFileSync(new URL('../src/features/plugins/usePluginDetail.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
function harness() {
  const slots = []; let cursor = 0; let effect; let cleanup;
  const react = {
    useState(initial) { const slot = cursor++; if (!(slot in slots)) slots[slot] = initial; return [slots[slot], value => { slots[slot] = typeof value === 'function' ? value(slots[slot]) : value; }]; },
    useRef(initial) { const slot = cursor++; return slots[slot] ??= { current: initial }; },
    useCallback: fn => fn,
    useEffect: fn => { effect = fn; },
  };
  const exports = {}; vm.runInNewContext(compiled, { exports, require: name => { assert.equal(name, 'react'); return react; }, Error });
  const requests = [];
  const runtime = { view: { managementAvailable: true }, actions: { loadDetail(id) { const value = deferred(); requests.push({ id, ...value }); return value.promise; } } };
  return { runtime, requests, render(id) { cursor = 0; return exports.usePluginDetail(runtime, id); }, commit() { cleanup?.(); cleanup = effect(); }, unmount() { cleanup?.(); } };
}
test('switching plugins hides old detail immediately and rejects late responses from the old selection', async () => {
  const h = harness(); h.render('one'); h.commit();
  h.requests[0].resolve({ plugin: { id: 'one' } }); await flush();
  assert.equal(h.render('one').detail.plugin.id, 'one');
  assert.equal(h.render('two').detail, null); h.commit();
  const second = h.requests[1];
  const fresh = h.render('two').reload();
  h.requests[2].resolve({ plugin: { id: 'two' }, version: 'new' }); await fresh;
  second.resolve({ plugin: { id: 'two' }, version: 'stale' }); await flush();
  assert.equal(h.render('two').detail.version, 'new');
});
test('losing management access removes protected detail and invalidates an in-flight request', async () => {
  const h = harness(); h.render('one'); h.commit();
  h.runtime.view.managementAvailable = false;
  assert.equal(h.render('one').detail, null); h.commit();
  h.requests[0].resolve({ plugin: { id: 'one' } }); await flush();
  assert.equal(h.render('one').detail, null);
});
test('failed refresh keeps the last detail with an explicit error and supports retry', async () => {
  const h = harness(); h.render('one'); h.commit();
  h.requests[0].resolve({ plugin: { id: 'one' } }); await flush();
  const refresh = h.render('one').reload(); h.requests[1].reject(new Error('Disconnected')); await refresh;
  const failed = h.render('one'); assert.equal(failed.detail.plugin.id, 'one'); assert.equal(failed.error, 'Disconnected'); assert.equal(failed.loading, false);
  const retry = failed.reload(); h.requests[2].resolve({ plugin: { id: 'one' }, version: 'recovered' }); await retry;
  assert.equal(h.render('one').error, null); assert.equal(h.render('one').detail.version, 'recovered');
});

test('a completed mutation from an unmounted detail cannot invalidate the new selection', async () => {
  const h = harness(); const previous = h.render('one'); h.commit();
  h.render('two'); h.commit();
  await previous.reload();
  assert.equal(h.requests.length, 2);
  h.requests[1].resolve({ plugin: { id: 'two' } }); await flush();
  assert.equal(h.render('two').detail.plugin.id, 'two');
  h.unmount(); await h.render('two').reload(); assert.equal(h.requests.length, 2);
});
