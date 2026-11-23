// Every application page loads this module. A top-level document becomes a
// shell: it owns the shared Python engine and shows the original pages in one
// same-origin frame, so moving between pages does not restart the engine.
// Inside that frame the module installs the transport and loads the desktop
// entry; that is the only change before the desktop code runs. The page does
// not wait for the engine: its requests reach the engine when that has started.
const base = new URL('./', document.baseURI)
const FRAME = 'candlescope-page'
const UNCONTROLLED = 'candlescope.uncontrolled-reload'
const root = document.getElementById('root')
let sequence = 0
const callbacks = new Map()
// The build names a content-addressed engine folder (see host.config.mjs).
const engineScript = new URL((import.meta.env.VITE_ENGINE_DIR || 'engine/') + 'backend-worker.mjs', base)
document.documentElement.dataset.engineScript = engineScript.href
const worker =
  typeof SharedWorker === 'function'
    ? new SharedWorker(engineScript, { type: 'module', name: 'candlescope-python' })
    : null
// The shell's own messages come from the app's catalogs, in the language the
// person chose. Only failures load them in the shell; pages load them anyway.
let messages
function translator() {
  messages ??= Promise.all([
    import('../../src/i18n/index.js'),
    import('../../src/features/settings/chartAppearanceSettings.js'),
  ]).then(async ([i18n, settings]) => {
    await i18n.initializeLocale(settings.readPersistedLocale())
    return i18n.t
  })
  return messages
}
// The application owns #root once it has loaded, so this module's notices are
// elements of their own above it.
const NOTICE_FONT = 'font:13px/1.5 system-ui,sans-serif;white-space:pre-line;z-index:2147483647'
const FAILURE_STYLE = 'position:fixed;inset:0;padding:12px 16px;background:#0d0e10;color:#8b909a;' + NOTICE_FONT
// Centred above the application's status bar, clear of its side toolbars.
const STARTING_STYLE =
  'position:fixed;left:50%;bottom:44px;transform:translateX(-50%);padding:8px 14px;border-radius:6px;' +
  'pointer-events:none;text-align:center;background:rgba(22,24,28,.94);color:#c9cdd4;' +
  'box-shadow:0 2px 12px rgba(0,0,0,.35);' +
  NOTICE_FONT
function notice(role, style) {
  const element = document.createElement('div')
  element.setAttribute('role', role)
  element.style.cssText = style
  document.body.append(element)
  return element
}
async function startupFailure(key, values) {
  // Without its catalogs the app cannot run either; say so in English.
  const t = await translator().catch(() => (name, values) =>
    name === 'browser.desktop.download' ? 'Download the desktop app' : values?.reason ?? "CandleScope couldn't start."
  )
  root.dataset.startupFailure = key
  const failure = notice('alert', FAILURE_STYLE)
  failure.textContent = t(key, values) + ' '
  const link = document.createElement('a')
  link.href = 'https://github.com/helenananaa/CandleScope/releases'
  link.target = '_top'
  link.textContent = t('browser.desktop.download')
  failure.append(link)
}
if (!worker) {
  void startupFailure('browser.host.unsupported')
  throw Error('SharedWorker unavailable')
}
worker.port.onmessage = ({ data }) =>
  data.kind === 'notice' ? showStorageNotice(data.storage) : callbacks.get(data.id)?.(data)
worker.port.start()

const deadlines = new Map()
function request(kind, payload = {}, timeout = 90000) {
  const id = ++sequence
  return new Promise((resolve, reject) => {
    deadlines.set(
      id,
      setTimeout(() => {
        callbacks.delete(id)
        deadlines.delete(id)
        reject(Error('Python worker timed out'))
      }, timeout)
    )
    callbacks.set(id, (result) => {
      callbacks.delete(id)
      clearTimeout(deadlines.get(id))
      deadlines.delete(id)
      if (result.kind === 'error') reject(Error(result.error))
      else resolve(result)
    })
    worker.port.postMessage({ id, kind, ...payload })
  })
}

// The engine reports when another build's engine still owns the browser
// storage, and when saving to it fails. The page frame shows either.
let storageNotice = null
let storageBanner
let startingNotice
function showStorageNotice(notice) {
  storageNotice = notice ?? null
  if (notice?.state === 'waiting') {
    // Starting waits for the other tabs to close, however long that takes.
    for (const deadline of deadlines.values()) clearTimeout(deadline)
    deadlines.clear()
    startingNotice?.end()
  }
  if (window.top === window) return
  translator().then((t) => {
    const current = storageNotice
    if (!current) return storageBanner?.remove()
    if (!storageBanner) {
      storageBanner = document.createElement('div')
      storageBanner.setAttribute('role', 'alert')
      storageBanner.style.cssText =
        'position:fixed;left:12px;right:12px;bottom:12px;z-index:2147483647;padding:10px 14px;border-radius:6px;' +
        'background:#3a2a12;color:#f5d9a8;font:13px/1.5 system-ui,sans-serif;box-shadow:0 2px 12px rgba(0,0,0,.4)'
    }
    storageBanner.textContent =
      current.state === 'waiting'
        ? t('browser.host.storageWaiting')
        : t('browser.host.storageFailed', { reason: current.error })
    document.body.append(storageBanner)
  }, console.error)
}

// The service worker hands each application HTTP request to the document that
// issued it. Both the shell and the page answer through the shared engine.
const httpRequests = new Set()
function forwardApplicationRequests() {
  navigator.serviceWorker.addEventListener('message', ({ data, ports }) => {
    if (data?.type !== 'candlescope.api' || !ports[0]) return
    const id = ++sequence
    httpRequests.add(id)
    callbacks.set(id, () => {
      callbacks.delete(id)
      httpRequests.delete(id)
    })
    worker.port.postMessage({ ...data, kind: 'http', id, origin: location.origin }, [ports[0], data.body])
  })
}

const appSockets = new Set()
const nativeSocket = globalThis.WebSocket
class AppSocket extends EventTarget {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3
  readyState = 0
  bufferedAmount = 0
  protocol = ''
  extensions = ''
  binaryType = 'blob'
  constructor(value, protocols) {
    super()
    const url = new URL(value, location.href)
    if (url.host !== location.host || !url.pathname.startsWith('/api/v1/'))
      return new nativeSocket(value, protocols)
    this.url = url.href
    this.id = ++sequence
    appSockets.add(this)
    callbacks.set(this.id, (message) => {
      const event = message.event
      if (event?.type === 'websocket.accept') {
        if (this.readyState >= 2) return
        this.readyState = 1
        this.emit(new Event('open'))
      } else if (event?.type === 'websocket.send' && this.readyState === 1)
        this.emit(new MessageEvent('message', { data: event.text }))
      else if (event?.type === 'websocket.close' || message.kind === 'closed' || message.kind === 'error') {
        appSockets.delete(this)
        callbacks.delete(this.id)
        if (message.kind === 'error') this.emit(new Event('error'))
        this.readyState = 3
        this.emit(
          new CloseEvent('close', {
            code: event?.code ?? (message.kind === 'error' ? 1011 : 1000),
            reason: event?.reason ?? '',
          })
        )
      }
    })
    worker.port.postMessage({
      id: this.id,
      kind: 'open',
      path: url.pathname,
      query: url.search,
      origin: location.origin,
    })
  }
  emit(event) {
    this.dispatchEvent(event)
    this['on' + event.type]?.(event)
  }
  send(text) {
    if (this.readyState !== 1) throw new DOMException('Socket closed', 'InvalidStateError')
    worker.port.postMessage({
      id: this.id,
      kind: 'socket',
      event: { type: 'websocket.receive', text: String(text) },
    })
  }
  close(code = 1000, reason = '') {
    if (this.readyState >= 2) return
    this.readyState = 2
    worker.port.postMessage({
      id: this.id,
      kind: 'socket',
      event: { type: 'websocket.disconnect', code, reason },
    })
  }
}

// Later engine starts restore a memory snapshot of the imported backend. A
// shared worker cannot start workers, so the shell starts the one that makes
// it, once the first page has loaded its data. A visit that ends sooner
// leaves the snapshot to the next one.
function snapshotEngine() {
  const maker = new Worker(new URL('snapshot-worker.mjs', engineScript), { type: 'module', name: 'candlescope-snapshot' })
  const done = (error) => {
    maker.terminate()
    if (error) console.warn('Could not snapshot the Python engine', error)
  }
  maker.onmessage = ({ data }) => done(data.error)
  maker.onerror = (event) => done(event.message || 'worker error')
}

function startShell() {
  const html = document.documentElement
  html.dataset.candlescopeShell = '1'
  root.hidden = true
  // Ask the browser not to clear the site's data under storage pressure.
  navigator.storage?.persist?.().catch(() => {})
  // Boot the engine while the frame loads. The frame waits for this instance.
  request('ready', {}, 150000).then((ready) => {
    if (ready.snapshot === 'missing') setTimeout(snapshotEngine, 10000)
  }, console.error)
  const style = document.createElement('style')
  style.textContent =
    'html,body{margin:0;height:100%;overflow:hidden;background:#0d0e10}' +
    'iframe[name="' + FRAME + '"]{position:fixed;inset:0;width:100%;height:100%;border:0;display:block}'
  document.head.append(style)
  const frame = document.createElement('iframe')
  frame.name = FRAME
  frame.title = document.title
  frame.allow = 'fullscreen; clipboard-read; clipboard-write'
  frame.src = location.href
  // Load the page once the service worker is active, so that it controls the
  // page from its first request. Whether clients.claim() reaches a frame that
  // already exists differs by browser: Safari often leaves it uncontrolled.
  navigator.serviceWorker
    .register(new URL('workspace-service.mjs', base), { scope: base.pathname })
    .then(() => navigator.serviceWorker.ready)
    .then(
      () => document.body.append(frame),
      (error) => {
        console.error(error)
        void startupFailure('browser.host.startFailed', { reason: String(error) })
      }
    )

  // Keep the address bar, title and language in step with the page, so that
  // reloading or sharing the URL opens the page the visitor is looking at.
  let observer
  function sync() {
    let page
    try {
      page = frame.contentWindow
      if (page.location.origin !== location.origin) return
    } catch {
      return
    }
    const doc = page.document
    if (page.location.href !== location.href) history.replaceState(null, '', page.location.href)
    if (doc.title) document.title = frame.title = doc.title
    if (doc.documentElement.lang) html.lang = doc.documentElement.lang
    if (doc.body) {
      const background = getComputedStyle(doc.body).backgroundColor
      if (background && background !== 'rgba(0, 0, 0, 0)') document.body.style.background = background
    }
  }
  frame.addEventListener('load', () => {
    observer?.disconnect()
    sync()
    try {
      const doc = frame.contentDocument
      observer = new MutationObserver(sync)
      observer.observe(doc.head, { subtree: true, childList: true, characterData: true })
      observer.observe(doc.documentElement, { attributes: true, attributeFilter: ['lang', 'data-theme'] })
      frame.contentWindow.focus()
    } catch {
      // The frame shows another site; it has no document to follow.
    }
  })
  window.addEventListener('message', ({ source, data }) => {
    if (source === frame.contentWindow && data?.type === 'candlescope.location') sync()
  })
  forwardApplicationRequests()
}

// Same-document URL changes and links leaving the site belong to the shell.
function followShell() {
  const notify = () => window.parent.postMessage({ type: 'candlescope.location' }, location.origin)
  for (const name of ['pushState', 'replaceState']) {
    const original = history[name]
    history[name] = function (...args) {
      const result = original.apply(this, args)
      notify()
      return result
    }
  }
  window.addEventListener('popstate', notify)
  window.addEventListener('hashchange', notify)
  window.addEventListener('click', (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
      return
    const link = event.target instanceof Element ? event.target.closest('a[href]') : null
    if (!link || (link.target && link.target !== '_self') || link.hasAttribute('download')) return
    const target = new URL(link.href, location.href)
    if (target.origin === location.origin) return
    event.preventDefault()
    window.top.location.assign(target.href)
  })
}

// While the engine starts, a page that already shows says so. A running engine
// answers within a frame or two, and a returning visitor's starts in about two
// seconds; only a longer start, which a first visit's download is, shows text.
function showStarting() {
  let element
  const t = translator()
  const timers = [
    setTimeout(async () => {
      const text = await t
      if (!timers.length) return
      element = notice('status', STARTING_STYLE)
      element.textContent = text('browser.host.starting')
    }, 2500),
    setTimeout(async () => {
      const text = await t
      if (element) element.textContent = text('browser.host.starting') + '\n' + text('browser.host.firstStart')
    }, 8000),
  ]
  return {
    end() {
      for (const timer of timers.splice(0)) clearTimeout(timer)
      element?.remove()
      element = null
    },
  }
}

async function startPage() {
  forwardApplicationRequests()
  await navigator.serviceWorker.register(new URL('workspace-service.mjs', base), { scope: base.pathname })
  await navigator.serviceWorker.ready
  if (!navigator.serviceWorker.controller) {
    const controlled = await new Promise((resolve) => {
      navigator.serviceWorker.addEventListener('controllerchange', () => resolve(true), { once: true })
      if (navigator.serviceWorker.controller) resolve(true)
      setTimeout(() => resolve(false), 3000)
    })
    // A document that loaded before the worker activated may stay uncontrolled;
    // its reload is controlled. Reload once, then report the failure.
    if (!controlled) {
      if (sessionStorage.getItem(UNCONTROLLED) !== location.href) {
        sessionStorage.setItem(UNCONTROLLED, location.href)
        return location.reload()
      }
      throw Error('The service worker does not control this page')
    }
  }
  sessionStorage.removeItem(UNCONTROLLED)
  const channel = new MessageChannel()
  const serviceVersion = await new Promise((resolve) => {
    const timer = setTimeout(() => resolve(null), 5000)
    channel.port1.onmessage = ({ data }) => {
      clearTimeout(timer)
      resolve(data)
    }
    navigator.serviceWorker.controller.postMessage({ type: 'candlescope.transport' }, [channel.port2])
  })
  channel.port1.close()
  if (serviceVersion !== 2) return startupFailure('browser.host.updated')

  // The shell started the engine. The application loads meanwhile; what it
  // asks for waits in the engine's queue (see worker.mjs) and is answered when
  // the engine has started.
  let started = false
  startingNotice = showStarting()
  request('ready', {}, 150000).then(
    (ready) => {
      started = true
      startingNotice.end()
      if (ready.transport !== 2) return startupFailure('browser.host.updated')
      if (ready.instance) document.documentElement.dataset.engineInstance = ready.instance
      showStorageNotice(ready.storage)
    },
    (error) => {
      startingNotice.end()
      void startupFailure('browser.host.startFailed', { reason: error?.message || String(error) })
      console.error(error)
    }
  )
  globalThis.WebSocket = AppSocket
  // An engine that has not started has nothing to save.
  const flush = () => started && void request('flush').catch(console.error)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush()
  })
  window.addEventListener('pagehide', () => {
    for (const id of httpRequests) worker.port.postMessage({ id, kind: 'abort' })
    for (const socket of appSockets) socket.close(1000, 'Page closed')
    flush()
  })
  switch (document.documentElement.dataset.entry) {
    case 'replay':
      return import('../../src/replay-main.tsx')
    case 'strategy':
      return import('../../src/strategy-main.tsx')
    case 'local':
      return import('../../src/local-main.tsx')
    case 'backtest':
      return import('../../src/backtest-main.tsx')
    default:
      return import('../../src/main.tsx')
  }
}

if (window.top === window) startShell()
else {
  if (window.name === FRAME) followShell()
  startPage().catch((error) => {
    void startupFailure('browser.host.startFailed', { reason: String(error) })
    console.error(error)
  })
}
