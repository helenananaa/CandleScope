import { catalogStats, forgetCatalogs, prefetchCatalogs, readCatalog } from './catalog.mjs'
import { IMPORT_BACKEND, disableSnapshot, hasSnapshot, interpreter, loadBackend, readSnapshot } from './interpreter.mjs'
import { openStore } from './store.mjs'

// The backend's first requests wait for the opening market's catalog. Load it
// while the interpreter starts (see catalog.mjs); browser_io.py reads it here.
// Parsing it keeps the interpreter busy for about a second, and the backend
// asks while it starts: hand it over once the page has its first candles, or
// has had time to ask, so that a returning visitor sees the stored ones first.
let servePage
const pageServed = new Promise((resolve) => (servePage = resolve))
globalThis.candlescopeCatalog = {
  read: (url) => pageServed.then(() => readCatalog(url)),
  forget: forgetCatalogs,
}
prefetchCatalogs()

let runtime
// Pages report this to show that moving between them reused one engine.
const instance = crypto.randomUUID()
let nextSocket = 0
let sync = Promise.resolve()
// After the first start, the engine restores a memory snapshot of the imported
// backend instead of importing it (see interpreter.mjs and the shell).
const snapshots = typeof caches !== 'undefined'
let boot = 'import'
let snapshotState = snapshots ? 'missing' : 'unsupported'

// Pages show the storage state: { state: 'waiting' } while another build's
// engine owns the data directory, { state: 'failed', error } after a save
// failed, and null otherwise.
let storageNotice = null
const ports = new Set()
function notify(notice) {
  if (JSON.stringify(notice) === JSON.stringify(storageNotice)) return
  storageNotice = notice
  for (const port of ports) port.postMessage({ kind: 'notice', storage: notice })
}

// One engine at a time owns the data directory. Tabs of another build run
// another shared worker, which waits here until this one's tabs have closed.
async function lockStorage() {
  if (!navigator.locks) return
  const forever = new Promise(() => {})
  const acquired = await new Promise((resolve, reject) =>
    navigator.locks
      .request('candlescope-store', { ifAvailable: true }, (lock) => {
        resolve(Boolean(lock))
        return lock && forever
      })
      .catch(reject)
  )
  if (acquired) return
  notify({ state: 'waiting' })
  await new Promise((resolve, reject) =>
    navigator.locks
      .request('candlescope-store', () => {
        resolve()
        return forever
      })
      .catch(reject)
  )
  notify(null)
}

// A failed save keeps serving: the changes stay in memory, the pages say so,
// and the next save retries them.
function persist(store) {
  const task = sync.then(async () => {
    try {
      await store.save()
      if (storageNotice?.state === 'failed') notify(null)
    } catch (error) {
      console.error('Could not save the data directory', error)
      notify({ state: 'failed', error: String(error?.message || error) })
    }
  })
  sync = task
  return task
}

async function start() {
  // The interpreter downloads its runtime while the engine archive arrives
  // (see interpreter.mjs).
  const backend = loadBackend()
  const [snapshot] = await Promise.all([
    snapshots
      ? readSnapshot().catch((error) => {
          console.warn('Ignoring the interpreter snapshot', error)
          return null
        })
      : null,
    lockStorage(),
  ])
  let py
  if (snapshot?.disabled) snapshotState = 'disabled'
  else if (snapshot) {
    try {
      py = await interpreter(backend, { snapshot })
      boot = 'snapshot'
      snapshotState = 'restored'
    } catch (error) {
      // A failed download fails this start; it says nothing about the snapshot.
      await Promise.all([backend.libraries, backend.files])
      console.warn('Could not restore the interpreter snapshot; importing the backend', error)
      snapshotState = 'disabled'
      await disableSnapshot().catch(() => {})
    }
  }
  py ??= await interpreter(backend, 'import')
  const store = await openStore(py, '/store')
  // Starting does not wait for the catalog; should that change, do not hold it.
  const unheld = setTimeout(servePage, 10000)
  try {
    // The archive holds unpacked packages with bytecode for the modules that
    // starting the backend imports (see prepare_engine.mjs).
    await py.runPythonAsync((boot === 'snapshot' ? 'import browser_host\n' : IMPORT_BACKEND) + 'await browser_host.start()\n')
  } catch (error) {
    // A restored interpreter that cannot start is not restored again.
    if (boot === 'snapshot') await disableSnapshot().catch(() => {})
    throw error
  }
  clearTimeout(unheld)
  setTimeout(servePage, 1500)
  // Background backfill may commit after its HTTP request has already returned.
  let flushing = false
  setInterval(async () => {
    if (flushing) return
    flushing = true
    await persist(store)
    flushing = false
  }, 2000)
  return { store, host: py.pyimport('browser_host') }
}
function attach(port) {
  ports.add(port)
  if (storageNotice) port.postMessage({ kind: 'notice', storage: storageNotice })
  const sessions = new Map()
  const send = (id, message) => port.postMessage({ id, ...message })
  const requests = new Map()
  port.onmessage = async ({ data, ports }) => {
    const { id, kind } = data
    const channel = ports[0]
    try {
      const { store, host } = await (runtime ??= start())
      if (kind === 'ready')
        return send(id, { kind: 'ready', transport: 2, instance, snapshot: snapshotState, storage: storageNotice })
      if (kind === 'stats') {
        const snapshot = snapshotState === 'missing' && (await hasSnapshot()) ? 'stored' : snapshotState
        return send(id, { kind: 'stats', instance, boot, snapshot, catalog: catalogStats(), ...JSON.parse(host.stats()) })
      }
      if (kind === 'abort') return requests.get(id)?.cancel()
      if (kind === 'http') {
        // The request waited for the engine to start; its time limit begins now.
        if (data.accepts) channel.postMessage({ type: 'accepted' })
        const { body, ...metadata } = data
        const task = host.http_task(JSON.stringify(metadata), new Uint8Array(body), (value) =>
          channel.postMessage(JSON.parse(value))
        )
        requests.set(id, task)
        channel.onmessage = ({ data }) => {
          if (data.type === 'abort') task.cancel()
        }
        try {
          const result = JSON.parse(await task)
          await persist(store)
          channel.postMessage(result)
          if (data.path.startsWith('/api/v1/klines/')) servePage()
        } finally {
          requests.delete(id)
          task.destroy()
        }
        return
      }
      if (kind === 'open') {
        const key = ++nextSocket
        sessions.set(id, key)
        host.open_socket(key)
        try {
          await host.websocket(key, JSON.stringify(data), (value) =>
            send(id, { kind: 'socket', event: JSON.parse(value) })
          )
        } finally {
          sessions.delete(id)
          send(id, { kind: 'closed' })
        }
      } else if (kind === 'socket' && sessions.has(id))
        host.ws_event(sessions.get(id), JSON.stringify(data.event))
      else if (kind === 'flush') {
        await persist(store)
        send(id, { kind: 'ready' })
      }
    } catch (error) {
      console.error(error)
      if (channel) channel.postMessage({ error: String(error) })
      else send(id, { kind: 'error', error: String(error) })
    } finally {
      if (channel) {
        channel.close()
        send(id, { kind: 'complete' })
      }
    }
  }
  // The shell keeps this worker alive across pages. A page that disappears
  // without its pagehide messages must not leave its sockets or requests open.
  port.addEventListener('close', () => {
    ports.delete(port)
    for (const task of requests.values()) task.cancel()
    if (!sessions.size) return
    void runtime?.then(({ host }) => {
      for (const key of sessions.values())
        host.ws_event(key, JSON.stringify({ type: 'websocket.disconnect', code: 1001, reason: 'Page closed' }))
    })
  })
  port.start()
}
self.onconnect = ({ ports }) => attach(ports[0])
