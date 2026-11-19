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
      // Namespace packages keep desktop server bootstrap out of the browser.
      const modules = [
        'data_engine/kline_quality', 'data_engine/aggregation/semantics', 'data_engine/aggregation/adapters',
        'data_engine/data_manager/models', 'data_engine/market_data/kline_metrics', 'data_engine/series_identity',
        'data_engine/series_key', 'data_engine/interval_policy', 'indicator/base', 'indicator/types',
        'indicator/window_math', 'indicator/indicators/ma', 'indicator/indicators/ema', 'indicator/indicators/rsi',
      ]
      this.emitFile({ type: 'asset', fileName: 'engine/desktop-modules.json', source: JSON.stringify(
        Object.fromEntries(modules.map(name => ['app/' + name + '.py', readFileSync(resolve(engine, '..', name + '.py'), 'utf8')]))
      ) })
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
  build: { outDir: '../dist-prototype', emptyOutDir: true },
})
