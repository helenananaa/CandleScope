// Venue catalogs for the engine's start.
//
// Before its first stream or history request the backend reads the venue's
// instrument catalog, 7 MB for Binance spot, and each of a start's readers
// asks for it again. The engine therefore starts loading the catalog of the
// opening market here, while Python itself is still starting, hands that one
// copy to every reader of the start, and keeps it in Cache Storage. A later
// start reads the stored copy at once and replaces it in the background.
//
// browser_io.py passes the backend's catalog requests to readCatalog(). An
// empty answer sends the request to the venue as before, so that the backend
// sees the venue's own status and headers when a catalog cannot be loaded.

const CACHE = 'candlescope-catalog'
// What the backend requests for the opening market: browser_host.py warms
// Binance spot, and browser_io.py's public_url() gives this address.
export const OPENING_CATALOGS = ['https://data-api.binance.vision/api/v3/exchangeInfo?showPermissionSets=false']
const STORED_MAX_AGE = 24 * 3600e3 // an older stored copy is not used
const REFRESH_AGE = 3600e3 // an older stored copy is replaced once the page has started
const REFRESH_DELAY = 15e3
// One copy answers the readers of a start, for this long from its first reader.
const SHARE = 60e3
const UNREAD = 600e3
// Every reader of a start waits for its one download, so a download that
// receives nothing for this long is given up: the readers then ask the venue
// themselves, with the backend's own time limits and retries. A slow download
// that keeps receiving continues.
const STALL = 15e3

// url -> { copy: Promise<Uint8Array | undefined> | null, until: number | null }.
// until is null before the backend's first read. An entry stays after its copy
// is released: a start uses the stored copy once, then asks the venue.
const entries = new Map()
// openingDownloads counts the downloads of OPENING_CATALOGS among all downloads.
const counts = { reads: 0, stored: 0, downloads: 0, openingDownloads: 0, failures: 0 }
export const catalogStats = () => ({ ...counts })

async function stored(url) {
  try {
    const response = await (await caches.open(CACHE)).match(url)
    const at = Number(response?.headers.get('x-candlescope-stored'))
    if (!response || !(Date.now() - at < STORED_MAX_AGE)) return null
    return { at, bytes: new Uint8Array(await response.arrayBuffer()) }
  } catch {
    return null // a private window may refuse Cache Storage
  }
}

async function download(url) {
  counts.downloads++
  if (OPENING_CATALOGS.includes(url)) counts.openingDownloads++
  const controller = new AbortController()
  let timer
  const waiting = () => {
    clearTimeout(timer)
    timer = setTimeout(() => controller.abort(Error(`No catalog data for ${STALL / 1000} s`)), STALL)
  }
  let bytes
  try {
    waiting()
    const response = await fetch(url, {
      credentials: 'omit',
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    })
    if (!response.ok) throw Error('HTTP ' + response.status)
    const reader = response.body.getReader()
    const parts = []
    for (;;) {
      waiting()
      const { done, value } = await reader.read()
      if (done) break
      parts.push(value)
    }
    bytes = new Uint8Array(await new Blob(parts).arrayBuffer())
  } finally {
    clearTimeout(timer)
  }
  const copy = new Response(bytes, {
    headers: { 'content-type': 'application/json', 'x-candlescope-stored': String(Date.now()) },
  })
  Promise.resolve()
    .then(() => caches.open(CACHE))
    .then((cache) => cache.put(url, copy))
    .catch(() => {})
  return bytes
}

async function open(url) {
  const copy = await stored(url)
  if (!copy) return download(url)
  counts.stored++
  if (Date.now() - copy.at > REFRESH_AGE) setTimeout(() => download(url).catch(() => {}), REFRESH_DELAY)
  return copy.bytes
}

function current(url) {
  const known = entries.get(url)
  if (known?.copy && (known.until === null || Date.now() < known.until)) return known
  const entry = { until: null }
  entry.copy = (known ? download(url) : open(url)).catch((error) => {
    counts.failures++
    console.warn('Could not load the catalog ' + url, error)
  })
  entries.set(url, entry)
  return entry
}

export function prefetchCatalogs() {
  for (const url of OPENING_CATALOGS) {
    const entry = current(url)
    // An engine that never reads it starts over.
    setTimeout(() => entry.until === null && entries.get(url) === entry && entries.delete(url), UNREAD)
  }
}

export function readCatalog(url) {
  counts.reads++
  const entry = current(url)
  const copy = entry.copy
  if (entry.until === null) {
    entry.until = Date.now() + SHARE
    setTimeout(() => (entry.copy = null), SHARE)
  }
  return copy
}

// The backend found its catalog out of date: its next read asks the venue.
export function forgetCatalogs() {
  for (const entry of entries.values()) entry.until = 0
}
