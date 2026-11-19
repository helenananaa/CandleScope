import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { readFileSync, mkdirSync } from 'node:fs'
import { execFileSync } from 'node:child_process'

const here = dirname(fileURLToPath(import.meta.url))
const frontend = resolve(here, '..')
const runtime = resolve(here, 'node_modules/pyodide')
const pages = ['index', 'replay', 'strategy', 'local', 'backtest']
const appVersion = readFileSync(resolve(frontend, '../backend/app/core/version.py'), 'utf8').match(
  /APP_VERSION = "([^"]+)"/
)[1]

export default defineConfig({
  root: frontend,
  base: './',
  define: {
    'import.meta.env.VITE_BROWSER_PYTHON': '"1"',
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
        const emit = (path, fileName) =>
          this.emitFile({ type: 'asset', fileName, source: readFileSync(path) })
        const cache = resolve(here, '.host-cache')
        mkdirSync(cache, { recursive: true })
        const pack = resolve(cache, 'backend.zip')
        execFileSync('python3', [resolve(here, 'host/bundle.py'), pack], { stdio: 'inherit' })
        emit(pack, 'engine/backend.zip')
        for (const name of [
          'pyodide.mjs',
          'pyodide.asm.mjs',
          'pyodide.asm.wasm',
          'python_stdlib.zip',
          'pyodide-lock.json',
        ]) {
          emit(resolve(runtime, name), 'engine/' + name)
        }
        emit(resolve(here, 'host/worker.mjs'), 'engine/backend-worker.mjs')
        emit(resolve(here, 'workspace-service.mjs'), 'workspace-service.mjs')
      },
    },
  ],
  build: {
    outDir: process.env.CANDLE_BROWSER_OUT || 'dist-web',
    emptyOutDir: true,
    rollupOptions: {
      input: Object.fromEntries(pages.map((page) => [page, resolve(frontend, page + '.html')])),
    },
  },
})
