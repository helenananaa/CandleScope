// Starting the Python interpreter that runs the backend, shared by the engine
// (worker.mjs) and the worker that snapshots it (snapshot-worker.mjs).
//
// The first start imports the backend. A separate interpreter then imports it
// again and saves a memory snapshot, which later starts restore instead of
// importing. Pyodide's snapshot holds only memory, so this module also keeps
// the backend's C extensions where the snapshot expects them:
//
// - They load before the interpreter starts, in the order importing loads
//   them (dynlibs.json, from prepare_engine.mjs). Their memory and function
//   table slots then never depend on anything Python allocated.
// - The table entries added later (dlsym results) and the dlopen handles that
//   Python holds are recorded with the snapshot and put back on restore.
import createPyodideModule from './pyodide.asm.mjs'
import { loadPyodide } from './pyodide.mjs'

const here = new URL('./', import.meta.url)
export const SNAPSHOT_CACHE = 'candlescope-engine'
// The engine folder is named by its contents, so its snapshot is too.
export const snapshotKey = new URL('interpreter-snapshot', here).href
export const IMPORT_BACKEND = `
import glob, sys
sys.dont_write_bytecode = True
sys.path[:0] = ['/packages', '/repo', '/repo/backend', *glob.glob('/repo/packages/*/src')]
import browser_host
`

// Read named entries of the engine archive before Python exists.
async function archiveEntries(archive, names) {
  const view = new DataView(archive.buffer, archive.byteOffset, archive.byteLength)
  let end = archive.length - 22
  while (end >= 0 && view.getUint32(end, true) !== 0x06054b50) end--
  if (end < 0) throw Error('The Python backend archive is damaged')
  const wanted = new Set(names)
  const decoder = new TextDecoder()
  const entries = {}
  let offset = view.getUint32(end + 16, true)
  for (let index = view.getUint16(end + 10, true); index > 0; index--) {
    const method = view.getUint16(offset + 10, true)
    const size = view.getUint32(offset + 20, true)
    const nameLength = view.getUint16(offset + 28, true)
    const header = view.getUint32(offset + 42, true)
    const name = decoder.decode(archive.subarray(offset + 46, offset + 46 + nameLength))
    offset += 46 + nameLength + view.getUint16(offset + 30, true) + view.getUint16(offset + 32, true)
    if (!wanted.has(name)) continue
    const start = header + 30 + view.getUint16(header + 26, true) + view.getUint16(header + 28, true)
    const data = archive.subarray(start, start + size)
    entries[name] =
      method === 0
        ? data
        : new Uint8Array(
            await new Response(new Blob([data]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).arrayBuffer()
          )
  }
  for (const name of wanted) if (!entries[name]) throw Error('The Python backend archive lacks ' + name)
  return entries
}

export async function loadBackend() {
  const response = await fetch(new URL('backend.zip', here))
  if (!response.ok) throw Error('Python backend download failed')
  const archive = new Uint8Array(await response.arrayBuffer())
  const { dynlibs } = JSON.parse(new TextDecoder().decode((await archiveEntries(archive, ['dynlibs.json']))['dynlibs.json']))
  const files = await archiveEntries(archive, dynlibs.map((path) => path.slice(1)))
  return { archive, libraries: dynlibs.map((path) => [path, files[path.slice(1)]]) }
}

const libraryPaths = (module) => Object.keys(module.LDSO.loadedLibsByName).filter((name) => name !== '__main__')
export const openFiles = (py) => py.FS.streams.filter(Boolean).map((stream) => stream.path)

function moduleFactory(libraries, snapshot) {
  return async (settings) => {
    settings.preRun = [
      ...[].concat(settings.preRun ?? []),
      () => {
        for (const [path, bytes] of libraries) {
          settings.FS.mkdirTree(path.slice(0, path.lastIndexOf('/')))
          settings.FS.writeFile(path, bytes)
          const exports = settings.loadWebAssemblyModule(
            bytes,
            { loadAsync: false, global: false, nodelete: true },
            path,
            {}
          )
          // Python's dlopen then finds the library already loaded.
          settings.newDSO(path, undefined, exports).global = false
        }
        settings.preloadedTable = settings.wasmTable.length
        libraries = null
      },
    ]
    const module = await createPyodideModule(settings)
    if (snapshot) {
      // This build defines its memory in the module and ignores INITIAL_MEMORY.
      module.growMemory(snapshot.memory.length)
      restoreLayout(module, snapshot.layout)
    }
    // Pyodide keeps this factory for the session; it keeps none of the bytes.
    snapshot = null
    return module
  }
}

// Snapshot mode wraps the global scope in a proxy that records the path to
// each object Python reads, and passes that proxy as the receiver of the read.
// Browser accessors such as crossOriginIsolated or location reject it, and
// packages read them while importing. Below that proxy, this membrane gives
// every read and call its real object.
function membrane(root) {
  const targets = new WeakMap()
  const proxies = new WeakMap()
  const unwrap = (value) => targets.get(value) ?? value
  const handler = {
    get(target, name) {
      const value = Reflect.get(target, name)
      const own = Reflect.getOwnPropertyDescriptor(target, name)
      // A proxy must report fixed data properties unchanged.
      return own && !own.configurable && own.writable === false ? value : wrap(value)
    },
    set: (target, name, value) => Reflect.set(target, name, unwrap(value)),
    apply: (target, self, args) => Reflect.apply(target, unwrap(self), args.map(unwrap)),
    construct: (target, args) => Reflect.construct(target, args.map(unwrap)),
  }
  function wrap(value) {
    if (value === null || (typeof value !== 'object' && typeof value !== 'function')) return value
    let proxy = proxies.get(value)
    if (!proxy) {
      proxy = new Proxy(value, handler)
      proxies.set(value, proxy)
      targets.set(proxy, value)
    }
    return proxy
  }
  return wrap(root)
}

// mode: 'import' starts an empty interpreter, 'snapshot' one whose memory can
// be saved, and { snapshot } restores a saved one.
export async function interpreter({ archive, libraries }, mode) {
  const snapshot = typeof mode === 'object' ? mode.snapshot : null
  const py = await loadPyodide({
    indexURL: here.href,
    createPyodideModule: moduleFactory(libraries, snapshot),
    ...(snapshot
      ? { _loadSnapshot: snapshot.memory }
      : mode === 'snapshot'
        ? { _makeSnapshot: true, jsglobals: membrane(globalThis) }
        : {}),
  })
  // The restored memory is in place; do not keep a second copy for the session.
  if (snapshot) py._api.config._loadSnapshot = null
  py.unpackArchive(archive, 'zip', { extractDir: '/' })
  return py
}

// What restoring needs beyond memory.
export function snapshotLayout(py, libraries, filesBefore) {
  const module = py._module
  const paths = libraries.map(([path]) => path)
  const loaded = libraryPaths(module)
  if (loaded.join('\n') !== paths.join('\n'))
    throw Error('Importing the backend loaded C extensions outside the prepared set: ' + loaded.join(', '))
  const opened = openFiles(py).filter((path) => !filesBefore.includes(path))
  if (opened.length) throw Error('Files stayed open while importing the backend: ' + opened.join(', '))
  const owners = new Map()
  paths.forEach((path, library) => {
    for (const [name, value] of Object.entries(module.LDSO.loadedLibsByName[path].exports))
      if (typeof value === 'function' && !owners.has(value)) owners.set(value, [library, name])
  })
  for (const [name, value] of Object.entries(module))
    if (typeof value === 'function' && !owners.has(value)) owners.set(value, [-1, name])
  const table = []
  for (let index = module.preloadedTable; index < module.wasmTable.length; index++) {
    const entry = module.wasmTable.get(index)
    const owner = entry === null ? null : owners.get(entry)
    if (owner === undefined) throw Error('Unidentified function table entry ' + index)
    table.push(owner)
  }
  const handles = Object.entries(module.LDSO.loadedLibsByHandle)
    .filter(([handle]) => Number(handle))
    .map(([handle, dso]) => [Number(handle), paths.indexOf(dso.name)])
  return { libraries: paths, preloadedTable: module.preloadedTable, table, handles }
}

function restoreLayout(module, layout) {
  const paths = libraryPaths(module)
  if (paths.join('\n') !== layout.libraries.join('\n') || module.preloadedTable !== layout.preloadedTable)
    throw Error('The prepared C extensions differ from the snapshot')
  const exports = paths.map((path) => module.LDSO.loadedLibsByName[path].exports)
  layout.table.forEach((owner, offset) => {
    const index = layout.preloadedTable + offset
    const entry = owner === null ? null : owner[0] < 0 ? module[owner[1]] : exports[owner[0]][owner[1]]
    if (owner && typeof entry !== 'function') throw Error('Missing function for table entry ' + index)
    if (index >= module.wasmTable.length) module.wasmTable.grow(index + 1 - module.wasmTable.length)
    if (module.wasmTable.get(index) !== entry) module.setWasmTableEntry(index, entry)
  })
  for (const [handle, library] of layout.handles)
    module.LDSO.loadedLibsByHandle[handle] = module.LDSO.loadedLibsByName[paths[library]]
}

// null: none yet; { disabled }: this build could not restore one.
export async function readSnapshot() {
  const response = await (await caches.open(SNAPSHOT_CACHE)).match(snapshotKey)
  if (!response) return null
  const layout = JSON.parse(response.headers.get('x-candlescope-layout'))
  if (!layout) return { disabled: true }
  return { layout, memory: new Uint8Array(await response.arrayBuffer()) }
}
export async function hasSnapshot() {
  return Boolean(await (await caches.open(SNAPSHOT_CACHE)).match(snapshotKey))
}
export async function storeSnapshot(memory, layout) {
  const cache = await caches.open(SNAPSHOT_CACHE)
  // Snapshots of other engine builds can never be restored here.
  for (const request of await cache.keys()) if (request.url !== snapshotKey) await cache.delete(request)
  await cache.put(
    snapshotKey,
    new Response(memory, {
      headers: { 'content-type': 'application/octet-stream', 'x-candlescope-layout': JSON.stringify(layout) },
    })
  )
}
export async function disableSnapshot() {
  await (await caches.open(SNAPSHOT_CACHE)).put(snapshotKey, new Response('', { headers: { 'x-candlescope-layout': 'null' } }))
}
