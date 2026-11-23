// Browser storage for the engine's data directory.
//
// While the engine runs, the data directory is in memory (MEMFS). This module
// keeps a copy in IndexedDB as 64 KiB chunks and writes only the chunks that
// changed. Emscripten's IDBFS, used before, stored every file as one value:
// it rewrote whole databases on each sync, and once a file outgrew the
// browser's value limit (about 127 MB in Chrome) it could not be saved again.
//
// Each save is one transaction, so the copy always matches one moment of the
// directory, as SQLite's journal and WAL recovery require.
const CHUNK = 64 * 1024
const tracked = Symbol('candlescope.store')

const result = (request) =>
  new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
const committed = (transaction) =>
  new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve()
    transaction.onerror = () => reject(transaction.error)
    transaction.onabort = () => reject(transaction.error ?? new DOMException('Storage transaction aborted', 'AbortError'))
  })
const chunkRange = (path, first) => IDBKeyRange.bound([path, first], [path, Infinity])

async function openDatabase(name) {
  const request = indexedDB.open(name, 1)
  request.onupgradeneeded = () => {
    request.result.createObjectStore('files')
    request.result.createObjectStore('chunks')
  }
  const db = await result(request)
  // Clearing site data deletes the database under a running engine; later
  // saves then fail and the pages say so.
  db.onversionchange = () => db.close()
  return db
}

// files: path -> { kind, mode, mtime, size, count }; chunks: [path, index] -> bytes
async function readSaved(db) {
  const transaction = db.transaction(['files', 'chunks'], 'readonly')
  const files = transaction.objectStore('files')
  const [paths, metas] = await Promise.all([result(files.getAllKeys()), result(files.getAll())])
  const entries = new Map(paths.map((path, index) => [path, metas[index]]))
  const contents = new Map()
  for (const [path, meta] of entries) if (meta.kind === 'file') contents.set(path, new Uint8Array(meta.size))
  await new Promise((resolve, reject) => {
    const cursor = transaction.objectStore('chunks').openCursor()
    cursor.onerror = () => reject(cursor.error)
    cursor.onsuccess = () => {
      const entry = cursor.result
      if (!entry) return resolve()
      const [path, index] = entry.key
      const target = contents.get(path)
      if (target && index * CHUNK < target.length) target.set(entry.value.subarray(0, target.length - index * CHUNK), index * CHUNK)
      entry.continue()
    }
  })
  return { entries, contents }
}

// Earlier builds kept the directory in an IDBFS database named after it.
async function readLegacy(name, isDir) {
  const names = await indexedDB.databases?.()
  if (names && !names.some((database) => database.name === name)) return null
  const db = await result(indexedDB.open(name))
  try {
    if (!db.objectStoreNames.contains('FILE_DATA')) {
      // Opening it without a list of databases created it.
      if (!names) indexedDB.deleteDatabase(name)
      return null
    }
    const store = db.transaction('FILE_DATA', 'readonly').objectStore('FILE_DATA')
    const [paths, values] = await Promise.all([result(store.getAllKeys()), result(store.getAll())])
    const entries = new Map()
    const contents = new Map()
    paths.forEach((path, index) => {
      const { mode, timestamp, contents: data } = values[index]
      const mtime = +timestamp || Date.now()
      if (isDir(mode)) entries.set(path, { kind: 'dir', mode, mtime })
      else {
        const bytes = data ? new Uint8Array(data) : new Uint8Array(0)
        entries.set(path, { kind: 'file', mode, mtime, size: bytes.length })
        contents.set(path, bytes)
      }
    })
    return { entries, contents }
  } finally {
    db.close()
  }
}
function deleteLegacy(name) {
  // Another tab of an earlier build may still hold it open; the browser
  // deletes it once that tab closes.
  const request = indexedDB.deleteDatabase(name)
  request.onerror = () => console.warn('Could not remove the previous browser storage', request.error)
}

// Record which chunks of each file under the mount change.
function trackWrites(FS) {
  const MEMFS = FS.filesystems.MEMFS
  if (MEMFS[tracked]) return MEMFS[tracked]
  const marks = new WeakMap()
  const mounts = new Set()
  const mark = (node, start, end) => {
    if (!mounts.has(node.mount) || end <= start) return
    let chunks = marks.get(node)
    if (!chunks) marks.set(node, (chunks = new Set()))
    for (let index = Math.floor(start / CHUNK), last = Math.ceil(end / CHUNK); index < last; index++) chunks.add(index)
  }
  const write = MEMFS.stream_ops.write
  function trackedWrite(stream, buffer, offset, length, position, canOwn) {
    const written = write.call(this, stream, buffer, offset, length, position, canOwn)
    mark(stream.node, position, position + written)
    return written
  }
  // File nodes share ops_table.file.stream, which copied write when MEMFS
  // created its first node; msync calls MEMFS.stream_ops.write.
  MEMFS.stream_ops.write = trackedWrite
  if (MEMFS.ops_table) MEMFS.ops_table.file.stream.write = trackedWrite
  const resize = MEMFS.resizeFileStorage
  MEMFS.resizeFileStorage = function (node, size) {
    const before = node.usedBytes
    resize.call(this, node, size)
    mark(node, Math.min(before, size), Math.max(before, size))
  }
  return (MEMFS[tracked] = { marks, mounts })
}

function files(FS, root) {
  const nodes = new Map()
  const visit = (path, node) => {
    if (FS.isFile(node.mode)) nodes.set(path, node)
    else if (FS.isDir(node.mode)) {
      if (path !== root) nodes.set(path, node)
      for (const [name, child] of Object.entries(node.contents)) visit(path + '/' + name, child)
    }
  }
  visit(root, FS.lookupPath(root).node)
  return nodes
}

export async function openStore(py, mountpoint = '/store', { name = 'candlescope-store', legacy = mountpoint } = {}) {
  const FS = py.FS
  const { marks, mounts } = trackWrites(FS)
  FS.mkdirTree(mountpoint)
  FS.mount(FS.filesystems.MEMFS, {}, mountpoint)
  mounts.add(FS.lookupPath(mountpoint).node.mount)
  const db = await openDatabase(name)
  let saved = await readSaved(db)
  let migrating = !saved.entries.size && (await readLegacy(legacy, (mode) => FS.isDir(mode)))
  if (migrating) saved = migrating

  // What the database holds: path -> meta, and node -> { path, size } for
  // the file each saved path was last written from.
  const known = new Map()
  const written = new WeakMap()
  for (const [path, meta] of [...saved.entries].sort(([a], [b]) => a.length - b.length)) {
    if (meta.kind === 'dir') FS.mkdirTree(path, meta.mode & 4095)
    else {
      FS.mkdirTree(path.slice(0, path.lastIndexOf('/')))
      FS.writeFile(path, saved.contents.get(path), { canOwn: true })
      FS.chmod(path, meta.mode)
    }
    const node = FS.lookupPath(path).node
    node.atime = node.mtime = node.ctime = meta.mtime
    if (migrating) continue
    known.set(path, meta)
    if (meta.kind === 'file') {
      marks.delete(node)
      written.set(node, { path, size: meta.size })
    }
  }
  saved = null
  migrating = Boolean(migrating)

  async function save() {
    const nodes = files(FS, mountpoint)
    const puts = []
    const removed = []
    const applied = []
    const taken = []
    for (const [path, node] of nodes) {
      const previous = known.get(path)
      if (FS.isDir(node.mode)) {
        // Directory times follow their children; record creation and mode.
        if (previous?.kind !== 'dir' || previous.mode !== node.mode) {
          const meta = { kind: 'dir', mode: node.mode, mtime: node.mtime }
          puts.push(['files', path, meta])
          applied.push([path, meta])
        }
        continue
      }
      const size = node.usedBytes
      const count = Math.ceil(size / CHUNK)
      const state = written.get(node)
      const changed = marks.get(node)
      let chunks
      if (!state || state.path !== path || previous?.kind !== 'file') {
        chunks = Array.from({ length: count }, (_, index) => index)
        if (previous) removed.push([path, count, previous.kind === 'dir'])
      } else {
        chunks = new Set(changed)
        if (size > state.size) for (let index = Math.floor(state.size / CHUNK); index < count; index++) chunks.add(index)
        if (previous.count > count) removed.push([path, count, false])
        if (!chunks.size && previous.size === size && previous.mode === node.mode && previous.mtime === node.mtime) continue
      }
      marks.delete(node)
      if (changed) taken.push([node, changed])
      const meta = { kind: 'file', mode: node.mode, mtime: node.mtime, size, count }
      puts.push(['files', path, meta])
      for (const index of chunks)
        if (index < count)
          puts.push(['chunks', [path, index], node.contents.slice(index * CHUNK, Math.min(size, (index + 1) * CHUNK))])
      applied.push([path, meta, node])
    }
    for (const [path, meta] of known) if (!nodes.has(path)) removed.push([path, 0, meta.kind === 'dir'])
    if (!puts.length && !removed.length) return { chunks: 0, bytes: 0 }

    let bytes = 0
    try {
      const transaction = db.transaction(['files', 'chunks'], 'readwrite')
      const fileStore = transaction.objectStore('files')
      const chunkStore = transaction.objectStore('chunks')
      for (const [path, first, directory] of removed) {
        if (first === 0 || directory) fileStore.delete(path)
        chunkStore.delete(chunkRange(path, first))
      }
      for (const [store, key, value] of puts) {
        if (store === 'chunks') bytes += value.length
        ;(store === 'files' ? fileStore : chunkStore).put(value, key)
      }
      await committed(transaction)
    } catch (error) {
      // Keep the changes for the next save.
      for (const [node, changed] of taken) {
        let chunks = marks.get(node)
        if (!chunks) marks.set(node, (chunks = new Set()))
        for (const index of changed) chunks.add(index)
      }
      throw error
    }
    for (const [path, first] of removed) if (first === 0) known.delete(path)
    for (const [path, meta, node] of applied) {
      known.set(path, meta)
      if (node) written.set(node, { path, size: meta.size })
    }
    if (migrating) {
      migrating = false
      deleteLegacy(legacy)
    }
    return { chunks: puts.length - applied.length, bytes }
  }

  // The earlier copy stays until the new one is complete; the engine's saves
  // retry a migration that could not be saved now.
  if (migrating) await save().catch((error) => console.warn('Could not save the migrated browser storage yet', error))
  return { save, close: () => db.close() }
}
