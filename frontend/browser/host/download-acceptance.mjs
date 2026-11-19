// Exercise the public market download and replay entry in a disposable Chrome profile.
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core')
const url = process.argv[2] || 'http://127.0.0.1:4178/'
const profile = await mkdtemp(join(tmpdir(), 'candlescope-download-'))
const options = {
  headless: true,
  ...(process.env.CHROME_PATH && { executablePath: process.env.CHROME_PATH }),
}
const start = Date.UTC(2025, 0, 2, 0, 0)
const end = start + 25 * 60000
const saved = []
async function visit(offline, check) {
  const context = await chromium.launchPersistentContext(profile, {
    ...options,
    args: offline
      ? [
          '--proxy-server=direct://',
          '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost',
        ]
      : [],
  })
  try {
    const page = await context.newPage()
    await page.goto(new URL('replay.html', url).href)
    const form = page.getByTestId('history-download-form')
    await form.locator('..').locator('summary').click({ timeout: 150000 })
    await check(page, form)
  } finally {
    await context.close()
  }
}
try {
  await visit(false, async (page, form) => {
    for (const kind of ['bars', 'aggTrades']) {
      await form.locator('[name=kind]').selectOption(kind)
      await form.locator('[name=start]').fill(new Date(start).toISOString().slice(0, 16))
      await form.locator('[name=end]').fill(new Date(end).toISOString().slice(0, 16))
      await form.locator('button[type=submit]').click()
      await page.waitForFunction(
        () => {
          const form = document.querySelector('[data-testid=history-download-form]')
          return (
            form?.querySelector('[role=alert]') ||
            form?.querySelector('[role=status]')?.textContent.match(/已保存|Saved/)
          )
        },
        null,
        { timeout: 240000 }
      )
      assert.equal(await form.getByRole('alert').count(), 0, await form.innerText())
      const manifest = await page.evaluate(async (kind) => {
        const { datasets } = await (await fetch('/api/v1/local/datasets')).json()
        return datasets.find((d) => (kind === 'aggTrades' ? d.market_trade_input : !d.market_trade_input))
      }, kind)
      assert.ok(manifest)
      assert.equal(manifest.rows, 25)
      assert.equal(manifest.first_open_ms, start)
      assert.equal(manifest.instrument.quote_asset, 'USDT')
      if (kind === 'aggTrades') {
        const trades = manifest.market_trade_input
        assert.ok(trades.row_count > 1000, 'exercise cross-page trade history')
        assert.equal(trades.last_sequence - trades.first_sequence + 1, trades.row_count)
        console.log('Continuous aggregate trade records:', trades.row_count)
      }
      saved.push(manifest.dataset_id)
      const ready = await page.evaluate(
        async ({ kind, id, start, end }) => {
          const api = async (path, body) => {
            const response = await fetch(
              '/api/v1/' + path,
              body
                ? {
                    method: 'POST',
                    headers: { 'content-type': 'application/json' },
                    body: JSON.stringify(body),
                  }
                : {}
            )
            const value = await response.json()
            if (!response.ok) throw Error(JSON.stringify(value).slice(0, 500))
            return value
          }
          const setup = {
            protocol: 'replay.v3',
            name: 'Downloaded ' + kind,
            source_kind: kind === 'bars' ? 'BAR' : 'AGG_TRADE',
            start_mode: 'MANUAL',
            settlement_asset: 'USDT',
            requested_start_ms: start + 4 * 60000,
            indicator_warmup_bars: 2,
            visible_history_lookback: { mode: 'DURATION', duration_ms: 120000 },
            forward_cache_ms: 180000,
            initial_equity: '10000',
            max_leverage: '3',
            maker_fee_bps: '2',
            taker_fee_bps: '5',
            market_slippage_bps: '1',
            integrity_mode: 'CHALLENGE',
            time_disclosure_policy: 'HIDE_ALL',
            book_mode: 'OFF',
            margin_mode: 'CROSS',
            funding_mode: 'OFF',
            allow_rule_changes: false,
          }
          const run = (await api('replay/runs', setup)).run.run_id
          const root = 'replay/runs/' + run
          const catalog = await api(root + '/market-catalog')
          const entry = catalog.entries.find((e) => e.identity.exchange === id)
          if (!entry) throw Error('Downloaded dataset missing from replay catalog')
          const selected = await api(root + '/markets', {
            catalog_epoch: catalog.catalog_epoch,
            ...entry.identity,
            base_interval: '1m',
            display_interval: '1m',
          })
          return selected.run.last_symbol
        },
        { kind, id: manifest.dataset_id, start, end }
      )
      assert.equal(ready, 'BTCUSDT')
      console.log(kind, 'downloaded and started a BTCUSDT replay:', manifest.rows, 'bars')
    }
  })
  await visit(true, async (page) => {
    const result = await page.evaluate(
      async ({ start, end }) => {
        const ids = []
        for (const kind of ['bars', 'aggTrades']) {
          const r = await fetch('/api/v1/local/downloads', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ symbol: 'BTCUSDT', kind, start_ms: start, end_ms: end }),
          })
          const v = await r.json()
          if (v.status !== 'complete') throw Error(JSON.stringify(v))
          ids.push(v.dataset.dataset_id)
        }
        return ids
      },
      { start, end }
    )
    assert.deepEqual(result, saved)
    console.log(
      'After a full Chrome restart both ranges reused their original dataset IDs with exchange DNS blocked.'
    )
  })
} finally {
  await rm(profile, { recursive: true, force: true, maxRetries: 3 })
}
