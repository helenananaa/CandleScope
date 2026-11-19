import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { readFileSync, readdirSync } from 'node:fs'

const here = dirname(fileURLToPath(import.meta.url))
const engine = resolve(here, '../../backend/app/data_engine')
const runtime = resolve(here, 'node_modules/pyodide')

// Ship the same Python sources as the desktop runtime, without a CDN dependency.
function browserAssets() {
  return {
    name: 'candlescope-browser-runtime',
    generateBundle() {
      const emit = (sourcePath, fileName) => this.emitFile({
        type: 'asset', fileName, source: readFileSync(sourcePath),
      })
      for (const name of ['pyodide.mjs', 'pyodide.asm.mjs', 'pyodide.asm.wasm', 'python_stdlib.zip', 'pyodide-lock.json']) {
        emit(resolve(runtime, name), 'engine/' + name)
      }
      emit(resolve(engine, 'kline_quality.py'), 'engine/kline_quality.py')
      emit(resolve(engine, 'aggregation/semantics.py'), 'engine/semantics.py')
      for (const name of ['market_window.py', 'market-worker.mjs', 'recent-history.mjs']) emit(resolve(here, name), 'engine/' + name)
      for (const name of readdirSync(resolve(here, 'snapshots'))) emit(resolve(here, 'snapshots', name), 'samples/' + name)
      emit(resolve(here, '../public/brand/favicon.svg'), 'favicon.svg')
    },
  }
}

export default defineConfig({
  root: here,
  base: './',
  publicDir: false,
  plugins: [react(), browserAssets()],
  build: { outDir: '../dist-web', emptyOutDir: true },
})
