import { loadHistory, queueOlder, commitPage } from './recent-history.mjs'
import { loadPyodide } from './pyodide.mjs'

const windows = new Map()
const minutes = { '1m': 1, '5m': 5, '15m': 15, '30m': 30, '1h': 60, '4h': 240, '1d': 1440 }
const sampleSymbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
const sampleIntervals = ['5m', '15m', '1h', '1d']
const runtime = (async () => {
  const py = await loadPyodide({ indexURL: new URL('./', import.meta.url).href })
  const bundle = await fetch(new URL('desktop-modules.json', import.meta.url))
  if (!bundle.ok) throw Error('Desktop indicator bundle unavailable')
  for (const [name, source] of Object.entries(await bundle.json())) {
    py.FS.mkdirTree(name.slice(0, name.lastIndexOf('/')))
    py.FS.writeFile(name, source)
  }
  const source = await fetch(new URL('market_window.py', import.meta.url))
  if (!source.ok) throw Error('Browser market module unavailable')
  py.FS.writeFile('market_window.py', await source.text())
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
  feed.gap = result.gap
  feed.first = result.first
  feed.count = result.count
  publish(feed, { type: 'bars', reset, origin, ...result })
  if (result.bars.length) updateStudies(feed, result.bars.length === 1 && result.bars[0].time * 1000 === result.last)
}

function updateStudies(feed, tailOnly = false) {
  if (!feed.model || !feed.studies || !feed.count) return
  const output = JSON.parse(feed.model.indicators(JSON.stringify(feed.studies), tailOnly))
  publish(feed, { type: 'studies', ...output })
}

async function getPage(feed, { before, gap } = {}) {
  if (Date.now() < (feed.cooldown ?? 0)) throw Error('Rate limited')
  const url = new URL('https://data-api.binance.vision/api/v3/klines')
  url.search = new URLSearchParams({ symbol: feed.symbol, interval: feed.interval, limit: '300' })
  if (before != null) url.searchParams.set('endTime', String(before - 1))
  if (gap) {
    url.searchParams.set('startTime', String(gap[0]))
    url.searchParams.set('endTime', String(gap[1] - 1))
  }
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
  const rows = data.map((row, i) => [...row.slice(0, 6), before != null || !!gap || i < data.length - 1])
  try {
    await commitPage(feed.key, rows, started, before)
  } catch {
    publish(feed, { type: 'warning', text: '浏览器无法保存行情，刷新后可能丢失' })
  }
  // Always retain restored history. Only the bundled seed may be replaced.
  const reset = feed.seedOnly && before == null && !gap
  feed.seedOnly = false
  merge(feed, rows, 'rest', reset)
  return data.length
}

async function extendHistory(feed, before) {
  if (feed.paging || feed.abort.signal.aborted) return
  feed.paging = true
  feed.pending.add(before)
  try {
    await queueOlder(feed.key, before).catch(() =>
      publish(feed, { type: 'warning', text: '浏览器无法保存补数进度' }))

    const count = await getPage(feed, { before })
    feed.pending.delete(before)
    publish(feed, { type: 'page', text: count ? '已保存更早的行情' : '已到历史起点', exhausted: count === 0 })
  } catch {
    publish(feed, { type: 'page', text: '补数未完成，将从上次位置重试' })
  } finally { feed.paging = false }
}

async function repair(feed) {
  if (feed.abort.signal.aborted || feed.repairing) return
  feed.repairing = true
  try {
    if (feed.pending.size) await extendHistory(feed, feed.pending.values().next().value)
    if (feed.gap && !feed.abort.signal.aborted) {
      const from = feed.gap[0]
      await getPage(feed, { gap: feed.gap })
      feed.retryDelay = feed.gap?.[0] === from ? Math.min((feed.retryDelay || 4000) * 2, 120000) : 4000
    }
  } catch { /* The missing interval is derived again from the committed timestamps. */ }
  finally {
    feed.repairing = false
    if (!feed.abort.signal.aborted && (feed.pending.size || feed.gap)) {
      clearTimeout(feed.repairTimer)
      feed.repairTimer = setTimeout(() => { feed.repairTimer = null; void repair(feed) }, Math.max(feed.retryDelay || 4000, (feed.cooldown ?? 0) - Date.now()))
    }
  }
}

function reconnect(feed) {
  if (feed.abort.signal.aborted || feed.timer) return
  feed.timer = setTimeout(() => {
    feed.timer = null
    void connect(feed)
  }, feed.delay)
  feed.delay = Math.min(feed.delay * 2, 60000)
}

async function refreshLatest(feed) {
  if (feed.abort.signal.aborted || feed.fetchingLatest || feed.invalid) return
  feed.fetchingLatest = true
  clearTimeout(feed.latestTimer)
  try {
    const count = await getPage(feed)
    feed.latestDelay = 4000
    void repair(feed)
    if (count && !feed.socket) publish(feed, { type: 'status', status: '历史已更新 · 等待实时推送' })
  } catch {
    if (feed.abort.signal.aborted) return
    if (feed.invalid) {
      publish(feed, { type: 'status', status: '交易对不存在，请更换交易对' })
      return
    }
    // REST can fail while the live socket stays healthy for hours.
    publish(feed, { type: 'status', status: '历史接口暂不可用 · 将自动重试' })
    feed.latestTimer = setTimeout(() => refreshLatest(feed),
      Math.max(feed.latestDelay || 4000, (feed.cooldown ?? 0) - Date.now()))
    feed.latestDelay = Math.min((feed.latestDelay || 4000) * 2, 60000)
  } finally { feed.fetchingLatest = false }
}

async function connect(feed) {
  if (feed.abort.signal.aborted || feed.connecting || feed.socket) return
  feed.connecting = true
  await refreshLatest(feed)
  feed.connecting = false
  if (feed.abort.signal.aborted || feed.invalid) return
  const socket = new WebSocket('wss://data-stream.binance.vision/ws/' + feed.symbol.toLowerCase() + '@kline_' + feed.interval)
  feed.socket = socket
  const onTimeout = () => socket.close()
  let watchdog = setTimeout(onTimeout, 15000)
  socket.onmessage = event => {
    if (feed.abort.signal.aborted) return
    const candle = JSON.parse(event.data).k
    if (!candle || candle.s !== feed.symbol || candle.i !== feed.interval) return
    const row = [candle.t, candle.o, candle.h, candle.l, candle.c, candle.v, candle.x]
    merge(feed, [row], 'stream')
    if (candle.x) void commitPage(feed.key, [row], Date.now(), null, 'stream').catch(() =>
      publish(feed, { type: 'warning', text: '浏览器无法保存已收盘行情' }))
    if (feed.gap && !feed.repairTimer) void repair(feed)
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
  const feed = { id, symbol, interval, studies: message.studies, key: symbol + ':' + interval, delay: 4000, abort: new AbortController(), count: 0, pending: new Set() }
  windows.set(id, feed)
  try {
    const Model = await runtime
    if (feed.abort.signal.aborted) return
    feed.model = Model(minutes[interval] * 60000)
    try {
      const cached = await loadHistory(feed.key).catch(() => {
        publish(feed, { type: 'warning', text: '历史缓存暂不可用，请检查存储空间或关闭旧版标签页' })
        return null
      })
      if (feed.abort.signal.aborted) return
      feed.pending = new Set(cached?.pending)
      if (cached?.exhausted) publish(feed, { type: 'page', text: '已到历史起点', exhausted: true })
      if (cached?.rows.length) merge(feed, cached.rows, 'cache')
      else if (sampleSymbols.includes(symbol) && sampleIntervals.includes(interval)) {
        const sample = await fetch(new URL('../samples/' + symbol + '-' + interval + '.json', import.meta.url), { signal: feed.abort.signal })
        feed.seedOnly = true
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
  if (data.type === 'studies') {
    feed.studies = data.studies
    updateStudies(feed)
  } else if (data.type === 'stop') {
    windows.delete(feed.id)
    feed.abort.abort()
    clearTimeout(feed.timer)
    clearTimeout(feed.latestTimer)
    clearTimeout(feed.repairTimer)
    feed.socket?.close()
    feed.model?.destroy()
  } else if (data.type === 'older' && !feed.paging && feed.first) {
    await extendHistory(feed, feed.pending.values().next().value ?? feed.first)
    if (feed.pending.size) void repair(feed)
  }
}
