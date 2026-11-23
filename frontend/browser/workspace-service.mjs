// Let the previous transport finish serving its existing tabs before activating.
self.addEventListener('message', ({ data, ports }) => {
  if (data?.type === 'candlescope.transport' && ports[0]) {
    ports[0].postMessage(2)
    ports[0].close()
  }
})
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
  const body = await event.request.arrayBuffer()
  return new Promise((resolve) => {
    let stream
    const abort = () => {
      channel.port1.postMessage({ type: 'abort' })
      channel.port1.close()
    }
    function finish(response) {
      clearTimeout(timer)
      channel.port1.close()
      resolve(response)
    }
    const expire = () => {
      abort()
      finish(Response.json({ detail: 'Browser backend timed out' }, { status: 504 }))
    }
    // A page shows before the engine has started, so its first requests wait
    // for the start. The limit on a request counts from when the engine takes it.
    let timer = setTimeout(expire, 250000)
    channel.port1.onmessage = ({ data }) => {
      if (data.type === 'accepted') {
        clearTimeout(timer)
        timer = setTimeout(expire, 95000)
        return
      }
      if (stream) {
        if (data.type === 'chunk') stream.enqueue(Uint8Array.from(atob(data.body), (c) => c.charCodeAt(0)))
        else {
          if (data.error) stream.error(Error(data.error))
          else stream.close()
          channel.port1.close()
        }
        return
      }
      if (data.type === 'start') {
        clearTimeout(timer)
        const body = new ReadableStream({
          start(controller) {
            stream = controller
          },
          cancel: abort,
        })
        resolve(new Response(body, { status: data.status, headers: data.headers }))
        return
      }
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
        // This worker understands the engine's { type: 'accepted' }.
        accepts: true,
        path: url.pathname,
        query: url.search,
        method: event.request.method,
        headers: [...event.request.headers].filter(
          ([name]) => !['cookie', 'authorization', 'accept-encoding'].includes(name)
        ),
        body,
      },
      [channel.port2, body]
    )
  })
}
