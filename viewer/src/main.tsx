import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './console/console.css'
import { ConsoleApp } from './console/ConsoleApp.tsx'

// The console is the only UI. Its stylesheet is scoped under `.xc` (plus html/body background), so
// nothing here depends on load order.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConsoleApp />
  </StrictMode>,
)
