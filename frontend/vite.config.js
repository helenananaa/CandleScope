import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import process from 'node:process'
import { realpathSync, readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { Agent as HttpAgent } from 'node:http'
import { Agent as HttpsAgent } from 'node:https'
import { resolve } from 'node:path'
import { loopbackAliasPlugin } from './scripts/vite-loopback-alias.mjs'
import { desktopRuntimeConfigPlugin } from './desktop/runtime-config.mjs'

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:18080'
const devServerPort = Number(process.env.VITE_DEV_PORT || 15173)
// Use the same physical root for Vite and HTML inputs when the checkout is
// reached through a drive alias or junction.
const frontendRoot = realpathSync.native(import.meta.dirname)
const appVersion = readFileSync(new URL('../backend/app/core/version.py', import.meta.url), 'utf8').match(/APP_VERSION = "([^"]+)"/)[1]
let appBuild = 'unknown'
try {
  const gitOptions = { cwd: import.meta.dirname, encoding: 'utf8', windowsHide: true }
  appBuild = execFileSync('git', ['rev-parse', '--short=12', 'HEAD'], gitOptions).trim()
  if (execFileSync('git', ['status', '--porcelain', '--untracked-files=normal'], gitOptions).trim()) appBuild += '-dirty'
} catch { /* source archives have no Git metadata */ }
const dependencyRoot = realpathSync(resolve(import.meta.dirname, 'node_modules'))
const replaySoakProjectionEnabled = process.env.VITE_REPLAY_SOAK_PROJECTION_ENABLED === '1'
// The upstream owns its keep-alive deadline (Uvicorn defaults to five seconds),
// while Vite has no authoritative view of that deadline. Reusing a socket at
// the close boundary can turn an otherwise safe API request into a bodyless
// proxy 500, so the development/preview proxy must use a fresh upstream
// connection for every request.
const proxyAgentOptions = { keepAlive: false, maxSockets: 32 }
const apiProxyAgent = new URL(apiProxyTarget).protocol === 'https:'
  ? new HttpsAgent(proxyAgentOptions)
  : new HttpAgent(proxyAgentOptions)
const buildApiProxy = () => ({
  '/api': {
    target: apiProxyTarget,
    // Keep the browser Origin so LIVE local-library access can reject LAN
    // pages even when the TCP peer is Vite on 127.0.0.1. Host may be rewritten
    // to the backend; Origin is not an authentication substitute, but it is
    // the browser identity the backend must see.
    changeOrigin: true,
    ws: true,
    agent: apiProxyAgent,
  },
})

// https://vite.dev/config/
export default defineConfig({
  root: frontendRoot,
  define: {
    'import.meta.env.VITE_APP_VERSION': JSON.stringify(appVersion),
    'import.meta.env.VITE_APP_BUILD': JSON.stringify(appBuild),
  },
  base: process.env.VITE_DESKTOP_BUILD === '1' ? './' : '/',
  plugins: [react(), loopbackAliasPlugin(), desktopRuntimeConfigPlugin()],
  build: {
    rollupOptions: {
      ...(replaySoakProjectionEnabled
        ? { preserveEntrySignatures: 'strict' }
        : {}),
      input: {
        live: resolve(frontendRoot, 'index.html'),
        replay: resolve(frontendRoot, 'replay.html'),
        local: resolve(frontendRoot, 'local.html'),
        backtest: resolve(frontendRoot, 'backtest.html'),
        strategy: resolve(frontendRoot, 'strategy.html'), // canonical; local/backtest stay one release cycle
        ...(replaySoakProjectionEnabled
          ? {
              replaySoakProjection: resolve(
                frontendRoot,
                'scripts/replay-soak-projection.ts',
              ),
            }
          : {}),
      },
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          // `@monaco-editor/react` also contains the word "react" in its path.
          // Keep this check before the generic React bucket so the editor stays
          // behind its lazy boundary instead of making the live shell preload it.
          if (id.includes('monaco-editor') || id.includes('@monaco-editor')) return 'vendor-editor'
          if (id.includes('react')) return 'vendor-react'
          if (id.includes('lightweight-charts')) return 'vendor-charts'
          if (id.includes('html-to-image')) return 'vendor-export'
          return 'vendor'
        },
      },
    },
  },
  server: {
    host: '127.0.0.1',
    port: devServerPort,
    strictPort: true,
    // Git worktrees may share node_modules through a junction. Vite resolves
    // font assets to that junction's real path, so explicitly allow only the
    // frontend root and the resolved dependency root.
    fs: {
      allow: [frontendRoot, dependencyRoot],
    },
    proxy: buildApiProxy(),
  },
  preview: {
    host: '127.0.0.1',
    port: devServerPort,
    strictPort: true,
    proxy: buildApiProxy(),
  },
})
