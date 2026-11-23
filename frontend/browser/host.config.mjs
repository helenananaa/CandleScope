import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { readFileSync, mkdirSync, rmSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'

const here = dirname(fileURLToPath(import.meta.url))
const frontend = resolve(here, '..')
const outDir = resolve(frontend, process.env.CANDLE_BROWSER_OUT || 'dist-web')

// Cloudflare serves the build as a Worker's static assets (wrangler.jsonc).
// HTML pages and the service worker keep Cloudflare's default Cache-Control,
// which revalidates on every load; the engine and asset folders are named by
// their contents. html_handling "none" keeps every page at its .html address,
// which the pages link to and the shell mirrors, so the root is served from
// index.html here.
const HEADERS = `/engine/*
  ! Cache-Control
  Cache-Control: public, max-age=31536000, immutable

/assets/*
  ! Cache-Control
  Cache-Control: public, max-age=31536000, immutable
`
const REDIRECTS = `/ /index.html 200
`
const runtime = resolve(here, 'node_modules/pyodide')
const pages = ['index', 'replay', 'strategy', 'local', 'backtest']
const appVersion = readFileSync(resolve(frontend, '../backend/app/core/version.py'), 'utf8').match(
  /APP_VERSION = "([^"]+)"/
)[1]

// Build the Python engine first: the pages name its content-addressed folder.
// A deployment therefore never pairs new pages with a cached older engine, and
// tabs of different deployments start separate shared workers.
const cache = resolve(here, '.host-cache')
mkdirSync(cache, { recursive: true })
const pack = resolve(cache, 'backend.zip')
execFileSync('python3', [resolve(here, 'host/bundle.py'), pack], {
  stdio: 'inherit',
  env: { ...process.env, CANDLESCOPE_NODE: process.execPath },
})
const engineFiles = {
  'backend.zip': pack,
  'backend-worker.mjs': resolve(here, 'host/worker.mjs'),
  'catalog.mjs': resolve(here, 'host/catalog.mjs'),
  'interpreter.mjs': resolve(here, 'host/interpreter.mjs'),
  'snapshot-worker.mjs': resolve(here, 'host/snapshot-worker.mjs'),
  'store.mjs': resolve(here, 'host/store.mjs'),
  ...Object.fromEntries(
    ['pyodide.mjs', 'pyodide.asm.mjs', 'pyodide.asm.wasm', 'python_stdlib.zip', 'pyodide-lock.json'].map(
      (name) => [name, resolve(runtime, name)]
    )
  ),
}
const engineHash = createHash('sha256')
for (const [name, path] of Object.entries(engineFiles).sort()) engineHash.update(name).update(readFileSync(path))
const engineDir = 'engine/' + engineHash.digest('hex').slice(0, 16) + '/'

export default defineConfig({
  root: frontend,
  base: './',
  define: {
    'import.meta.env.VITE_BROWSER_PYTHON': '"1"',
    'import.meta.env.VITE_ENGINE_DIR': JSON.stringify(engineDir),
    'import.meta.env.VITE_APP_VERSION': JSON.stringify(appVersion),
    'import.meta.env.VITE_APP_BUILD': JSON.stringify(
      execFileSync('git', ['rev-parse', '--short=12', 'HEAD'], { cwd: here, encoding: 'utf8' }).trim()
    ),
  },
  plugins: [
    react(),
    {
      name: 'browser-python-host',
      transformIndexHtml: {
        order: 'pre',
        handler(html, ctx) {
          const entry = ctx.path.split('/').at(-1).replace('.html', '')
          return html
            .replace('<html ', '<html data-entry="' + entry + '" ')
            .replace(/src="\/src\/(?:[a-z]+-)?main\.tsx"/, 'src="/browser/host/entry.mjs"')
        },
      },
      generateBundle() {
        for (const [name, path] of Object.entries(engineFiles))
          this.emitFile({ type: 'asset', fileName: engineDir + name, source: readFileSync(path) })
        this.emitFile({
          type: 'asset',
          fileName: 'workspace-service.mjs',
          source: readFileSync(resolve(here, 'workspace-service.mjs')),
        })
        this.emitFile({ type: 'asset', fileName: '_headers', source: HEADERS })
        this.emitFile({ type: 'asset', fileName: '_redirects', source: REDIRECTS })
      },
      // public/design-previews holds design mockups for development only.
      closeBundle() {
        rmSync(resolve(outDir, 'design-previews'), { recursive: true, force: true })
      },
    },
  ],
  build: {
    outDir,
    emptyOutDir: true,
    rollupOptions: {
      input: Object.fromEntries(pages.map((page) => [page, resolve(frontend, page + '.html')])),
    },
  },
})
