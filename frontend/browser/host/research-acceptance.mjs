// Run against a static build, using the same Chrome configuration as acceptance.mjs.
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { closeBrowsers, launchVisit, openApp } from './app-frame.mjs'

const require = createRequire(import.meta.url)
const playwright = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core')
const url = process.argv[2] || 'http://127.0.0.1:4178/'
const profile = await mkdtemp(join(tmpdir(), 'candlescope-library-'))
const start = 1760000400000
const minute = 60000
let dataset, session, account, run, cursor, journal
async function visit(check) {
  const context = await launchVisit(playwright, profile)
  try {
    const page = await openApp(await context.newPage(), new URL('strategy.html?action=import', url).href)
    await page.getByTestId('research-data-drawer').waitFor({ timeout: 150000 })
    async function api(path, body, status = 200) {
      const [code, value] = await page.evaluate(
        async ({ path, body }) => {
          const csv = typeof body === 'string'
          const r = await fetch(
            '/api/v1/' + path,
            body === undefined
              ? {}
              : {
                  method: 'POST',
                  body: csv ? body : JSON.stringify(body),
                  headers: { 'content-type': csv ? 'text/csv' : 'application/json' },
                }
          )
          return [r.status, await r.json()]
        },
        { path, body }
      )
      assert.equal(code, status, path + ' ' + JSON.stringify(value).slice(0, 600))
      return value
    }
    await check(page, api)
  } finally {
    await context.close()
  }
}
try {
  await visit(async (page, api) => {
    // Cross an ASGI chunk boundary inside a UTF-8 CSV upload.
    const annotation = '数据'.repeat(2000)
    const csv =
      'time,open,high,low,close,volume,annotation\n' +
      Array.from({ length: 30 }, (_, i) =>
        [start + i * minute, 100 + i, 105 + i, 95 + i, 101 + i, 5, annotation].join(',')
      ).join('\n')
    const job = await api(
      'local/imports/csv/jobs?name=Browser%20BAR&symbol=BTCUSDT&interval=1m&timestamp_unit=ms&base_asset=BTC&quote_asset=USDT',
      csv,
      202
    )
    let outcome
    for (let i = 0; i < 60; i++) {
      outcome = await api('local/imports/jobs/' + job.job_id)
      if (!['queued', 'running'].includes(outcome.status)) break
      await page.waitForTimeout(250)
    }
    assert.equal(outcome.status, 'completed', JSON.stringify(outcome.error))
    dataset = outcome.dataset.dataset_id
    assert.equal((await api('backtests/datasets')).datasets[0].dataset_id, dataset)
    const series = await api('local/datasets/' + dataset + '/klines/history?interval=1m')
    assert.equal(series.data.length, 30)
    assert.equal(Number(series.data.at(-1).close), 130)
    console.log(
      'Imported 30 bars via the original background job and read the same dataset in strategy research.'
    )

    const setup = {
      protocol: 'replay.v3',
      name: 'Browser BAR',
      source_kind: 'BAR',
      start_mode: 'MANUAL',
      settlement_asset: 'USDT',
      requested_start_ms: start + 4 * minute,
      indicator_warmup_bars: 2,
      visible_history_lookback: { mode: 'DURATION', duration_ms: 2 * minute },
      forward_cache_ms: 5 * minute,
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
    const created = await api('replay/runs', setup, 201)
    run = created.run.run_id
    const root = 'replay/runs/' + run
    const catalog = await api(root + '/market-catalog')
    const entry = catalog.entries.find((e) => e.identity.exchange === dataset)
    const selected = await api(
      root + '/markets',
      {
        catalog_epoch: catalog.catalog_epoch,
        ...entry.identity,
        base_interval: '1m',
        display_interval: '1m',
      },
      201
    )
    session = 'replay/runs/session/' + selected.run.adapter_session_id
    const before = (await api(session)).snapshot
    const command = (type, revision, payload) =>
      api(session + '/commands', {
        protocol: 'replay.v1',
        command_id: 'test-' + type,
        client_instance_id: 'research-browser',
        type,
        expected_revision: revision,
        payload,
      })
    const acquired = await command('acquire_controller', before.revision, {})
    const stepped = await command('step', acquired.revision, { count: 1 })
    cursor = stepped.cursor
    assert.ok(cursor.virtual_time_ms > before.cursor.virtual_time_ms)
    console.log(
      'Created a training run, selected imported BAR data, acquired control and advanced the replay.'
    )

    const restored = await page.evaluate(async (manifest) => {
      const packed = await fetch('/api/v1/local/projects/' + manifest.dataset_id + '/export', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          data_epoch: manifest.data_epoch,
          client_state: {
            schema_version: 1,
            events: [],
            indicators: [],
            drawings: [],
            settings: {},
          },
        }),
      })
      if (!packed.ok) throw Error(await packed.text())
      const response = await fetch('/api/v1/local/projects/import', {
        method: 'POST',
        headers: { 'content-type': 'application/vnd.candlescope.local-project+zip' },
        body: await packed.blob(),
      })
      if (!response.ok) throw Error(await response.text())
      return response.json()
    }, outcome.dataset)
    assert.equal(restored.identity_changed, true)
    assert.notEqual(restored.dataset_id, dataset)
    assert.deepEqual(
      (await api('local/datasets/' + restored.dataset_id + '/klines/history?interval=1m')).data,
      series.data
    )
    console.log('Exported the portable project and imported a separate copy with the same candles.')

    const tapeCsv =
      'time,sequence,price,quantity,is_buyer_maker\n' +
      Array.from({ length: 30 }, (_, i) =>
        [start + i * minute + 1000, 10000 + i, 100 + i, 1, 'true'].join(',')
      ).join('\n')
    const tape = await api(
      'local/imports/market-trades/csv?name=Trades&symbol=ETHUSDT&base_asset=ETH&quote_asset=USDT&timestamp_unit=ms&trade_kind=MARKET_TRADE&coverage_start_ms=' +
        start +
        '&coverage_end_ms=' +
        (start + 30 * minute),
      tapeCsv,
      201
    )
    const tapeRun = (await api('replay/runs', { ...setup, source_kind: 'AGG_TRADE' }, 201)).run.run_id
    const tapeRoot = 'replay/runs/' + tapeRun
    const tapeCatalog = await api(tapeRoot + '/market-catalog')
    const tapeEntry = tapeCatalog.entries.find((e) => e.identity.exchange === tape.dataset_id)
    assert.ok(tapeEntry)
    const tapeSelected = await api(
      tapeRoot + '/markets',
      {
        catalog_epoch: tapeCatalog.catalog_epoch,
        ...tapeEntry.identity,
        base_interval: '1m',
        display_interval: '1m',
      },
      201
    )
    assert.equal(tapeSelected.run.last_symbol, 'ETHUSDT')
    console.log('Started a second training run from imported trade prints.')
    account = (await api('trading/accounts', { kind: 'practice', name: 'Browser practice' })).id
    const snapshot = await page.evaluate(async (id) => {
      const r = await fetch('/api/v1/trading/accounts/' + id + '/events', {
        signal: AbortSignal.timeout(15000),
      })
      const reader = r.body.getReader()
      try {
        let line = ''
        const decoder = new TextDecoder()
        while (!line.includes('\n')) {
          const { value, done } = await reader.read()
          if (done) throw Error('Missing account snapshot')
          line += decoder.decode(value, { stream: true })
        }
        return JSON.parse(line.split('\n')[0])
      } finally {
        await reader.cancel()
      }
    }, account)
    assert.equal(snapshot.identity.accountId, account)
    journal = 'Trading journal from browser'
    await api('trading/accounts/' + account + '/journal', {
      kind: 'quick',
      exchange: 'binance',
      marketType: 'spot',
      symbol: 'BTCUSDT',
      body: journal,
    })
    await api('readonly-accounts', undefined, 501)
    await api('backtests/runs', {}, 501)
    console.log(
      'Received the practice account live snapshot, wrote a journal note and checked desktop-only routes.'
    )
  })
  await visit(async (page, api) => {
    await page.getByTestId('research-dataset-' + dataset).waitFor()
    assert.equal((await api('local/datasets/' + dataset + '/klines/history?interval=1m')).data.length, 30)
    assert.deepEqual((await api(session)).snapshot.cursor, cursor)
    assert.ok((await api('replay/runs')).items.some((item) => item.run_id === run))
    assert.ok(JSON.stringify(await api('trading/accounts/' + account + '/journal')).includes(journal))
    await page.goto(new URL('replay.html?run=' + encodeURIComponent(run), url).href)
    await page.waitForFunction(
      () =>
        [...document.querySelectorAll('[data-replay-cell-bars]')].some(
          (cell) =>
            Number(cell.getAttribute('data-replay-cell-bars')) > 0 &&
            !cell.getAttribute('data-replay-cell-error')
        ),
      null,
      { timeout: 90000 }
    )
    assert.ok(await page.locator('canvas:visible').count())
    console.log('Opened the saved training in the desktop replay UI with visible chart data.')
    console.log(
      'After a full Chrome restart the library, replay cursor, practice account and journal were restored.'
    )
  })
} finally {
  await closeBrowsers()
  await rm(profile, { recursive: true, force: true, maxRetries: 3 })
}
