import { createServer } from 'node:http'
import { Server as HttpsServer } from 'node:https'

/** Serve both loopback families without changing the browser origin or
 * widening a loopback-only Vite server to the network interfaces. */
export function attachLoopbackAlias(primary, warn = () => {}) {
  let alias = null
  let stopped = false
  let resolveReady
  let resolveClosed
  const sockets = new Set()
  const ready = new Promise(resolve => { resolveReady = resolve })
  const closed = new Promise(resolve => { resolveClosed = resolve })
  const close = () => {
    if (stopped) return closed
    stopped = true
    primary?.off('listening', start)
    for (const socket of sockets) socket.destroy()
    if (alias) alias.close(() => resolveClosed())
    else resolveClosed()
    resolveReady(null)
    return closed
  }
  const start = () => {
    if (stopped) return
    const address = primary.address()
    const host = address && typeof address !== 'string'
      ? address.address === '127.0.0.1' ? '::1'
        : address.address === '::1' ? '127.0.0.1' : null
      : null
    if (host === null || primary instanceof HttpsServer) {
      resolveReady(null)
      return
    }
    alias = createServer((request, response) => primary.emit('request', request, response))
    alias.on('upgrade', (request, socket, head) => primary.emit('upgrade', request, socket, head))
    alias.on('connection', socket => {
      sockets.add(socket)
      socket.once('close', () => sockets.delete(socket))
    })
    alias.once('error', error => {
      warn(`Loopback alias unavailable (${error.code ?? error.message}); primary listener remains active.`)
      close()
    })
    alias.once('listening', () => resolveReady(alias.address()))
    alias.listen({ host, port: address.port, ipv6Only: host === '::1' })
  }
  if (!primary) resolveReady(null)
  else {
    primary.once('close', close)
    if (primary.listening) start()
    else primary.once('listening', start)
  }
  return { ready, close }
}

export function loopbackAliasPlugin() {
  const aliases = new Set()
  const attach = server => {
    aliases.add(attachLoopbackAlias(server.httpServer, message => server.config.logger.warn(message)))
  }
  return {
    name: 'loopback-alias', configureServer: attach, configurePreviewServer: attach,
    async closeBundle() {
      await Promise.all([...aliases].map(alias => alias.close()))
      aliases.clear()
    },
  }
}
