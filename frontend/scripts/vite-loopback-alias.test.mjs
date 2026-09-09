import assert from 'node:assert/strict'
import { once } from 'node:events'
import { createServer, get } from 'node:http'
import { createServer as createHttpsServer } from 'node:https'
import { createConnection } from 'node:net'
import test from 'node:test'
import { attachLoopbackAlias } from './vite-loopback-alias.mjs'

test('loopback alias forwards HTTP and upgrades and closes with its owner', async context => {
  const primary = createServer((request, response) => {
    response.setHeader('x-origin', request.headers.origin ?? '')
    response.end(request.url)
  })
  primary.on('upgrade', (_request, socket) => socket.end('HTTP/1.1 101 Switching Protocols\r\nConnection: close\r\n\r\n'))
  const alias = attachLoopbackAlias(primary)
  context.after(() => { alias.close(); primary.closeAllConnections(); primary.close() })
  primary.listen(0, '127.0.0.1')
  await once(primary, 'listening')
  const address = await alias.ready
  if (address === null) { context.skip('IPv6 loopback unavailable on this host'); return }
  assert.equal(address.address, '::1')
  assert.equal(address.port, primary.address().port)
  const result = await new Promise((resolve, reject) => {
    get({ host: '::1', port: address.port, path: '/replay.html?run=test', headers: { origin: 'http://localhost' }, agent: false }, response => {
      let body = ''
      response.on('data', chunk => { body += chunk })
      response.on('end', () => resolve({ body, origin: response.headers['x-origin'] }))
    }).on('error', reject)
  })
  assert.deepEqual(result, { body: '/replay.html?run=test', origin: 'http://localhost' })
  const socket = createConnection({ host: '::1', port: address.port })
  context.after(() => socket.destroy())
  await once(socket, 'connect')
  socket.write('GET /ws HTTP/1.1\r\nHost: localhost\r\nConnection: Upgrade\r\nUpgrade: test\r\n\r\n')
  const [data] = await once(socket, 'data')
  assert.match(data.toString(), /^HTTP\/1.1 101/)
  const closed = once(primary, 'close')
  primary.close()
  await closed
  alias.close() // idempotent
})

test('wildcard listeners do not create an extra listener', async context => {
  const primary = createServer()
  context.after(() => primary.close())
  const alias = attachLoopbackAlias(primary)
  primary.listen(0, '0.0.0.0')
  await once(primary, 'listening')
  assert.equal(await alias.ready, null)
})

test('HTTPS never gets an unencrypted alias', async context => {
  const primary = createHttpsServer()
  context.after(() => primary.close())
  const alias = attachLoopbackAlias(primary)
  primary.listen(0, '127.0.0.1')
  await once(primary, 'listening')
  assert.equal(await alias.ready, null)
  await alias.close()
})
