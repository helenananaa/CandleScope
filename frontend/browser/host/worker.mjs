import { IMPORT_BACKEND, disableSnapshot, hasSnapshot, interpreter, loadBackend, readSnapshot } from './interpreter.mjs'

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

function filesystem(py, populate) {
  return new Promise((resolve, reject) =>
    py.FS.syncfs(populate, (error) => {
      if (!error) return resolve()
      const failure = new Error(
        error.message || error.name || 'Browser filesystem sync failed (errno ' + error.errno + ')'
      )
      failure.errno = error.errno
      reject(failure)
    })
  )
}
function persist(py) {
  const task = sync
    .catch(() => {})
    .then(async () => {
      try {
        await filesystem(py, false)
      } catch (error) {
        // IDBFS enumerates files before opening its transaction. SQLite may
        // remove a journal during that interval. Re-enumerate on WASI ENOENT.
        if (error.errno !== 44) throw error
        await filesystem(py, false)
      }
    })
  sync = task
  return task
}

async function start() {
  const [backend, snapshot] = await Promise.all([
    loadBackend(),
    snapshots
      ? readSnapshot().catch((error) => {
          console.warn('Ignoring the interpreter snapshot', error)
          return null
        })
      : null,
  ])
  let py
  if (snapshot?.disabled) snapshotState = 'disabled'
  else if (snapshot) {
    try {
      py = await interpreter(backend, { snapshot })
      boot = 'snapshot'
      snapshotState = 'restored'
    } catch (error) {
      console.warn('Could not restore the interpreter snapshot; importing the backend', error)
      snapshotState = 'disabled'
      await disableSnapshot().catch(() => {})
    }
  }
  py ??= await interpreter(backend, 'import')
  py.FS.mkdirTree('/store')
  py.FS.mount(py.FS.filesystems.IDBFS, {}, '/store')
  await filesystem(py, true)
  try {
    // The archive holds unpacked packages with bytecode for the modules that
    // starting the backend imports (see prepare_engine.mjs).
    await py.runPythonAsync((boot === 'snapshot' ? 'import browser_host\n' : IMPORT_BACKEND) + 'await browser_host.start()\n')
  } catch (error) {
    // A restored interpreter that cannot start is not restored again.
    if (boot === 'snapshot') await disableSnapshot().catch(() => {})
    throw error
  }
  // Background backfill may commit after its HTTP request has already returned.
  let flushing = false
  setInterval(async () => {
    if (flushing) return
    flushing = true
    try {
      await persist(py)
    } catch (error) {
      console.error(error)
    } finally {
      flushing = false
    }
  }, 2000)
  return { py, host: py.pyimport('browser_host') }
}
function attach(port) {
  const sessions = new Map()
  const send = (id, message) => port.postMessage({ id, ...message })
  const requests = new Map()
  port.onmessage = async ({ data, ports }) => {
    const { id, kind } = data
    const channel = ports[0]
    try {
      const { py, host } = await (runtime ??= start())
      if (kind === 'ready') return send(id, { kind: 'ready', transport: 2, instance, snapshot: snapshotState })
      if (kind === 'stats') {
        const snapshot = snapshotState === 'missing' && (await hasSnapshot()) ? 'stored' : snapshotState
        return send(id, { kind: 'stats', instance, boot, snapshot, ...JSON.parse(host.stats()) })
      }
      if (kind === 'abort') return requests.get(id)?.cancel()
      if (kind === 'http') {
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
          await persist(py)
          channel.postMessage(result)
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
        await persist(py)
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
