import { loadPyodide } from './pyodide.mjs'

let runtime
// Pages report this to show that moving between them reused one engine.
const instance = crypto.randomUUID()
let nextSocket = 0
let sync = Promise.resolve()
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
async function boot() {
  const py = await loadPyodide({ indexURL: new URL('./', import.meta.url).href })
  const bundle = await fetch(new URL('./backend.zip', import.meta.url))
  if (!bundle.ok) throw Error('Python backend download failed')
  py.unpackArchive(await bundle.arrayBuffer(), 'zip', { extractDir: '/' })
  py.FS.mkdirTree('/store')
  py.FS.mount(py.FS.filesystems.IDBFS, {}, '/store')
  await filesystem(py, true)
  // The archive holds unpacked packages with bytecode for the modules that
  // starting the backend imports (see prepare_engine.mjs).
  await py.runPythonAsync(`
import glob, sys
sys.dont_write_bytecode = True
sys.path[:0] = ['/packages', '/repo', '/repo/backend', *glob.glob('/repo/packages/*/src')]
import browser_host
await browser_host.start()
`)
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
      const { py, host } = await (runtime ??= boot())
      if (kind === 'ready') return send(id, { kind: 'ready', transport: 2, instance })
      if (kind === 'stats') return send(id, { kind: 'stats', instance, ...JSON.parse(host.stats()) })
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
