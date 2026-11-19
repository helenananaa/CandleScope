import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import SingleChartPanes from '../components/SingleChartPanes'
import type { MainChartType } from '../shared/mainChartTypes'
import type { DrawingToolId } from '../features/drawings/drawingTypes'
import { SeriesWindowStore } from '../features/market-data/window/seriesWindowStore'
import type { KlineBar } from '../features/market-data/marketDataTypes'
import type { IndicatorLine } from '../features/indicators/indicatorTypes'
import { BrowserMarkets } from './BrowserMarkets'
import { useWatchlistStore } from '../features/watchlist/watchlistStore'
import { IndicatorNumberInput } from '../features/indicators/IndicatorNumberInput'
import { BrowserChartLinks, defaultLinks, linkLabels, readViewport, saveViewport, type LinkOptions } from './browserChartLinks'
import { names, readStudies, sources, type Studies } from './browserStudies'
import type { ChartSurfaceHandle } from '../chart-adapter/useChartSurfaceRuntime'
import { useBrowserFeed } from './browserFeed'
import '../styles/layers.css'
import '../styles/fonts'
import '../index.css'
import './browserWorkspace.css'

const symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
const intervals = ['1m', '5m', '15m', '30m', '1h', '4h', '1d']
const validSymbol = (symbol: unknown): symbol is string => typeof symbol === 'string' && /^[A-Z0-9]{4,24}$/.test(symbol)
const styles: Partial<Record<MainChartType, string>> = {
  candlestick: 'K 线', 'hollow-candlestick': '空心 K 线', 'heikin-ashi': '平均 K 线',
  line: '折线', area: '面积', bar: '美国线', baseline: '基线',
}
const tools: Partial<Record<DrawingToolId, string>> = {
  'cursor-crosshair': '十字线', 'line-segment': '趋势线', 'line-horizontal': '水平线', 'line-ray': '射线',
  'shape-rectangle': '矩形', fibonacci: '斐波那契', 'measure-price-time': '量价测量', pen: '画笔', eraser: '橡皮擦',
}
type Cell = { symbol: string; interval: string; style: MainChartType; studies: Studies; ma?: boolean; volume: boolean }
type Layout = { count: number; cells: Cell[]; links: LinkOptions }
const releaseUrl = 'https://github.com/helenananaa/CandleScope/releases'
const settingsKey = 'candlescope-browser-workspace-v1'
function readLayout(): Layout {
  let saved: Partial<Layout> | null = null
  try { saved = JSON.parse(localStorage.getItem(settingsKey) ?? 'null') as Partial<Layout> | null } catch { /* Private or corrupt storage. */ }
  const cells = Array.from({ length: 4 }, (_, i): Cell => {
    const cell = saved?.cells?.[i]
    return {
      symbol: cell && validSymbol(cell.symbol) ? cell.symbol : symbols[i % symbols.length]!,
      interval: cell && intervals.includes(cell.interval) ? cell.interval : i === 3 ? '15m' : '1h',
      style: cell && Object.hasOwn(styles, cell.style) ? cell.style : 'candlestick',
      studies: readStudies(cell?.studies, cell?.ma !== false), volume: cell?.volume === true,
    }
  })
  return { count: [2, 4].includes(saved?.count ?? 0) ? saved!.count! : 1, cells, links: { ...defaultLinks, ...saved?.links } }
}

function ChartCell({ cell, update, theme, slot, bus, links, search, active, activate }: {
  cell: Cell; update: (changes: Partial<Cell>) => void; theme: string; slot: number
  bus: BrowserChartLinks; links: LinkOptions; search(): void; active: boolean; activate(): void
}) {
  const feed = useBrowserFeed(cell.symbol, cell.interval, cell.studies)
  const viewportKey = 'candlescope-web-view:' + slot + ':' + feed.store.seriesKey
  const [initialView] = useState(() => readViewport(viewportKey))
  const awaitingView = useRef(initialView)
  const bind = useCallback((handle: ChartSurfaceHandle | null) => {
    bus.register(slot, handle, viewportKey)
  }, [bus, slot, viewportKey])
  useEffect(() => {
    const handle = bus.handles.get(slot)
    if (!handle || !feed.store.barCount) return
    function restore() {
      if (bus.applyPending(slot)) { awaitingView.current = null; return }
      if (awaitingView.current && handle?.setLinkedVisibleTimeRange(awaitingView.current)) awaitingView.current = null
    }
    const release = handle.subscribeLinkedViewportReady(restore)
    const frame = requestAnimationFrame(restore)
    return () => { cancelAnimationFrame(frame); release() }
  }, [bus, slot, feed.revision, feed.store])
  const [tool, setTool] = useState<DrawingToolId | null>('cursor-crosshair')
  const [replay, setReplay] = useState<{ rows: KlineBar[]; index: number } | null>(null)
  const [playing, setPlaying] = useState(false)
  const [replayStore] = useState(() => new SeriesWindowStore({ seriesKey: 'replay:' + feed.store.seriesKey }))
  useEffect(() => {
    if (!replay || !playing || replay.index >= replay.rows.length) return
    const timer = setTimeout(() => setReplay({ ...replay, index: replay.index + 1 }), 500)
    return () => clearTimeout(timer)
  }, [replay, playing])
  useEffect(() => {
    if (replay) replayStore.replace(replay.rows.slice(0, replay.index))
  }, [replay, replayStore])
  const liveRows = feed.store.snapshot()
  const rows = useMemo(() => replay ? replay.rows.slice(0, replay.index) : liveRows, [liveRows, replay])
  const studies = useMemo(() => {
    const lines: IndicatorLine[] = []
    for (const name of names) {
      const spec = cell.studies[name]
      const data = feed.lines[name]
      if (!spec.enabled || !data) continue
      const cutoff = replay?.rows[replay.index - 1]?.time
      lines.push({ id: name, name: name.toUpperCase() + ' ' + spec.period,
        color: { ma: '#e6bb73', ema: '#6babc2', rsi: '#ad86d3' }[name],
        data: cutoff == null ? data : data.filter(p => p.time <= cutoff), lineWidth: 2 })
    }
    return lines
  }, [cell.studies, feed.lines, replay])
  const lines = useMemo(() => studies.filter(line => line.id !== 'rsi'), [studies])
  const subPanes = useMemo(() => {
    const panes = []
    const rsi = studies.find(line => line.id === 'rsi')
    if (rsi) panes.push({ id: 'rsi', label: rsi.name!, lines: [rsi] })
    if (cell.volume) panes.push({
      id: 'browser-volume', label: '成交量', lines: [{
        id: 'volume', name: '成交量', type: 'histogram', data: rows.map(row => ({
          time: row.time, value: Number(row.volume), color: Number(row.close) >= Number(row.open) ? '#279c81' : '#d66a67',
        })),
      }],
    })
    return panes
  }, [cell.volume, rows, studies])
  const store = replay ? replayStore : feed.store
  const dataMeta = useMemo(() => ({
    version: replay?.index ?? feed.revision, status: 'ready', source: 'browser',
    seriesKey: store.seriesKey, committedAt: null,
  }), [feed.revision, replay?.index, store])
  const last = replay ? replay.rows[replay.index - 1] : store.last()
  function toggleReplay() {
    setPlaying(false)
    if (replay) { setReplay(null); return }
    const rows = feed.store.snapshot().slice()
    setReplay({ rows, index: Math.max(1, rows.length - 60) })
  }
  return <section className="web-cell" aria-label={'图表 ' + (slot + 1)} data-active={active}
    onFocusCapture={activate} onPointerDownCapture={activate} onPointerEnter={() => { bus.pointer(slot) }}
    onPointerLeave={() => { if (links.crosshair) bus.crosshair(slot, null); bus.pointer(null) }}>
    <header className="web-cell-head">
      <button className="web-symbol" aria-label={'搜索交易对 ' + cell.symbol} onClick={search}>{cell.symbol} ⌕</button>
      <strong className="web-price">{last?.close?.toLocaleString('en-US', { maximumFractionDigits: 4 }) ?? '—'}</strong>
      <span className="web-source" title={feed.status}>{replay ? 'K 线回放' : feed.status}</span>
    </header>
    <div className="web-tools">
      <select aria-label="周期" value={cell.interval} onChange={e => update({ interval: e.target.value })}>
        {intervals.map(i => <option key={i}>{i}</option>)}</select>
      <select aria-label="图表类型" value={cell.style} onChange={e => update({ style: e.target.value as MainChartType })}>
        {Object.entries(styles).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select>
      <details className="web-studies"><summary>指标参数</summary><div>
        {names.map(name => {
          const spec = cell.studies[name]
          const patch = (change: Partial<typeof spec>) => update({ studies: { ...cell.studies, [name]: { ...spec, ...change } } })
          return <fieldset key={name}><legend><label><input type="checkbox" checked={spec.enabled}
            onChange={e => patch({ enabled: e.target.checked })} />{name.toUpperCase()}</label></legend>
            <label>周期 <IndicatorNumberInput key={spec.period} title={name.toUpperCase() + ' 周期'} min={2} max={500} step={1} value={spec.period}
              onCommit={period => patch({ period })} /></label>
            <label>价格 <select aria-label={name.toUpperCase() + ' 价格'} value={spec.source} onChange={e => patch({ source: e.target.value as typeof spec.source })}>
              {sources.map(v => <option key={v}>{v}</option>)}</select></label>
          </fieldset>
        })}
      </div></details>
      <button aria-pressed={cell.volume} onClick={() => update({ volume: !cell.volume })}>成交量</button>
      <select aria-label="绘图工具" value={tool ?? 'cursor-crosshair'} onChange={e => setTool(e.target.value as DrawingToolId)}>
        {Object.entries(tools).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select>
      <button disabled={!last || feed.paging || feed.exhausted || !!replay} onClick={feed.older}>{feed.paging ? '读取中…' : '更早行情'}</button>
      <button disabled={!last} aria-pressed={!!replay} onClick={toggleReplay}>{replay ? '退出回放' : '回放'}</button>
    </div>
    {replay && <div className="web-playback">
      <button onClick={() => setPlaying(!playing)} disabled={replay.index === replay.rows.length}>{playing && replay.index < replay.rows.length ? '暂停' : '播放'}</button>
      <input aria-label="回放位置" type="range" min="1" max={replay.rows.length} value={replay.index}
        onChange={e => { setPlaying(false); setReplay({ ...replay, index: Number(e.target.value) }) }} />
      <button disabled={replay.index === replay.rows.length} onClick={() => setReplay({ ...replay, index: replay.index + 1 })}>下一根</button>
    </div>}
    <SingleChartPanes ref={bind}
      onCrosshairMove={value => { if (links.crosshair) bus.crosshair(slot, typeof value?.time === 'number' ? value.time : null) }}
      onUserViewportRangeChange={range => {
        if (!range.time || replay) return
        awaitingView.current = null
        saveViewport(viewportKey, range.time)
        if (links.range) bus.range(slot, range.time)
      }}
      onNeedMoreLeft={replay ? null : feed.loadOlder} canLoadMoreLeft={!feed.exhausted && !feed.paging}
      key={replay ? 'replay' : 'market'} symbol={cell.symbol} interval={cell.interval} datasetKey={String(store.seriesKey)} seriesStore={store} dataMeta={dataMeta}
      theme={theme} inheritApplicationTheme={false} customBg={theme === 'dark' ? '#191c21' : '#ffffff'}
      upColor="#279c81" downColor="#d66a67" chartType={cell.style} mainOverlayLines={lines} subPanes={subPanes}
      drawingKeyBase={'web:binance:spot:' + cell.symbol + ':' + slot} drawingTool={tool} onDrawingToolChange={setTool}
      drawingsEnabled penColor="#cf9a4c" penSize={2} loading={!last && !feed.status.includes('不存在') && !feed.status.includes('失败')} timezone="UTC" />
    <footer className="web-cell-status"><span>Binance 现货 · UTC</span><span>{feed.historySource}</span>
      <span>{last && new Date(Number(last.time) * 1000).toISOString().slice(0, 16).replace('T', ' ')}</span>
      <span>{replay ? replay.index : feed.store.barCount} 根{feed.gaps > 0 && !replay ? ' · 存在历史缺口' : ''}</span>
      {feed.warning && <span role="status">{feed.warning}</span>}
      {feed.pageText && !replay && <span role="status">{feed.pageText}</span>}</footer>
  </section>
}

export default function Workspace() {
  const [layout, setLayout] = useState(readLayout)
  const [bus] = useState(() => new BrowserChartLinks())
  const [active, setActive] = useState(0)
  const [panel, setPanel] = useState<'search' | 'watchlist' | null>(null)
  const markets = useWatchlistStore()
  const updateCell = (slot: number, changes: Partial<Cell>) => setLayout(prev => ({
    ...prev, cells: prev.cells.map((cell, index) => {
      if (slot === index) return { ...cell, ...changes }
      if (index >= prev.count) return cell
      if (changes.symbol && prev.links.symbol) return { ...cell, symbol: changes.symbol }
      if (prev.links.studies && changes.studies) return { ...cell, studies: changes.studies }
      if (prev.links.studies && changes.volume !== undefined) return { ...cell, volume: changes.volume }
      if (changes.interval && prev.links.interval) return { ...cell, interval: changes.interval }
      return cell
    }),
  }))
  function toggleLink(key: keyof LinkOptions, checked: boolean) {
    if (!checked && key === 'range') bus.cancelPending()
    if (!checked && key === 'crosshair') for (const handle of bus.handles.values()) handle.setLinkedCrosshairTime(null)
    setLayout(prev => {
      const source = prev.cells[active]!
      const cells = prev.cells.map((cell, index) => {
        if (!checked || index === active || index >= prev.count) return cell
        if (key === 'symbol') return { ...cell, symbol: source.symbol }
        if (key === 'interval') return { ...cell, interval: source.interval }
        if (key === 'studies') return { ...cell, studies: source.studies, volume: source.volume }
        return cell
      })
      return { ...prev, cells, links: { ...prev.links, [key]: checked } }
    })
    if (key === 'range' && checked) {
      const range = bus.handles.get(active)?.getVisibleRange()?.time
      if (range) bus.range(active, range)
    }
  }
  const [theme, setTheme] = useState(() => { try { return localStorage.getItem(settingsKey + '-theme') === 'light' ? 'light' : 'dark' } catch { return 'dark' } })
  useEffect(() => { try { localStorage.setItem(settingsKey, JSON.stringify(layout)) } catch { /* Session remains usable. */ } }, [layout])
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem(settingsKey + '-theme', theme) } catch { /* Session remains usable. */ }
  }, [theme])
  return <main className="web-workspace" data-theme={theme}>
    {panel && <BrowserMarkets markets={markets} mode={panel} close={() => setPanel(null)}
      select={symbol => { updateCell(active, { symbol }); setPanel(null) }} />}
    <header className="web-header"><div className="web-brand"><img src="./favicon.svg" alt=""/>CandleScope</div>
      <span className="web-title">网页工作台</span>
      <button onClick={() => setPanel('watchlist')}>自选列表</button>
      <details className="web-link-menu"><summary>多图联动</summary><div>
        {(Object.keys(linkLabels) as (keyof LinkOptions)[]).map(key =>
          <label key={key}><input type="checkbox" checked={layout.links[key]}
            onChange={e => toggleLink(key, e.target.checked)} />
            {linkLabels[key]}</label>)}
      </div></details>
      <nav aria-label="工作区布局">{[1,2,4].map(count => <button key={count} aria-pressed={count === layout.count}
        onClick={() => { setActive(Math.min(active, count - 1)); setLayout({ ...layout, count }) }}>{count} 图</button>)}</nav>
      <button onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? '浅色' : '深色'}</button>
      <details className="web-desktop"><summary>桌面版</summary><div>完整训练回放、Python 策略回测、账户和原生插件需要桌面版。<a href={releaseUrl} target="_blank" rel="noreferrer">下载 CandleScope ↗</a></div></details>
    </header>
    <div className={'web-grid grid-' + layout.count}>{layout.cells.slice(0, layout.count).map((cell, i) =>
      <ChartCell key={i + cell.symbol + cell.interval} cell={cell} slot={i} theme={theme} bus={bus} links={layout.links} active={active === i} activate={() => setActive(i)}
        search={() => { setActive(i); setPanel('search') }} update={change => updateCell(i, change)} />)}</div>
  </main>
}
