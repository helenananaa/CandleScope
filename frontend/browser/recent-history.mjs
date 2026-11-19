// Cache the last successful REST page per supported market. One transaction orders
// overlapping tabs' reads and writes, so a slower older request cannot replace it.
let connection
function database() {
  connection ??= new Promise((resolve, reject) => {
    const request = indexedDB.open('candlescope-browser-market-v1', 1)
    request.onupgradeneeded = () => request.result.createObjectStore('recent')
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
  return connection
}

export async function recentHistory(key, update) {
  const db = await database()
  return new Promise((resolve, reject) => {
    const transaction = db.transaction('recent', update ? 'readwrite' : 'readonly')
    const store = transaction.objectStore('recent')
    const read = store.get(key)
    read.onsuccess = () => {
      if (update && (!read.result || read.result.started < update.started)) store.put(update, key)
    }
    transaction.oncomplete = () => resolve(read.result?.rows)
    transaction.onabort = () => reject(transaction.error)
  })
}
