// Import the backend in an interpreter of its own and keep a memory snapshot
// of it, so that later engine starts restore it instead (see interpreter.mjs).
// The shell starts this worker when the running engine has no snapshot. The
// engine itself never runs in snapshot mode, where every read of the global
// scope goes through Pyodide's path-recording proxy.
import {
  IMPORT_BACKEND,
  hasSnapshot,
  interpreter,
  loadBackend,
  openFiles,
  snapshotKey,
  snapshotLayout,
  storeSnapshot,
} from './interpreter.mjs'

async function run() {
  // One tab makes the snapshot; the others find it, or find the lock taken.
  return navigator.locks.request(snapshotKey, { ifAvailable: true }, async (lock) => {
    if (!lock || (await hasSnapshot())) return 'skipped'
    const backend = await loadBackend()
    const py = await interpreter(backend, 'snapshot')
    const filesBefore = openFiles(py)
    await py.runPythonAsync(IMPORT_BACKEND)
    // A restored interpreter has none of these files open. importlib.metadata
    // caches the zip lookups that keep the standard library archive open;
    // without them it reopens the archive when asked. snapshotLayout refuses
    // any other file still open.
    py.runPython(`
import gc, importlib.metadata
importlib.metadata.FastPath.__new__.cache_clear()
gc.collect()
`)
    const layout = snapshotLayout(py, backend.libraries, filesBefore)
    await storeSnapshot(py.makeMemorySnapshot(), layout)
    return 'stored'
  })
}
run().then(
  (result) => postMessage({ result }),
  (error) => postMessage({ error: String(error?.stack || error) })
)
