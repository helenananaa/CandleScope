// Check switching the real replay form, including same-symbol cache isolation.
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE || 'playwright-core')
const url = new URL('replay.html', process.argv[2] || 'http://127.0.0.1:4178/')
const browser = await chromium.launch({
  headless: true,
  ...(process.env.CHROME_PATH && { executablePath: process.env.CHROME_PATH }),
})
const context = await browser.newContext()
const start = Math.floor((Date.now() - 86400000) / 60000) * 60000
const utc = (ms) => new Date(ms).toISOString().slice(0, 16).replace('T', ' ')
const ids = new Map()
try {
  // Keep a hub tab open; all sessions use the same origin-qualified library.
  const hub = await context.newPage()
  await hub.goto(url.href)
  await hub.getByRole('button', { name: '新建训练', exact: true }).waitFor({ timeout: 150000 })
  const page = await context.newPage()
  for (const [exchange, market, symbol, kind] of [
    ['binance', 'spot', 'ETHUSDT', 'BAR'],
    ['binance', 'futures', 'ETHUSDT', 'BAR'],
    ['bybit', 'swap.linear', 'ETH/USDT:USDT', 'BAR'],
    ['bitget', 'swap.linear', 'ETH/USDT:USDT', 'BAR'],
    ['okx', 'futures', 'LTC-USDT-SWAP', 'AGG_TRADE'],
    ['binance', 'futures', 'ETHUSDT', 'BAR'],
  ]) {
    console.log('Starting', exchange, market, symbol, kind)
    await page.goto(url.href)
    await page.getByRole('button', { name: '新建训练', exact: true }).click({ timeout: 150000 })
    const dialog = page.locator('.training-hub-create')
    await dialog.getByLabel('交易所', { exact: true }).selectOption(exchange, { timeout: 45000 })
    await dialog.getByLabel('市场类型', { exact: true }).selectOption(market)
    await dialog.getByLabel('商品', { exact: true }).fill(symbol)
    await dialog.getByRole('radio', { name: kind === 'BAR' ? 'K 线' : '成交', exact: true }).click()
    const first = dialog.locator('[data-training-field=requested-start-utc]')
    await first.fill(utc(start))
    await first.press('Tab')
    const end = dialog.locator('[data-training-field=end-utc]')
    await end.fill(utc(start + 120000))
    await end.press('Tab')
    const submitted = page.waitForResponse(
      (r) => r.url().endsWith('/data-preparations/replay') && r.request().method() === 'POST'
    )
    await dialog.getByRole('button', { name: '开始回放', exact: true }).click()
    const initial = await (await submitted).json()
    assert.equal(initial.request.requirements[0].exchange, exchange)
    assert.equal(initial.request.requirements[0].market_type, market)
    const reportFailure = page
      .waitForResponse(
        async (response) => {
          if (!response.url().endsWith('/data-preparations/' + initial.id)) return false
          try {
            return (await response.json()).state === 'FAILED'
          } catch {
            return false
          }
        },
        { timeout: 210000 }
      )
      .then(async (response) => {
        throw Error(JSON.stringify((await response.json()).error))
      })
    try {
      await Promise.race([page.waitForURL('**/*run=*', { timeout: 210000 }), reportFailure])
    } catch (error) {
      console.log(await page.locator('body').innerText())
      throw error
    }
    await page.waitForFunction(
      () =>
        [...document.querySelectorAll('[data-replay-cell-bars]')].some(
          (c) => Number(c.dataset.replayCellBars) > 0
        ),
      null,
      { timeout: 90000 }
    )
    const job = await page.evaluate(
      async (id) => (await fetch('/api/v1/data-preparations/' + id)).json(),
      initial.id
    )
    assert.equal(job.state, 'READY')
    const receipt = job.result.inputs[0].dataset_id
    const identity = [exchange, market, symbol, kind].join('|')
    if (ids.has(identity)) {
      assert.equal(receipt, ids.get(identity))
      assert.deepEqual(job.result.missing_ranges, [])
    } else {
      assert.ok(![...ids.values()].includes(receipt))
      ids.set(identity, receipt)
    }
    console.log('Visible replay chart', identity, receipt)
  }
} finally {
  await browser.close()
}
