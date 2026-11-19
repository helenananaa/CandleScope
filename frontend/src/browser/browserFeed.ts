import { useEffect, useState } from 'react'
import type { KlineBar } from '../features/market-data/marketDataTypes'
import { SeriesWindowStore } from '../features/market-data/window/seriesWindowStore'

import { parseIntervalSeconds } from '../utils/intervals'
let worker: Worker | undefined
let sequence = 0
interface FeedMessage {
  id: number
  type: 'bars' | 'status' | 'page'
  status?: string
  bars?: KlineBar[]
  gaps?: number
  origin?: string
  reset?: boolean
  text?: string
  exhausted?: boolean
}

export function useBrowserFeed(symbol: string, interval: string) {
  // The parent keys each cell by market and interval, so all state belongs to this series.
  const [store] = useState(() => new SeriesWindowStore({
    seriesKey: symbol + ':' + interval, intervalSeconds: parseIntervalSeconds(interval), maxBars: 2400,
  }))
  const [id] = useState(() => ++sequence)
  const [historySource, setHistorySource] = useState('')
  const [status, setStatus] = useState('正在加载行情引擎')
  const [gaps, setGaps] = useState(0)
  const [revision, setRevision] = useState(0)
  const [paging, setPaging] = useState(false)
  const [exhausted, setExhausted] = useState(false)
  const [pageText, setPageText] = useState('')
  useEffect(() => {
    worker ??= new Worker(new URL('engine/market-worker.mjs', document.baseURI), { type: 'module' })
    const target = worker
    function receive({ data }: MessageEvent<FeedMessage>) {
      if (data.id !== id) return
      if (data.type === 'status') setStatus(data.status ?? '')
      if (data.type === 'bars' && data.bars) {
        if (data.origin === 'sample') setHistorySource('随站历史样本')
        if (data.origin === 'cache') setHistorySource('本机历史缓存')
        if (data.origin === 'rest') setHistorySource('交易所历史')
        if (!store.barCount || data.reset) store.replace(data.bars)
        else store.applyRange(data.bars)
        setRevision(Number(store.version))
        setGaps(data.gaps ?? 0)
      }
      if (data.type === 'page') {
        setPageText(data.text ?? '')
        setExhausted(Boolean(data.exhausted))
        setPaging(false)
      }
    }
    const failed = () => { setStatus('行情引擎未能加载，请刷新重试'); setPaging(false) }
    target.addEventListener('message', receive)
    target.addEventListener('error', failed)
    target.postMessage({ type: 'start', id, symbol, interval })
    return () => {
      target.removeEventListener('message', receive)
      target.removeEventListener('error', failed)
      target.postMessage({ type: 'stop', id })
    }
  }, [symbol, interval, id, store])
  function older() {
    if (paging || exhausted || !store.barCount) return
    setPaging(true)
    worker?.postMessage({ type: 'older', id })
  }
  return { store, revision, gaps, status, historySource, older, paging, exhausted, pageText }
}
