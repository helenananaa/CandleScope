self.addEventListener('install', (event) => event.waitUntil(self.skipWaiting()))
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)
  if (url.origin !== self.location.origin || !/^\/api\/v[12]\//.test(url.pathname)) return
  event.respondWith(dispatch(event, url))
})
async function dispatch(event, url) {
  const client = await self.clients.get(event.clientId)
  if (
    event.request.mode === 'navigate' ||
    !client ||
    new URL(client.url).origin !== self.location.origin ||
    (event.request.headers.has('origin') && event.request.headers.get('origin') !== self.location.origin)
  ) {
    return Response.json({ detail: 'A same-origin CandleScope workspace is required' }, { status: 403 })
  }
  const channel = new MessageChannel()
  const bytes = new Uint8Array(await event.request.arrayBuffer())
  let binary = ''
  for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192))
  return new Promise((resolve) => {
    function finish(response) {
      clearTimeout(timer)
      channel.port1.close()
      resolve(response)
    }
    const timer = setTimeout(
      () => finish(Response.json({ detail: 'Browser backend timed out' }, { status: 504 })),
      95000
    )
    channel.port1.onmessage = ({ data }) => {
      if (data.error) return finish(Response.json({ detail: data.error }, { status: 503 }))
      const body = Uint8Array.from(atob(data.body), (c) => c.charCodeAt(0))
      const headers = new Headers(data.headers)
      headers.delete('content-length')
      finish(
        new Response([204, 304].includes(data.status) || event.request.method === 'HEAD' ? null : body, {
          status: data.status,
          headers,
        })
      )
    }
    client.postMessage(
      {
        type: 'candlescope.api',
        path: url.pathname,
        query: url.search,
        method: event.request.method,
        headers: [...event.request.headers].filter(
          ([name]) => !['cookie', 'authorization', 'accept-encoding'].includes(name)
        ),
        body: btoa(binary),
      },
      [channel.port2]
    )
  })
}
