// Every application page loads this module. A top-level document becomes a
// shell: it owns the shared Python engine and shows the original pages in one
// same-origin frame, so moving between pages does not restart the engine.
// Inside that frame the module installs the transport and loads the desktop
// entry; that is the only change before the desktop code runs.
const base = new URL('./', document.baseURI)
const FRAME = 'candlescope-page'
const root = document.getElementById('root')
let sequence = 0
const callbacks = new Map()
const worker =
  typeof SharedWorker === 'function'
    ? new SharedWorker(new URL('engine/backend-worker.mjs', base), {
        type: 'module',
        name: 'candlescope-python',
      })
    : null
function startupFailure(message) {
  root.textContent = message + ' '
  const link = document.createElement('a')
  link.href = 'https://github.com/helenananaa/CandleScope/releases'
  link.target = '_top'
  link.textContent = '下载 CandleScope 桌面版'
  root.append(link)
}
if (!worker) {
  startupFailure('当前浏览器缺少 SharedWorker 支持。')
  throw Error('SharedWorker unavailable')
}
worker.port.onmessage = ({ data }) => callbacks.get(data.id)?.(data)
worker.port.start()

function request(kind, payload = {}, timeout = 90000) {
  const id = ++sequence
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      callbacks.delete(id)
      reject(Error('Python worker timed out'))
    }, timeout)
    callbacks.set(id, (result) => {
      callbacks.delete(id)
      clearTimeout(timer)
      if (result.kind === 'error') reject(Error(result.error))
      else resolve(result)
    })
    worker.port.postMessage({ id, kind, ...payload })
  })
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

function startShell() {
  const html = document.documentElement
  html.dataset.candlescopeShell = '1'
  root.hidden = true
  // Boot the engine while the frame loads. The frame waits for this instance.
  worker.port.postMessage({ id: ++sequence, kind: 'ready' })
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
  document.body.append(frame)

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
  navigator.serviceWorker.register(new URL('workspace-service.mjs', base), { scope: base.pathname }).catch(console.error)
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

async function startPage() {
  // A running engine answers within a frame or two; only a cold start shows text.
  // Before the page's styles load, the shell's last page colour shows through.
  const notice = setTimeout(() => {
    root.style.cssText = 'padding:12px 16px;color:#8b909a;font:13px/1.5 system-ui,sans-serif'
    root.textContent = '正在启动本机浏览器中的 CandleScope Python 引擎…'
  }, 400)
  forwardApplicationRequests()
  await navigator.serviceWorker.register(new URL('workspace-service.mjs', base), { scope: base.pathname })
  await navigator.serviceWorker.ready
  if (!navigator.serviceWorker.controller)
    await new Promise((resolve) => {
      navigator.serviceWorker.addEventListener('controllerchange', resolve, { once: true })
      if (navigator.serviceWorker.controller) resolve()
    })
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
  const ready = serviceVersion === 2 ? await request('ready', {}, 150000) : null
  if (ready?.transport !== 2) throw Error('网页版已更新，请关闭此站点的所有标签页后重新打开。')
  clearTimeout(notice)
  root.style.cssText = ''
  if (ready.instance) document.documentElement.dataset.engineInstance = ready.instance
  globalThis.WebSocket = AppSocket
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') void request('flush').catch(console.error)
  })
  window.addEventListener('pagehide', () => {
    for (const id of httpRequests) worker.port.postMessage({ id, kind: 'abort' })
    for (const socket of appSockets) socket.close(1000, 'Page closed')
    void request('flush').catch(console.error)
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
    startupFailure('浏览器后端启动失败：' + String(error))
    console.error(error)
  })
}
