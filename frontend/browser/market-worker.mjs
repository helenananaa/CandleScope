import { recentHistory } from './recent-history.mjs'
import { loadPyodide } from './pyodide.mjs'

const windows = new Map()
const minutes = { '1m': 1, '5m': 5, '15m': 15, '30m': 30, '1h': 60, '4h': 240, '1d': 1440 }
const sampleSymbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
const sampleIntervals = ['5m', '15m', '1h', '1d']
const runtime = (async () => {
  const py = await loadPyodide({ indexURL: new URL('./', import.meta.url).href })
  await Promise.all(['kline_quality.py', 'semantics.py', 'market_window.py'].map(async name => {
    const response = await fetch(new URL(name, import.meta.url))
    if (!response.ok) throw Error(name)
    py.FS.writeFile(name, await response.text())
  }))
  return py.runPython('from market_window import MarketWindow\nMarketWindow')
})()
runtime.catch(() => {}) // Each subscriber receives the initialization failure.

function publish(feed, message) {
  if (windows.get(feed.id) === feed) self.postMessage({ id: feed.id, ...message })
}

function merge(feed, rows, origin, reset = false) {
  if (feed.abort.signal.aborted || !feed.model || !rows.length) return
  if (reset) feed.model.clear()
  const result = JSON.parse(feed.model.merge(JSON.stringify(rows), origin))
  feed.first = result.first
  feed.count = result.count
  publish(feed, { type: 'bars', reset, origin, ...result })
}

async function getPage(feed, older = false) {
  if (Date.now() < (feed.cooldown ?? 0)) throw Error('Rate limited')
  const url = new URL('https://data-api.binance.vision/api/v3/klines')
  url.search = new URLSearchParams({ symbol: feed.symbol, interval: feed.interval, limit: '300' })
  if (older) url.searchParams.set('endTime', String(feed.first - 1))
  const signal = AbortSignal.any([feed.abort.signal, AbortSignal.timeout(9000)])
  const started = Date.now()
  const response = await fetch(url, { signal })
  if (!response.ok) {
    if (response.status === 400 && (await response.json()).code === -1121) feed.invalid = true
    if (response.status === 429 || response.status === 418) {
      const seconds = Number(response.headers.get('retry-after')) || 60
      feed.cooldown = Date.now() + Math.max(1, seconds) * 1000
    }
    throw Error('HTTP ' + response.status)
  }
  const data = await response.json()
  if (!Array.isArray(data)) throw Error('Invalid kline page')
  if (feed.abort.signal.aborted) return
  // Only successor bars in a latest page prove the previous REST candle closed.
  const rows = data.map((row, i) => [...row.slice(0, 6), older || i < data.length - 1])
  const reset = !older && !feed.onlineHistory
  merge(feed, rows, 'rest', reset)
  if (!older && rows.length) {
    feed.onlineHistory = true
    void recentHistory(feed.key, { started, rows }).catch(() => {})
  }
  return data.length
}

function reconnect(feed) {
  if (feed.abort.signal.aborted || feed.timer) return
  feed.timer = setTimeout(() => {
    feed.timer = null
    void connect(feed)
  }, feed.delay)
  feed.delay = Math.min(feed.delay * 2, 60000)
}

async function connect(feed) {
  if (feed.abort.signal.aborted || feed.connecting || feed.socket) return
  feed.connecting = true
  try {
    const count = await getPage(feed)
    if (count) publish(feed, { type: 'status', status: '历史已更新 · 等待实时推送' })
  } catch {
    if (feed.invalid) {
      publish(feed, { type: 'status', status: '交易对不存在，请更换交易对' })
      return
    }
    publish(feed, { type: 'status', status: '历史接口暂不可用 · 尝试实时连接' })
  } finally {
    feed.connecting = false
  }
  if (feed.abort.signal.aborted) return
  const socket = new WebSocket('wss://data-stream.binance.vision/ws/' + feed.symbol.toLowerCase() + '@kline_' + feed.interval)
  feed.socket = socket
  const onTimeout = () => socket.close()
  let watchdog = setTimeout(onTimeout, 15000)
  socket.onmessage = event => {
    if (feed.abort.signal.aborted) return
    const candle = JSON.parse(event.data).k
    if (!candle || candle.s !== feed.symbol || candle.i !== feed.interval) return
    merge(feed, [[candle.t, candle.o, candle.h, candle.l, candle.c, candle.v, candle.x]], 'stream')
    clearTimeout(watchdog)
    watchdog = setTimeout(onTimeout, 30000)
    feed.delay = 4000
    publish(feed, { type: 'status', status: '实时连接' })
  }
  socket.onclose = () => {
    clearTimeout(watchdog)
    feed.socket = null
    publish(feed, { type: 'status', status: '实时已断开 · 自动重连中' })
    reconnect(feed)
  }
}

async function start(message) {
  const { id, symbol, interval } = message
  if (!/^[A-Z0-9]{4,24}$/.test(symbol) || !Object.hasOwn(minutes, interval)) return
  const feed = { id, symbol, interval, key: symbol + ':' + interval, delay: 4000, abort: new AbortController(), count: 0 }
  windows.set(id, feed)
  try {
    const Model = await runtime
    if (feed.abort.signal.aborted) return
    feed.model = Model(minutes[interval] * 60000)
    try {
      const cached = await recentHistory(feed.key).catch(() => null)
      if (feed.abort.signal.aborted) return
      if (cached?.length) merge(feed, cached, 'cache')
      else if (sampleSymbols.includes(symbol) && sampleIntervals.includes(interval)) {
        const sample = await fetch(new URL('../samples/' + symbol + '-' + interval + '.json', import.meta.url), { signal: feed.abort.signal })
        if (sample.ok) merge(feed, (await sample.json()).map(row => [...row, true]), 'sample')
      }
    } catch { /* The exchange can still supply the initial window. */ }
    publish(feed, { type: 'status', status: '正在连接交易所' })
    await connect(feed)
  } catch (error) {
    publish(feed, { type: 'status', status: '行情引擎启动失败 · ' + String(error) })
  }
}

self.onmessage = async ({ data }) => {
  if (data.type === 'start') return start(data)
  const feed = windows.get(data.id)
  if (!feed) return
  if (data.type === 'stop') {
    windows.delete(feed.id)
    feed.abort.abort()
    clearTimeout(feed.timer)
    feed.socket?.close()
    feed.model?.destroy()
  } else if (data.type === 'older' && !feed.paging && feed.first) {
    feed.paging = true
    try {
      const count = await getPage(feed, true)
      publish(feed, { type: 'page', text: count ? '已读取更早的行情' : '已到历史起点', exhausted: !count || feed.count >= 2400 })
    } catch {
      publish(feed, { type: 'page', text: '历史接口暂不可用，可以重试' })
    } finally { feed.paging = false }
  }
}
