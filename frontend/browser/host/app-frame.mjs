// A top-level visit opens the shell, which keeps the Python engine alive and
// shows the application pages in one same-origin frame. Acceptance scripts
// drive that frame. The Frame object survives navigations inside it.
export const APP_FRAME = 'candlescope-page'

export async function appFrame(page, timeout = 30000) {
  const element = await page.waitForSelector(`iframe[name="${APP_FRAME}"]`, { state: 'attached', timeout })
  return element.contentFrame()
}

export async function openApp(page, href) {
  await page.goto(href)
  return appFrame(page)
}

// Ask the shared engine for its identity and open application sockets.
export function engineStats(frame) {
  return frame.evaluate(async () => {
    const worker = new SharedWorker(document.documentElement.dataset.engineScript, {
      type: 'module',
      name: 'candlescope-python',
    })
    worker.port.start()
    try {
      return await new Promise((resolve, reject) => {
        const id = 2 ** 40 + Math.floor(Math.random() * 2 ** 20)
        const timer = setTimeout(() => reject(Error('Engine stats timed out')), 20000)
        worker.port.onmessage = ({ data }) => {
          if (data.id !== id) return
          clearTimeout(timer)
          resolve({
            instance: data.instance,
            boot: data.boot,
            snapshot: data.snapshot,
            catalog: data.catalog,
            files: data.files,
            sockets: data.sockets,
            tasks: data.tasks,
          })
        }
        worker.port.postMessage({ id, kind: 'stats' })
      })
    } finally {
      worker.port.close()
    }
  })
}

// Acceptance scripts run in Chromium unless BROWSER names Playwright's WebKit.
// A visit is a browser context over the script's profile; closing it ends the
// engine, as quitting the browser does. An offline visit reaches only this
// machine.
//
// Playwright's WebKit cannot start with a profile directory on every macOS, so
// a script's visits share one context and closing a visit closes its pages.
// Its Cache Storage does not outlive the last page: later visits import the
// backend instead of restoring a snapshot. Offline, it aborts requests to other
// hosts, but not those of pages a service worker controls. A visit reports both
// limits (blocksNetwork, keepsSnapshots) so that checks skip what it cannot show.
// Playwright's Firefox lets page requests bypass the service worker that
// carries the application's HTTP requests, so it cannot run these checks.
let webkit
export async function launchVisit(playwright, profile, { offline = false } = {}) {
  const name = process.env.BROWSER || 'chromium'
  if (name === 'chromium') {
    const context = await playwright.chromium.launchPersistentContext(profile, {
      headless: true,
      ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}),
      args: offline
        ? ['--proxy-server=direct://', '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost']
        : [],
    })
    return Object.assign(context, { blocksNetwork: offline, keepsSnapshots: true })
  }
  if (name !== 'webkit') throw Error(`BROWSER=${name} is not supported; use chromium or webkit`)
  webkit ??= await (await playwright.webkit.launch({ headless: true })).newContext()
  await webkit.unrouteAll()
  const local = (url) => ['127.0.0.1', 'localhost'].includes(url.hostname)
  if (offline) await webkit.route((url) => !local(url), (route) => route.abort('internetdisconnected'))
  return {
    blocksNetwork: false,
    keepsSnapshots: false,
    newPage: () => webkit.newPage(),
    async close() {
      for (const page of webkit.pages()) await page.close()
      // The engine's shared worker ends once no page holds it.
      await new Promise((resolve) => setTimeout(resolve, 3000))
    },
  }
}

export async function closeBrowsers() {
  await webkit?.browser().close()
  webkit = undefined
}
