// Check the engine's browser storage (store.mjs) against a built site, with
// the bundled Pyodide and the browser's IndexedDB. It saves a SQLite database
// larger than one IndexedDB value may be, saves small changes and file
// operations, reads everything back in a second interpreter, and migrates an
// IDBFS directory of earlier builds. It uses databases of its own and removes
// them. PLAYWRIGHT_MODULE and CHROME_PATH are as for acceptance.mjs.
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core')
const url = new URL(process.argv[2] || 'http://127.0.0.1:4178/')
const profile = await mkdtemp(join(tmpdir(), 'candlescope-storage-acceptance-'))
const context = await chromium.launchPersistentContext(profile, {
  headless: true,
  ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}),
})
try {
  const page = await context.newPage()
  // Any same-origin document will do; this one does not start the engine.
  await page.goto(new URL('storage-acceptance', url).href)
  const engine = await page.evaluate(async () => {
    const html = await (await fetch('./')).text()
    const entry = html.match(/src="([^"]+\.js)"/)[1]
    const script = await (await fetch(new URL(entry, location.href))).text()
    return new URL(script.match(/engine\/[0-9a-f]{16}\//)[0], location.href).href
  })
  const report = await page.evaluate(async (engine) => {
    const { loadPyodide } = await import(engine + 'pyodide.mjs')
    const { openStore } = await import(engine + 'store.mjs')
    const name = 'storage-acceptance-' + Date.now()
    const timed = async (task) => {
      const started = performance.now()
      const value = await task()
      return [value, Math.round(performance.now() - started)]
    }
    const tree = `
import hashlib, json, os
def tree(root):
    found = {}
    for path, dirs, files in os.walk(root):
        for name in dirs:
            found[os.path.join(path, name)] = 'dir'
        for name in files:
            with open(os.path.join(path, name), 'rb') as handle:
                found[os.path.join(path, name)] = hashlib.sha256(handle.read()).hexdigest()
    return json.dumps(found, sort_keys=True)
`
    const result = {}
    let py = await loadPyodide({ indexURL: engine })
    let store = await openStore(py, '/data', { name, legacy: '/no-earlier-storage' })
    py.runPython(`
import os, sqlite3
os.makedirs('/data/notes/old', exist_ok=True)
os.makedirs('/data/gone', exist_ok=True)
open('/data/notes/a.txt', 'w').write('first note')
open('/data/empty.txt', 'w').close()
open('/data/catalog.json', 'wb').write(os.urandom(200_000))
open('/data/settings.json', 'w').write('{"theme": "dark"}')
db = sqlite3.connect('/data/big.db')
db.execute('pragma journal_mode=wal')
db.execute('create table bars(id integer primary key, payload blob)')
db.execute('with recursive n(x) as (select 1 union all select x + 1 from n where x < 40000) '
           'insert into bars(payload) select randomblob(4000) from n')
db.commit()
db.close()
`)
    result.databaseBytes = py.FS.stat('/data/big.db').size
    ;[result.first, result.firstMs] = await timed(() => store.save())
    py.runPython(`
import sqlite3
db = sqlite3.connect('/data/big.db')
db.executemany('update bars set payload = randomblob(4000) where id = ?', [(i * 1999,) for i in range(1, 21)])
db.commit()
db.close()
`)
    ;[result.update, result.updateMs] = await timed(() => store.save())
    py.runPython(`
import os
os.rename('/data/notes/a.txt', '/data/notes/b.txt')
os.remove('/data/empty.txt')
os.rmdir('/data/gone')
with open('/data/catalog.json', 'r+b') as handle:
    handle.truncate(10)
    handle.seek(300_000)
    handle.write(b'tail')
open('/data/settings.tmp', 'w').write('{"theme": "light"}')
os.replace('/data/settings.tmp', '/data/settings.json')
os.makedirs('/data/new/deeper', exist_ok=True)
open('/data/new/deeper/c.bin', 'wb').write(bytes(range(256)) * 300)
`)
    ;[result.operations, result.operationsMs] = await timed(() => store.save())
    result.nothing = await store.save()
    const expected = py.runPython(tree + "tree('/data')")
    store.close()
    py = store = null

    py = await loadPyodide({ indexURL: engine })
    ;[store, result.loadMs] = await timed(() => openStore(py, '/data', { name, legacy: '/no-earlier-storage' }))
    result.matches = py.runPython(tree + "tree('/data')") === expected
    result.integrity = py.runPython(`
import sqlite3
db = sqlite3.connect('/data/big.db')
answer = db.execute('pragma integrity_check').fetchone()[0], db.execute('select count(*) from bars').fetchone()[0]
db.close()
answer`).toJs()
    result.catalog = py.runPython(`
data = open('/data/catalog.json', 'rb').read()
[len(data), data[10:300_000].count(0), data[-4:].decode()]`).toJs()
    store.close()
    py = store = null

    // A directory that an earlier build saved with IDBFS.
    const legacy = '/legacy-' + Date.now()
    py = await loadPyodide({ indexURL: engine })
    py.FS.mkdirTree(legacy)
    py.FS.mount(py.FS.filesystems.IDBFS, {}, legacy)
    py.runPython(`
import os
os.makedirs('${legacy}/library', exist_ok=True)
open('${legacy}/library/data.bin', 'wb').write(os.urandom(5_000_000))
open('${legacy}/settings.json', 'w').write('{"language": "en"}')
`)
    const before = py.runPython(tree + `tree('${legacy}')`)
    await new Promise((resolve, reject) => py.FS.syncfs(false, (error) => (error ? reject(error) : resolve())))
    // That build's engine has exited before the new one opens the storage.
    for (const database of Object.values(py.FS.filesystems.IDBFS.dbs)) database.close()
    py = null
    py = await loadPyodide({ indexURL: engine })
    store = await openStore(py, legacy, { name: name + '-migrated' })
    result.migrated = py.runPython(tree + `tree('${legacy}')`) === before
    store.close()
    await new Promise((resolve) => setTimeout(resolve, 500))
    result.legacyRemoved = !(await indexedDB.databases()).some((database) => database.name === legacy)
    for (const database of [name, name + '-migrated']) indexedDB.deleteDatabase(database)
    return result
  }, engine)
  console.log(JSON.stringify(report))
  assert.ok(report.databaseBytes > 140_000_000, 'the test database exceeds one IndexedDB value')
  assert.ok(report.first.bytes >= report.databaseBytes)
  assert.ok(report.update.bytes < 4_000_000, 'a small update writes only the changed chunks')
  assert.deepEqual(report.nothing, { chunks: 0, bytes: 0 })
  assert.equal(report.matches, true, 'every file reads back unchanged')
  assert.deepEqual(report.integrity, ['ok', 40000])
  assert.deepEqual(report.catalog, [300004, 299990, 'tail'])
  assert.equal(report.migrated, true)
  assert.equal(report.legacyRemoved, true)
  console.log(
    `Saved a ${(report.databaseBytes / 1e6).toFixed(0)} MB SQLite database in ${report.firstMs} ms; ` +
      `a 20-row update wrote ${(report.update.bytes / 1e3).toFixed(0)} KB in ${report.updateMs} ms; ` +
      `file operations wrote ${(report.operations.bytes / 1e3).toFixed(0)} KB.`
  )
  console.log(`A new interpreter read it back unchanged in ${report.loadMs} ms; SQLite integrity_check ok.`)
  console.log('An IDBFS directory of an earlier build moved to the new storage and the old database was removed.')
} finally {
  await context.close()
  await rm(profile, { recursive: true, force: true, maxRetries: 3 })
}
