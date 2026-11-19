// The only change before loading the desktop entry is installing its transport.
const base = new URL('./', document.baseURI)
const root = document.getElementById('root')
root.textContent = '正在启动本机浏览器中的 CandleScope Python 引擎…'
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
async function start() {
  navigator.serviceWorker.addEventListener('message', async ({ data, ports }) => {
    if (data?.type !== 'candlescope.api' || !ports[0]) return
    try {
      ports[0].postMessage(await request('http', { ...data, origin: location.origin }))
    } catch (error) {
      ports[0].postMessage({ error: String(error) })
    } finally {
      ports[0].close()
    }
  })
  await navigator.serviceWorker.register(new URL('workspace-service.mjs', base), { scope: base.pathname })
  await navigator.serviceWorker.ready
  if (!navigator.serviceWorker.controller)
    await new Promise((resolve) => {
      navigator.serviceWorker.addEventListener('controllerchange', resolve, { once: true })
      if (navigator.serviceWorker.controller) resolve()
    })
  await request('ready', {}, 150000)
  globalThis.WebSocket = AppSocket
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') void request('flush').catch(console.error)
  })
  window.addEventListener('pagehide', () => {
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
start().catch((error) => {
  startupFailure('浏览器后端启动失败：' + String(error))
  console.error(error)
})
