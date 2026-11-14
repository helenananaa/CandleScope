import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/fonts.js'
import App from './App'
import { ChartErrorBoundary } from './app/AppProviders'
import { readPersistedLocale } from './features/settings/chartAppearanceSettings.js'
import { bindDocumentLocale, initializeLocale } from './i18n/index.js'
import { markPerf } from './runtime/performance/perfMarks'

async function boot(): Promise<void> {
  await initializeLocale(readPersistedLocale())
  bindDocumentLocale({
    titleKey: 'shell.documentTitle',
    descriptionKey: 'shell.documentDescription',
  })

  // 禁用浏览器默认右键菜单
  document.addEventListener('contextmenu', (e) => e.preventDefault())

  markPerf('app.boot.start')
  markPerf('app.root.render.requested')

  createRoot(document.getElementById('root') as HTMLElement).render(
    <StrictMode>
      <ChartErrorBoundary>
        <App />
      </ChartErrorBoundary>
    </StrictMode>,
  )
}

void boot();
