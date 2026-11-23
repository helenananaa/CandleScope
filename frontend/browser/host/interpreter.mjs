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
// Cache Storage of the engine: its large files and its snapshot.
const ENGINE_CACHE = 'candlescope-engine'
// The engine folder is named by its contents, so its snapshot is too.
export const snapshotKey = new URL('interpreter-snapshot', here).href

// The engine's large files are kept in Cache Storage rather than left to the
// HTTP cache, which Safari did not use for what workers download: every start,
// and the snapshot worker's, downloaded all of them again. The folder is named
// by its contents, so a kept copy is never stale. Pyodide fetches its runtime,
// standard library and lock file with the global fetch, which therefore takes
// these four from the cache. The module scripts (about 1.3 MB) stay with the
// HTTP cache.
const KEPT_FILES = ['backend.zip', 'pyodide.asm.wasm', 'python_stdlib.zip', 'pyodide-lock.json'].map(
  (name) => new URL(name, here).href
)
const fileCounts = { kept: 0, downloaded: 0 }
export const engineFileStats = () => ({ ...fileCounts })
const networkFetch = globalThis.fetch.bind(globalThis)

// Entries of other engine builds can never be used here.
async function forgetOtherBuilds(cache) {
  for (const request of await cache.keys()) if (!request.url.startsWith(here.href)) await cache.delete(request)
}

async function engineFile(url) {
  let cache
  try {
    cache = await caches.open(ENGINE_CACHE)
    const kept = await cache.match(url)
    if (kept) {
      fileCounts.kept++
      return kept
    }
  } catch {
    cache = null // a private window may refuse Cache Storage
  }
  fileCounts.downloaded++
  const response = await networkFetch(url)
  // A host that answers a missing file with its HTML page must not leave that
  // page in place of the file.
  if (cache && response.ok && !response.headers.get('content-type')?.startsWith('text/html'))
    cache
      .put(url, response.clone())
      .then(() => forgetOtherBuilds(cache))
      .catch((error) => console.warn('Could not keep ' + url, error))
  return response
}

// A start that failed drops this build's kept files, so that a damaged copy
// cannot fail every later start.
export async function forgetEngineFiles() {
  const cache = await caches.open(ENGINE_CACHE)
  for (const url of KEPT_FILES) await cache.delete(url)
}

globalThis.fetch = (input, init) => {
  const url = typeof input === 'string' ? new URL(input, location.href).href : input instanceof URL ? input.href : null
  return url && KEPT_FILES.includes(url) && !init?.integrity && (init?.method ?? 'GET') === 'GET'
    ? engineFile(url)
    : networkFetch(input, init)
}
export const IMPORT_BACKEND = `
import glob, sys
sys.dont_write_bytecode = True
sys.path[:0] = ['/packages', '/repo', '/repo/backend', *glob.glob('/repo/packages/*/src')]
import browser_host
`

const decoder = new TextDecoder()
const damaged = () => Error('The Python backend archive is damaged')
const inflate = async (data) =>
  new Uint8Array(await new Response(new Blob([data]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).arrayBuffer())

// Call onEntry(name, data) for each entry of a zip archive as its bytes
// arrive. The entries' sizes are in their local headers (bundle.py writes no
// data descriptors), so no entry waits for the central directory at the end.
// The response is read to its end, so that the HTTP cache keeps all of it.
async function readArchive(response, onEntry) {
  const reader = response.body.getReader()
  let pending = new Uint8Array(0)
  async function take(length) {
    const out = new Uint8Array(length)
    for (let filled = 0; filled < length; ) {
      if (!pending.length) {
        const { done, value } = await reader.read()
        if (done) throw damaged()
        pending = value
      }
      const part = Math.min(length - filled, pending.length)
      out.set(pending.subarray(0, part), filled)
      pending = pending.subarray(part)
      filled += part
    }
    return out
  }
  for (;;) {
    const header = new DataView((await take(30)).buffer)
    if (header.getUint32(0, true) !== 0x04034b50) break
    const flags = header.getUint16(6, true)
    const method = header.getUint16(8, true)
    if (flags & 8 || (method !== 0 && method !== 8)) throw damaged()
    const name = decoder.decode(await take(header.getUint16(26, true)))
    await take(header.getUint16(28, true))
    const data = await take(header.getUint32(18, true))
    await onEntry(name, method === 8 ? await inflate(data) : data)
  }
  while (!(await reader.read()).done);
}

// The archive holds dynlibs.json, the C extensions that importing the backend
// loads, and a zstd stream of every other file, in that order (bundle.py). It
// is read as it arrives: the C extensions compile, and Python starts, while
// the stream downloads. Returns { libraries, files }: promises of the
// [path, bytes, compiled module] list in loading order, and of the stream.
export function loadBackend() {
  let found
  const libraries = new Promise((resolve, reject) => (found = { resolve, reject }))
  const files = (async () => {
    const response = await engineFile(new URL('backend.zip', here).href)
    if (!response.ok) throw Error('Python backend download failed')
    let wanted = null
    const compiled = new Map()
    let stream = null
    await readArchive(response, (name, data) => {
      if (name === 'dynlibs.json') wanted = JSON.parse(decoder.decode(data)).dynlibs
      else if (name === 'files.zst') stream = data
      else compiled.set('/' + name, WebAssembly.compile(data).then((module) => ['/' + name, data, module]))
      if (found && wanted?.every((path) => compiled.has(path))) {
        found.resolve(Promise.all(wanted.map((path) => compiled.get(path))))
        found = null
      }
    })
    if (!wanted || !stream) throw Error('The Python backend archive lacks ' + (wanted ? 'files.zst' : 'dynlibs.json'))
    const missing = wanted.find((path) => !compiled.has(path))
    if (missing) throw Error('The Python backend archive lacks ' + missing)
    return stream
  })()
  files.catch((error) => found?.reject(error))
  // Each start reports a failed download once, where it waits for it.
  libraries.catch(() => {})
  files.catch(() => {})
  return { libraries, files }
}

// Python's own zstd unpacks the stream: a 4-byte index length, the JSON index
// of [path, size] pairs, then the files' bytes. Only zstd's 8 MB window and
// one file at a time pass through the interpreter's memory, which a snapshot
// keeps. The frame's checksum rejects a damaged download.
const UNPACK_FILES = `
import json, os
from compression import zstd
made = set()
with zstd.ZstdFile('/tmp/backend.zst') as stream:
    size = int.from_bytes(stream.read(4), 'little')
    for path, length in json.loads(stream.read(size)):
        folder = path.rpartition('/')[0] or '/'
        if folder not in made:
            os.makedirs(folder, exist_ok=True)
            made.add(folder)
        data = stream.read(length)
        if len(data) != length:
            raise EOFError('The Python backend archive is damaged')
        with open(path, 'wb') as target:
            target.write(data)
    if stream.read(1):
        raise ValueError('The Python backend archive is damaged')
os.remove('/tmp/backend.zst')
`
function unpackFiles(py, files) {
  py.FS.writeFile('/tmp/backend.zst', files)
  const scope = py.toPy({})
  try {
    py.runPython(UNPACK_FILES, { globals: scope })
  } finally {
    scope.destroy()
  }
}

const libraryPaths = (module) => Object.keys(module.LDSO.loadedLibsByName).filter((name) => name !== '__main__')
export const openFiles = (py) => py.FS.streams.filter(Boolean).map((stream) => stream.path)

// libraries resolves when the C extensions have arrived and compiled. Pyodide
// downloads and compiles its runtime meanwhile; Emscripten runs the hooks
// below once the runtime is instantiated, and a run dependency holds Python's
// start until the C extensions are loaded. Nothing has allocated memory before
// them, as when they loaded at once, so their placement is the same in every
// start.
function moduleFactory(libraries, snapshot) {
  return async (settings) => {
    const arrived = libraries
    settings.preRun = [
      ...[].concat(settings.preRun ?? []),
      () => {
        settings.addRunDependency('candlescope-libraries')
        libraries.then((list) => {
          for (const [path, bytes, compiled] of list) {
            settings.FS.mkdirTree(path.slice(0, path.lastIndexOf('/')))
            settings.FS.writeFile(path, bytes)
            const exports = settings.loadWebAssemblyModule(
              compiled,
              { loadAsync: false, global: false, nodelete: true },
              path,
              {}
            )
            // Python's dlopen then finds the library already loaded.
            settings.newDSO(path, undefined, exports).global = false
          }
          settings.preloadedTable = settings.wasmTable.length
          libraries = null
          settings.removeRunDependency('candlescope-libraries')
        }, () => {})
      },
    ]
    // A failed download fails the start instead of holding it.
    const module = await Promise.race([createPyodideModule(settings), arrived.then(() => new Promise(() => {}))])
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

// backend is loadBackend()'s result. mode: 'import' starts an empty
// interpreter, 'snapshot' one whose memory can be saved, and { snapshot }
// restores a saved one.
export async function interpreter(backend, mode) {
  const snapshot = typeof mode === 'object' ? mode.snapshot : null
  const py = await loadPyodide({
    indexURL: here.href,
    createPyodideModule: moduleFactory(backend.libraries, snapshot),
    ...(snapshot
      ? { _loadSnapshot: snapshot.memory }
      : mode === 'snapshot'
        ? { _makeSnapshot: true, jsglobals: membrane(globalThis) }
        : {}),
  })
  // The restored memory is in place; do not keep a second copy for the session.
  if (snapshot) py._api.config._loadSnapshot = null
  unpackFiles(py, await backend.files)
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
  const response = await (await caches.open(ENGINE_CACHE)).match(snapshotKey)
  if (!response) return null
  const layout = JSON.parse(response.headers.get('x-candlescope-layout'))
  if (!layout) return { disabled: true }
  return { layout, memory: new Uint8Array(await response.arrayBuffer()) }
}
export async function hasSnapshot() {
  return Boolean(await (await caches.open(ENGINE_CACHE)).match(snapshotKey))
}
export async function storeSnapshot(memory, layout) {
  const cache = await caches.open(ENGINE_CACHE)
  await forgetOtherBuilds(cache)
  await cache.put(
    snapshotKey,
    new Response(memory, {
      headers: { 'content-type': 'application/octet-stream', 'x-candlescope-layout': JSON.stringify(layout) },
    })
  )
}
export async function disableSnapshot() {
  await (await caches.open(ENGINE_CACHE)).put(snapshotKey, new Response('', { headers: { 'x-candlescope-layout': 'null' } }))
}
