import { loadPyodide } from './pyodide.mjs'

let runtime
let nextSocket = 0
let sync = Promise.resolve()
function filesystem(py, populate) {
  return new Promise((resolve, reject) =>
    py.FS.syncfs(populate, (error) => (error ? reject(error) : resolve()))
  )
}
function persist(py) {
  const task = sync.catch(() => {}).then(() => filesystem(py, false))
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
  await py.runPythonAsync(`
import glob, sys, os, zipfile
sys.dont_write_bytecode = True
os.makedirs('/packages', exist_ok=True)
for name in glob.glob('/wheels/*.whl'):
    with zipfile.ZipFile(name) as archive:
        archive.extractall('/packages')
    os.unlink(name)
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
  port.onmessage = async ({ data }) => {
    const { id, kind } = data
    try {
      const { py, host } = await (runtime ??= boot())
      if (kind === 'ready') return send(id, { kind: 'ready' })
      if (kind === 'http') {
        const response = JSON.parse(await host.http(JSON.stringify(data)))
        await persist(py)
        return send(id, { kind: 'http', ...response })
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
      send(id, { kind: 'error', error: String(error) })
    }
  }
  port.start()
}
self.onconnect = ({ ports }) => attach(ports[0])
