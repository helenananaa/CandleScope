import { useCallback, useEffect, useRef, useState } from 'react'
import type { KlineBar } from '../features/market-data/marketDataTypes'
import { SeriesWindowStore } from '../features/market-data/window/seriesWindowStore'

import { parseIntervalSeconds } from '../utils/intervals'
import type { Studies, StudyLines } from './browserStudies'
import { names } from './browserStudies'

let worker: Worker | undefined
let sequence = 0
interface FeedMessage {
  id: number
  type: 'bars' | 'status' | 'page' | 'studies' | 'warning'
  lines?: StudyLines
  full?: boolean
  status?: string
  bars?: KlineBar[]
  gaps?: number
  origin?: string
  reset?: boolean
  text?: string
  exhausted?: boolean
}

export function useBrowserFeed(symbol: string, interval: string, studies: Studies) {
  // The parent keys each cell by market and interval, so all state belongs to this series.
  const [store] = useState(() => new SeriesWindowStore({
    seriesKey: symbol + ':' + interval, intervalSeconds: parseIntervalSeconds(interval), maxBars: Number.MAX_SAFE_INTEGER,
  }))
  const [id] = useState(() => ++sequence)
  const currentStudies = useRef(studies)
  const [lines, setLines] = useState<StudyLines>({})
  const [historySource, setHistorySource] = useState('')
  const [status, setStatus] = useState('正在加载行情引擎')
  const [gaps, setGaps] = useState(0)
  const [revision, setRevision] = useState(0)
  const pending = useRef<{ promise: Promise<void>; resolve(): void } | null>(null)
  const [paging, setPaging] = useState(false)
  const [exhausted, setExhausted] = useState(false)
  const [warning, setWarning] = useState('')
  const [pageText, setPageText] = useState('')
  useEffect(() => {
    worker ??= new Worker(new URL('engine/market-worker.mjs', document.baseURI), { type: 'module' })
    const target = worker
    function receive({ data }: MessageEvent<FeedMessage>) {
      if (data.id !== id) return
      if (data.type === 'studies' && data.lines) {
        const incoming = data.lines
        setLines(previous => {
          if (data.full) return incoming
          const next = { ...previous }
          for (const name of names) {
            const point = incoming[name]?.at(-1)
            if (!point) continue
            const old = previous[name] ?? []
            next[name] = [...(old.at(-1)?.time === point.time ? old.slice(0, -1) : old), point]
          }
          return next
        })
      }
      if (data.type === 'warning') setWarning(data.text ?? '')
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
        if (data.exhausted !== undefined) setExhausted(data.exhausted)
        pending.current?.resolve()
        pending.current = null
        setPaging(false)
      }
    }
    const failed = () => { pending.current?.resolve(); pending.current = null; setStatus('行情引擎未能加载，请刷新重试'); setPaging(false) }
    target.addEventListener('message', receive)
    target.addEventListener('error', failed)
    target.postMessage({ type: 'start', id, symbol, interval, studies: currentStudies.current })
    return () => {
      pending.current?.resolve()
      pending.current = null
      target.removeEventListener('message', receive)
      target.removeEventListener('error', failed)
      target.postMessage({ type: 'stop', id })
    }
  }, [symbol, interval, id, store])
  useEffect(() => {
    currentStudies.current = studies
    worker?.postMessage({ type: 'studies', id, studies })
  }, [id, studies])
  const loadOlder = useCallback((): Promise<void> => {
    if (pending.current) return pending.current.promise
    if (exhausted || !store.barCount) return Promise.resolve()
    let resolve!: () => void
    const promise = new Promise<void>(done => { resolve = done })
    pending.current = { promise, resolve }
    setPaging(true)
    worker?.postMessage({ type: 'older', id })
    return promise
  }, [exhausted, store, id])
  return { store, warning, lines, revision, gaps, status, historySource, older: loadOlder, loadOlder, paging, exhausted, pageText }
}
