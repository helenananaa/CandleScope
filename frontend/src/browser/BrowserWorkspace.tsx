import { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import SingleChartPanes from '../components/SingleChartPanes'
import type { MainChartType } from '../shared/mainChartTypes'
import type { DrawingToolId } from '../features/drawings/drawingTypes'
import { SeriesWindowStore } from '../features/market-data/window/seriesWindowStore'
import type { KlineBar } from '../features/market-data/marketDataTypes'
import type { IndicatorLine } from '../features/indicators/indicatorTypes'
import { initializeLocale } from '../i18n'
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
type Cell = { symbol: string; interval: string; style: MainChartType; ma: boolean; volume: boolean }
type Layout = { count: number; cells: Cell[] }
const releaseUrl = 'https://github.com/helenananaa/CandleScope/releases'
const settingsKey = 'candlescope-browser-workspace-v1'
function readLayout(): Layout {
  let saved: Partial<Layout> | null = null
  try { saved = JSON.parse(localStorage.getItem(settingsKey) ?? 'null') } catch { /* Private or corrupt storage. */ }
  const cells = Array.from({ length: 4 }, (_, i): Cell => {
    const cell = saved?.cells?.[i]
    return {
      symbol: cell && validSymbol(cell.symbol) ? cell.symbol : symbols[i % symbols.length]!,
      interval: cell && intervals.includes(cell.interval) ? cell.interval : i === 3 ? '15m' : '1h',
      style: cell && Object.hasOwn(styles, cell.style) ? cell.style : 'candlestick',
      ma: cell?.ma !== false, volume: cell?.volume === true,
    }
  })
  return { count: [2, 4].includes(saved?.count ?? 0) ? saved!.count! : 1, cells }
}

function average(rows: readonly KlineBar[]): IndicatorLine[] {
  let sum = 0
  const data = []
  for (let i = 0; i < rows.length; i++) {
    sum += Number(rows[i]!.close)
    if (i >= 20) sum -= Number(rows[i - 20]!.close)
    if (i >= 19) data.push({ time: Number(rows[i]!.time), value: sum / 20 })
  }
  return [{ id: 'web-sma-20', name: 'MA 20', color: '#e6bb73', lineWidth: 2, data }]
}

function ChartCell({ cell, update, theme, slot }: {
  cell: Cell; update: (changes: Partial<Cell>) => void; theme: string; slot: number
}) {
  const feed = useBrowserFeed(cell.symbol, cell.interval)
  const [editingSymbol, setEditingSymbol] = useState(false)
  const [draft, setDraft] = useState('')
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
  const rows = useMemo(() => replay ? replay.rows.slice(0, replay.index) : feed.store.snapshot(),
    [feed.store, feed.revision, replay])
  const lines = useMemo(() => cell.ma ? average(rows) : [], [cell.ma, rows])
  const subPanes = useMemo(() => !cell.volume ? [] : [{
    id: 'browser-volume', label: '成交量', lines: [{
      id: 'volume', name: '成交量', type: 'histogram', data: rows.map(row => ({
        time: row.time, value: Number(row.volume), color: Number(row.close) >= Number(row.open) ? '#279c81' : '#d66a67',
      })),
    }],
  }], [cell.volume, rows])
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
  return <section className="web-cell" aria-label={'图表 ' + (slot + 1)}>
    <header className="web-cell-head">
      <select aria-label="交易对" className="web-symbol" value={cell.symbol} onChange={e => {
        if (e.target.value === '+') { setDraft(''); setEditingSymbol(true) }
        else { setEditingSymbol(false); update({ symbol: e.target.value }) }
      }}>
        {[...new Set([...symbols, cell.symbol])].map(s => <option key={s} value={s}>{s.replace(/USDT$/, ' / USDT')}</option>)}
        <option value="+">输入其他交易对…</option>
      </select>
      <strong className="web-price">{last?.close?.toLocaleString('en-US', { maximumFractionDigits: 4 }) ?? '—'}</strong>
      <span className="web-source" title={feed.status}>{replay ? 'K 线回放' : feed.status}</span>
    </header>
    {editingSymbol && <form className="web-tools" onSubmit={e => {
      e.preventDefault()
      if (validSymbol(draft)) { setEditingSymbol(false); update({ symbol: draft }) }
    }}>
      <input aria-label="Binance 交易对代码" placeholder="例如 BNBUSDT" value={draft} autoFocus maxLength={24}
        onChange={e => setDraft(e.target.value.toUpperCase().replace(/[\s/]/g, ''))} />
      <button disabled={!validSymbol(draft)}>打开</button>
      <button type="button" onClick={() => setEditingSymbol(false)}>取消</button>
    </form>}
    <div className="web-tools">
      <select aria-label="周期" value={cell.interval} onChange={e => update({ interval: e.target.value })}>
        {intervals.map(i => <option key={i}>{i}</option>)}</select>
      <select aria-label="图表类型" value={cell.style} onChange={e => update({ style: e.target.value as MainChartType })}>
        {Object.entries(styles).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select>
      <button aria-pressed={cell.ma} onClick={() => update({ ma: !cell.ma })}>MA 20</button>
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
    <SingleChartPanes key={replay ? 'replay' : 'market'} symbol={cell.symbol} interval={cell.interval} datasetKey={String(store.seriesKey)} seriesStore={store} dataMeta={dataMeta}
      theme={theme} inheritApplicationTheme={false} customBg={theme === 'dark' ? '#191c21' : '#ffffff'}
      upColor="#279c81" downColor="#d66a67" chartType={cell.style} mainOverlayLines={lines} subPanes={subPanes}
      drawingKeyBase={'web:binance:spot:' + cell.symbol + ':' + slot} drawingTool={tool} onDrawingToolChange={setTool}
      drawingsEnabled penColor="#cf9a4c" penSize={2} loading={!last && !feed.status.includes('不存在') && !feed.status.includes('失败')} timezone="UTC" />
    <footer className="web-cell-status"><span>Binance 现货 · UTC</span><span>{feed.historySource}</span>
      <span>{last && new Date(Number(last.time) * 1000).toISOString().slice(0, 16).replace('T', ' ')}</span>
      <span>{replay ? replay.index : feed.store.barCount} 根{feed.gaps > 0 && !replay ? ' · 存在历史缺口' : ''}</span>
      {feed.pageText && !replay && <span role="status">{feed.pageText}</span>}</footer>
  </section>
}

function Workspace() {
  const [layout, setLayout] = useState(readLayout)
  const [theme, setTheme] = useState(() => { try { return localStorage.getItem(settingsKey + '-theme') === 'light' ? 'light' : 'dark' } catch { return 'dark' } })
  useEffect(() => { try { localStorage.setItem(settingsKey, JSON.stringify(layout)) } catch { /* Session remains usable. */ } }, [layout])
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem(settingsKey + '-theme', theme) } catch { /* Session remains usable. */ }
  }, [theme])
  return <main className="web-workspace" data-theme={theme}>
    <header className="web-header"><div className="web-brand"><img src="./favicon.svg" alt=""/>CandleScope</div>
      <span className="web-title">网页工作台</span>
      <nav aria-label="工作区布局">{[1,2,4].map(count => <button key={count} aria-pressed={count === layout.count}
        onClick={() => setLayout({ ...layout, count })}>{count} 图</button>)}</nav>
      <button onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? '浅色' : '深色'}</button>
      <details className="web-desktop"><summary>桌面版</summary><div>完整训练回放、Python 策略回测、账户和原生插件需要桌面版。<a href={releaseUrl} target="_blank" rel="noreferrer">下载 CandleScope ↗</a></div></details>
    </header>
    <div className={'web-grid grid-' + layout.count}>{layout.cells.slice(0, layout.count).map((cell, i) =>
      <ChartCell key={i + cell.symbol + cell.interval} cell={cell} slot={i} theme={theme} update={change =>
        setLayout(prev => ({ ...prev, cells: prev.cells.map((old,j) => i === j ? { ...old, ...change } : old) }))} />)}</div>
  </main>
}
void initializeLocale('zh-CN').then(() => createRoot(document.getElementById('root')!).render(<Workspace />))
