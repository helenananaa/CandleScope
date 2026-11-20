// Run against a built static site. PLAYWRIGHT_MODULE can name an existing
// playwright-core install, and CHROME_PATH selects the native Chrome binary.
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { engineStats, openApp } from './app-frame.mjs'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core')
const url = process.argv[2] || 'http://127.0.0.1:4178/'
const profile = await mkdtemp(join(tmpdir(), 'candlescope-python-acceptance-'))
const market = 'exchange=binance&market_type=spot&symbol=BTCUSDT&interval=1h'

async function visit(offline, test) {
  const context = await chromium.launchPersistentContext(profile, {
    headless: true,
    ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}),
    args: offline
      ? [
          '--proxy-server=direct://',
          '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1',
        ]
      : [],
  })
  try {
    const page = await openApp(await context.newPage(), url)
    await page.waitForFunction(
      () => document.querySelector('canvas') || document.querySelector('#root[data-startup-failure]'),
      null,
      { timeout: 150000 }
    )
    assert.ok(await page.locator('canvas').count(), (await page.locator('body').innerText()).slice(-1000))
    await page.waitForFunction(
      () =>
        !document.querySelector('.history-study-mask') &&
        [...document.querySelectorAll('.chart-pane canvas')].some((canvas) => {
          const rect = canvas.getBoundingClientRect()
          return rect.width > 100 && rect.height > 80 && getComputedStyle(canvas).visibility === 'visible'
        }),
      null,
      { timeout: 60000 }
    )
    await test(page)
  } finally {
    await context.close()
  }
}

async function query(page, route, min) {
  const deadline = Date.now() + 150000
  let last
  do {
    last = await page.evaluate(async (path) => {
      const response = await fetch('/api/v1/klines/' + path)
      if (!response.ok)
        throw Error('HTTP ' + response.status + ': ' + (await response.text()).slice(0, 256))
      return response.json()
    }, route)
    if (last.data?.length >= min) return last
    await page.waitForTimeout(3000)
  } while (Date.now() < deadline)
  throw Error(
    'Unsettled original K-line route: ' +
      JSON.stringify({ route, count: last.count, state: last.history_state })
  )
}

function signature(rows) {
  return rows.map((bar) => [bar.time, bar.open, bar.high, bar.low, bar.close, bar.volume])
}

try {
  let saved
  const before = Math.floor(Date.now() / 3600000) * 3600 - 40 * 86400
  await visit(false, async (page) => {
    const live = await query(page, 'history?' + market + '&count_back=24', 24)
    assert.ok(live.data.every((bar) => Number.isFinite(bar.close)))
    await page.waitForFunction(
      () => document.querySelector('.chart-main-legend')?.innerText.match(/\d[\d,.]+/),
      null,
      { timeout: 60000 }
    )
    const history = await query(page, 'history/before?' + market + '&bars=32&before=' + before, 32)
    assert.ok(history.data.every((bar) => bar.time < before && bar.is_closed === true))
    saved = signature(history.data)
    const result = await page.evaluate(async (bars) => {
      const response = await fetch('/api/v1/indicators/compute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode: 'builtin',
          name: 'MA',
          ohlcv: bars,
          params: { period: 3 },
          symbol: 'BTCUSDT',
          interval: '1h',
        }),
      })
      return response.json()
    }, history.data)
    assert.equal(result.ok, true, JSON.stringify(result).slice(0, 400))
    const value = result.lines[0].data.at(-1).value
    const expected = history.data.slice(-3).reduce((total, bar) => total + bar.close, 0) / 3
    assert.ok(Math.abs(value - expected) < 1e-5)
    if (process.env.CANDLE_BROWSER_SCREENSHOT) await page.page().screenshot({ path: process.env.CANDLE_BROWSER_SCREENSHOT })
    console.log('Original market canvas, public history, older repair, desktop MA calculation passed.')
    // The shell has a memory snapshot of the imported engine made for later starts.
    let stats = await engineStats(page)
    for (let tries = 0; tries < 120 && stats.snapshot === 'missing'; tries++) {
      await page.waitForTimeout(500)
      stats = await engineStats(page)
    }
    assert.deepEqual([stats.boot, stats.snapshot], ['import', 'stored'])
  })
  await visit(true, async (page) => {
    assert.equal(
      await page.evaluate(async () => {
        try {
          await fetch('https://data-api.binance.vision/api/v3/time', {
            cache: 'no-store',
            signal: AbortSignal.timeout(4000),
          })
          return true
        } catch {
          return false
        }
      }),
      false,
      'external market network must be unavailable'
    )
    const range = await query(
      page,
      'range?' +
        market +
        '&repair=none&start_ms=' +
        saved[0][0] * 1000 +
        '&end_ms=' +
        saved.at(-1)[0] * 1000,
      saved.length
    )
    assert.deepEqual(signature(range.data), saved)
    assert.equal((await engineStats(page)).boot, 'snapshot')
    console.log(
      'After a complete browser exit, the engine restored its snapshot and all ' +
        saved.length +
        ' closed candles matched from the original storage, offline.'
    )
  })
  await visit(false, async (page) => {
    const next = await query(page, 'history/before?' + market + '&bars=12&before=' + saved[0][0], 12)
    assert.ok(next.data.every((bar) => bar.time < saved[0][0]))
    console.log('After reopening online, the original backend served the next older page.')
  })
} finally {
  await rm(profile, { recursive: true, force: true, maxRetries: 3 })
}
