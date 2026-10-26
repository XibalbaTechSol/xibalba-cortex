import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// The console is the only UI. It used to share this bundle with the original tab-based viewer,
// reachable at `?ui=legacy`; that viewer was archived and has now been removed, so the stylesheet
// no longer has to be imported dynamically to keep its global element selectors (button, input,
// h1...) out of the console. The import stays dynamic only because the console's CSS and its
// component tree are a single lazily-loaded chunk.
async function boot(): Promise<void> {
  const root = createRoot(document.getElementById('root')!)
  await import('./console/console.css')
  const managed = import.meta.env.VITE_CORTEX_EDITION === 'managed' || location.pathname.replace(/\/+$/, '') === '/managed'
  const App = managed
    ? (await import('./console/ManagedApp.tsx')).ManagedApp
    : (await import('./console/ConsoleApp.tsx')).ConsoleApp
  root.render(<StrictMode><App /></StrictMode>)
}

void boot()
