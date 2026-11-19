// REST rows, pagination intent and end-of-history state survive a refresh.
// Row keys let simultaneous charts or tabs commit disjoint pages independently.
let connection
function database() {
  connection ??= new Promise((resolve, reject) => {
    const request = indexedDB.open('candlescope-browser-market-v1', 2)
    request.onupgradeneeded = () => {
      const db = request.result
      const bars = db.createObjectStore('bars')
      db.createObjectStore('progress')
      if (db.objectStoreNames.contains('recent')) {
        const cursor = request.transaction.objectStore('recent').openCursor()
        cursor.onsuccess = () => {
          const entry = cursor.result
          if (!entry) return
          for (const row of entry.value.rows) bars.put({ row, started: entry.value.started }, [entry.key, row[0]])
          entry.continue()
        }
      }
    }
    request.onblocked = () => reject(Error('Close older CandleScope tabs to upgrade history storage'))
    request.onsuccess = () => {
      request.result.onversionchange = () => { request.result.close(); connection = undefined }
      resolve(request.result)
    }
    request.onerror = () => { connection = undefined; reject(request.error) }
  })
  return connection
}

function done(tx) {
  return new Promise((resolve, reject) => {
    tx.oncomplete = resolve
    tx.onabort = () => reject(tx.error)
  })
}

export async function loadHistory(key) {
  const db = await database()
  const tx = db.transaction(['bars', 'progress'])
  const bars = tx.objectStore('bars').getAll(IDBKeyRange.bound([key, 0], [key, Number.MAX_SAFE_INTEGER]))
  const pending = tx.objectStore('progress').getAll(IDBKeyRange.bound([key, 'older'], [key, 'older', Number.MAX_SAFE_INTEGER]))
  const exhausted = tx.objectStore('progress').get([key, 'exhausted'])
  await done(tx)
  return { rows: bars.result.map(entry => entry.origin === 'stream' ? [...entry.row, 'stream'] : entry.row), pending: [...new Set(pending.result)], exhausted: exhausted.result }
}

export async function queueOlder(key, before) {
  const db = await database()
  const tx = db.transaction('progress', 'readwrite')
  tx.objectStore('progress').put(before, [key, 'older', before])
  await done(tx)
}

export async function commitPage(key, rows, started, before, origin = 'rest') {
  const db = await database()
  const tx = db.transaction(['bars', 'progress'], 'readwrite')
  const bars = tx.objectStore('bars')
  for (const row of rows) {
    const id = [key, row[0]]
    const read = bars.get(id)
    read.onsuccess = () => {
      const held = read.result
      if (held?.row.at(-1) && !row.at(-1)) return
      if (held?.row.at(-1) && held.origin !== 'stream' && origin === 'stream') return
      if (!held || started >= held.started || (!held.row.at(-1) && row.at(-1)) || (held.origin === 'stream' && origin === 'rest' && row.at(-1))) {
        bars.put({ row, started, origin }, id)
      }
    }
  }
  if (before != null) {
    const progress = tx.objectStore('progress')
    progress.delete([key, 'older', before])
    const pending = progress.get([key, 'older'])
    pending.onsuccess = () => { if (pending.result === before) progress.delete([key, 'older']) }
    if (!rows.length) progress.put(before, [key, 'exhausted'])
  }
  await done(tx)
}
