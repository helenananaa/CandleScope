import { useEffect, useMemo, useRef, useState } from 'react'
import { filterSymbols, formatSymbolLabel } from '../features/symbol-search/symbolSearchFilter'
import type { SymbolSearchItem } from '../features/symbol-search/symbolSearchTypes'
import { createWatchlistId, useWatchlistStore, WATCHLIST_COLORS } from '../features/watchlist/watchlistStore'
import { parseSymbolKey, symbolKey } from '../utils/symbolKey'
import bundled from './spot-catalog.json'

type Markets = ReturnType<typeof useWatchlistStore>
type Listing = [string, string, string]
const cacheKey = 'candlescope-web-spot-directory-v1'

function listing(row: string[]): SymbolSearchItem {
  const [symbol = '', baseAsset = '', quoteAsset = ''] = row
  return { symbol, baseAsset, quoteAsset, exchange: 'binance', marketType: 'spot', _key: symbolKey(symbol, 'spot', 'binance') }
}

interface ExchangeListing { symbol: string; baseAsset: string; quoteAsset: string; status: string; isSpotTradingAllowed: boolean }
function isListing(row: unknown): row is Listing {
  return Array.isArray(row) && row.length === 3 && row.every(value => typeof value === 'string')
}
function isTradingPair(value: unknown): value is ExchangeListing {
  if (!value || typeof value !== 'object') return false
  const row = value as Record<string, unknown>
  return row.status === 'TRADING' && row.isSpotTradingAllowed === true && typeof row.symbol === 'string'
    && /^[A-Z0-9]{4,24}$/.test(row.symbol) && typeof row.baseAsset === 'string' && typeof row.quoteAsset === 'string'
}
function useCatalog() {
  const [rows, setRows] = useState<string[][]>(bundled)
  useEffect(() => {
    const controller = new AbortController()
    try {
      const cached = JSON.parse(localStorage.getItem(cacheKey) ?? 'null') as { rows?: unknown; at?: unknown } | null
      if (Array.isArray(cached?.rows) && cached.rows.every(isListing)) {
        setRows(cached.rows)
        if (typeof cached.at === 'number' && Date.now() - cached.at < 86400000) return
      }
    } catch { /* The bundled directory also works offline. */ }
    async function refresh() {
      const url = 'https://data-api.binance.vision/api/v3/exchangeInfo?permissions=SPOT&showPermissionSets=false&symbolStatus=TRADING'
      const r = await fetch(url, { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]) })
      if (!r.ok) return
      const data = await r.json() as { symbols?: unknown } | null
      if (!Array.isArray(data?.symbols)) return
      const next: Listing[] = data.symbols.filter(isTradingPair).map(s => [s.symbol, s.baseAsset, s.quoteAsset])
      if (next.length && !controller.signal.aborted) {
        setRows(next)
        localStorage.setItem(cacheKey, JSON.stringify({ at: Date.now(), rows: next }))
      }
    }
    void refresh().catch(() => {})
    return () => controller.abort()
  }, [])
  return useMemo(() => rows.map(listing), [rows])
}

export function BrowserMarkets({ markets, mode, close, select }: {
  markets: Markets; mode: 'search' | 'watchlist'; close(): void; select(symbol: string): void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const catalog = useCatalog()
  const [query, setQuery] = useState('')
  const [tab, setTab] = useState(mode)
  const [groupId, setGroupId] = useState(() => {
    try { return localStorage.getItem('candlescope-web-active-watchlist') || markets.watchlists[0]!.id }
    catch { return markets.watchlists[0]!.id }
  })
  const [newList, setNewList] = useState('')
  const [limit, setLimit] = useState(60)
  const group = markets.watchlists.find(g => g.id === groupId) ?? markets.watchlists[0]!
  useEffect(() => {
    try { localStorage.setItem('candlescope-web-active-watchlist', group.id) } catch { /* Session selection is usable. */ }
  }, [group.id])
  const items = useMemo(() => {
    const byKey = new Map(catalog.map(item => [item._key, item]))
    const all = tab === 'search' ? catalog : group.symbols.flatMap(key => {
      const { symbol, exchange, marketType } = parseSymbolKey(key)
      if (exchange !== 'binance' || marketType !== 'spot') return []
      return [byKey.get(key) ?? listing([symbol, '', ''])]
    })
    return filterSymbols({ allSymbols: all, marketType: 'spot', exchangeFilter: new Set(), quoteFilter: '', search: query, favorites: [] })
      .sort((a,b) => Number(b.symbol === query.toUpperCase()) - Number(a.symbol === query.toUpperCase()))
  }, [catalog, group, tab, query])
  useEffect(() => { dialog.current?.showModal() }, [])
  function toggle(key: string) {
    if (!group.symbols.includes(key)) markets.actions.addToWatchlist(group.id, key)
    else markets.actions.setWatchlists(prev => prev.map(g => g.id === group.id ? { ...g, symbols: g.symbols.filter(s => s !== key) } : g))
  }
  return <dialog ref={dialog} aria-label="市场与自选" className="web-market-dialog" onCancel={close}>
    <header><strong>Binance 现货</strong><button aria-label="关闭" onClick={close}>×</button></header>
    <div className="web-market-tabs">{(['search','watchlist'] as const).map(t =>
      <button key={t} aria-pressed={tab === t} onClick={() => setTab(t)}>{t === 'search' ? '品种搜索' : '自选列表'}</button>)}</div>
    <input autoFocus aria-label="搜索交易对" placeholder="搜索代码、基础币或计价币" value={query}
      onChange={e => { setQuery(e.target.value); setLimit(60) }} onKeyDown={e => { if (e.key === 'Enter' && items[0]) select(items[0].symbol) }} />
    <div className="web-market-group"><label>自选分组 <select value={group.id} onChange={e => setGroupId(e.target.value)}>
      {markets.watchlists.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}</select></label>
      {tab === 'watchlist' && <form onSubmit={e => {
        e.preventDefault()
        const name = newList.trim()
        if (!name) return
        const id = createWatchlistId()
        markets.actions.setWatchlists(prev => [...prev, { id, name, symbols: [], color: WATCHLIST_COLORS[0] }])
        setGroupId(id); setNewList('')
      }}><input aria-label="新分组名称" placeholder="新分组名称" maxLength={48} value={newList} onChange={e => setNewList(e.target.value)} />
        <button disabled={!newList.trim()}>新建</button></form>}
    </div>
    <div className="web-search-list">{items.slice(0,limit).map(item => <div key={item._key}>
      <button className="web-pair" onClick={() => select(item.symbol)}>{formatSymbolLabel(item)}</button>
      <button aria-label={(group.symbols.includes(item._key) ? '移出自选 ' : '加入自选 ') + item.symbol}
        aria-pressed={group.symbols.includes(item._key)} onClick={() => toggle(item._key)}>{group.symbols.includes(item._key) ? '★' : '☆'}</button>
    </div>)}
    {!items.length && <p>{tab === 'watchlist' ? '当前分组没有匹配的交易对，可在品种搜索中点 ☆ 添加。' : '没有匹配的交易对。'}</p>}
    {!items.length && tab === 'search' && /^[A-Z0-9]{4,24}$/.test(query.trim().toUpperCase()) &&
      <button onClick={() => select(query.trim().toUpperCase())}>按代码打开 {query.trim().toUpperCase()}</button>}
    {items.length > limit && <button onClick={() => setLimit(limit + 60)}>显示更多</button>}</div>
  </dialog>
}
