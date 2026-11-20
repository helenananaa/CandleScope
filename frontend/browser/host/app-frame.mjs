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
          resolve({ instance: data.instance, boot: data.boot, snapshot: data.snapshot, sockets: data.sockets, tasks: data.tasks })
        }
        worker.port.postMessage({ id, kind: 'stats' })
      })
    } finally {
      worker.port.close()
    }
  })
}
