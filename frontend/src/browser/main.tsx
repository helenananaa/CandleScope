import { createRoot } from 'react-dom/client'
import { initializeLocale } from '../i18n'
import Workspace from './BrowserWorkspace'

void initializeLocale('zh-CN').then(() => createRoot(document.getElementById('root')!).render(<Workspace />))
