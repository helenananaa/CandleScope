// Verify the same user action with cold, overlapping, and offline local coverage.
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { closeBrowsers, launchVisit, openApp } from './app-frame.mjs'

const playwright = createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE || 'playwright-core')
const url = new URL('replay.html', process.argv[2] || 'http://127.0.0.1:4178/')
const profile = await mkdtemp(join(tmpdir(), 'candlescope-start-'))
const epoch = Date.UTC(2025, 0, 2)
const minute = 60000
const instant = (m) => epoch + m * minute
const utc = (m) => new Date(instant(m)).toISOString().slice(0, 16).replace('T', ' ')
const saved = {}
async function check(offline) {
  const ctx = await launchVisit(playwright, profile, { offline })
  try {
    const tab = await ctx.newPage()
    let p
    tab.on('response', async (response) => {
      if (!response.url().includes('/data-preparations/') || response.request().method() !== 'GET') return
      try {
        const body = await response.json()
        if (body.state === 'FAILED') console.error('Preparation failed:', body.error)
      } catch {}
    })
    // Start replay prepares its own history. It must not submit a library
    // download or CSV import; listing the downloadable markets is a read.
    const imports = []
    tab.on('request', (r) => {
      if (r.method() === 'POST' && (r.url().includes('/local/downloads') || r.url().includes('/imports/csv')))
        imports.push(r.url())
    })
    async function start(kind, from, until, gaps) {
      console.log('Start', kind, utc(from), utc(until))
      p = await openApp(tab, url.href)
      await p.getByRole('button', { name: '新建训练', exact: true }).click({ timeout: 150000 })
      const dialog = p.locator('.training-hub-create')
      const field = dialog.locator('[data-training-field=requested-start-utc]')
      await field.waitFor({ timeout: 30000 })
      await dialog.getByRole('radio', { name: kind === 'bars' ? 'K 线' : '成交', exact: true }).click()
      const symbolInput = dialog.getByLabel('商品', { exact: true })
      await symbolInput.fill('BTCUSDT')
      await field.fill(utc(from))
      await field.press('Tab')
      const end = dialog.locator('[data-training-field=end-utc]')
      await end.fill(utc(until))
      await end.press('Tab')
      const submission = tab.waitForResponse(
        (r) => r.request().method() === 'POST' && r.url().endsWith('/data-preparations/replay')
      )
      await dialog.getByRole('button', { name: '开始回放', exact: true }).click({ timeout: 30000 })
      const res = await submission
      const initial = await res.json()
      assert.equal(res.status(), 202, JSON.stringify(initial))
      try {
        await p.waitForURL('**/*run=*', { timeout: 180000 })
      } catch (error) {
        console.error(await p.locator('body').innerText())
        throw error
      }
      await p.waitForFunction(
        () =>
          [...document.querySelectorAll('[data-replay-cell-bars]')].some(
            (el) => Number(el.dataset.replayCellBars) > 0
          ),
        null,
        { timeout: 90000 }
      )
      const job = await p.evaluate(
        async (id) => (await fetch('/api/v1/data-preparations/' + id)).json(),
        initial.id
      )
      assert.equal(job.state, 'READY')
      assert.equal(job.result.run.last_symbol, 'BTCUSDT')
      assert.deepEqual(
        job.result.missing_ranges,
        gaps.map(([a, b]) => [instant(a), instant(b)])
      )
      assert.deepEqual(imports, [])
      const id = job.result.inputs[0].dataset_id
      if (offline) assert.equal(id, saved[kind])
      saved[kind] = id
      console.log(
        kind,
        offline ? 'offline' : 'online',
        utc(from),
        utc(until),
        'opened chart; missing UTC minute ranges',
        JSON.stringify(gaps)
      )
    }
    for (const kind of ['bars', 'trades']) {
      if (offline) await start(kind, 9, 15, [])
      else {
        await start(kind, 5, 12, [[0, 12]])
        await start(kind, 8, 18, [[12, 18]])
      }
    }
  } finally {
    await ctx.close()
  }
}
try {
  await check(false)
  await check(true)
} finally {
  await closeBrowsers()
  await rm(profile, { recursive: true, force: true, maxRetries: 3 })
}
