// Moving between the market, research and replay pages keeps one running
// Python engine, mirrors the page into the address bar and closes the
// previous page's application sockets.
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { appFrame, closeBrowsers, engineStats, launchVisit, openApp } from './app-frame.mjs'

const playwright = createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE || 'playwright-core')
const url = process.argv[2] || 'http://127.0.0.1:4178/'
const limit = Number(process.env.CANDLE_PAGE_SWITCH_MS || 10000)
const profile = await mkdtemp(join(tmpdir(), 'candlescope-page-switch-'))
const links = { market: 'a[href="/"]', research: 'a[href="/strategy.html"]', replay: 'a[href="/replay.html"]' }
const current = (name) => (frame) =>
  frame.locator('nav.workspace-navigation ' + links[name] + '[aria-current=page]').waitFor({ timeout: limit })
const pages = {
  market: {
    path: (path) => path === '/' || path.endsWith('/index.html'),
    ready: async (frame) => {
      await current('market')(frame)
      await frame.locator('.chart-pane canvas').first().waitFor({ timeout: limit })
    },
  },
  research: { path: (path) => path.endsWith('/strategy.html'), ready: current('research') },
  replay: { path: (path) => path.endsWith('/replay.html'), ready: current('replay') },
}

async function engine(frame) {
  return frame.locator('html').getAttribute('data-engine-instance')
}

async function expectPage(tab, frame, name, instance) {
  const started = Date.now()
  await frame.waitForURL((target) => pages[name].path(target.pathname), { timeout: limit })
  await pages[name].ready(frame)
  const elapsed = Date.now() - started
  assert.equal(await engine(frame), instance, name + ' restarted the engine')
  assert.ok(pages[name].path(new URL(tab.url()).pathname), 'address bar shows ' + tab.url())
  assert.equal(await tab.title(), await frame.title())
  return elapsed
}

const context = await launchVisit(playwright, profile)
try {
  const tab = await context.newPage()
  const started = Date.now()
  const app = await openApp(tab, url)
  await app.locator('.chart-pane canvas').first().waitFor({ timeout: 150000 })
  await app.locator('html[data-engine-instance]').waitFor({ state: 'attached' })
  const instance = await engine(app)
  console.log('Cold start to the market chart:', Date.now() - started, 'ms')
  await app.waitForTimeout(5000)
  const baseline = await engineStats(app)
  assert.equal(baseline.instance, instance)

  for (const [from, to] of [
    ['market', 'research'],
    ['research', 'replay'],
    ['replay', 'market'],
    ['market', 'research'],
    ['research', 'market'],
  ]) {
    await app.locator(links[to]).first().click()
    const elapsed = await expectPage(tab, app, to, instance)
    console.log(`Switched ${from} → ${to} with the same engine in ${elapsed} ms`)
  }
  await app.waitForTimeout(5000)
  const after = await engineStats(app)
  assert.equal(after.instance, instance)
  assert.ok(after.sockets <= baseline.sockets, `sockets ${baseline.sockets} → ${after.sockets}`)
  console.log(`Application sockets after five switches: ${baseline.sockets} → ${after.sockets}`)

  // The browser buttons traverse the frame's entries in the tab's history.
  await tab.evaluate(() => history.back())
  await expectPage(tab, app, 'research', instance)
  await tab.evaluate(() => history.forward())
  await expectPage(tab, app, 'market', instance)
  console.log('Back and forward moved the page frame and the address bar together.')

  const second = await context.newPage()
  const replay = await openApp(second, new URL('replay.html', url).href)
  const opened = await expectPage(second, replay, 'replay', instance)
  console.log('A second tab joined the running engine in', opened, 'ms')

  await tab.reload()
  const reloaded = await appFrame(tab)
  await expectPage(tab, reloaded, 'market', instance)
  console.log('Reloading one tab kept the engine that the other tab holds.')
} finally {
  await context.close()
  await closeBrowsers()
  await rm(profile, { recursive: true, force: true, maxRetries: 3 })
}
