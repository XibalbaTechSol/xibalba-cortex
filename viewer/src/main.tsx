import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// Two UIs share this bundle while the console replaces the legacy viewer. The console is the
// default; `?ui=legacy` loads the original tab-based app unchanged. Each branch imports its own
// stylesheet dynamically so the legacy global element selectors (button, input, h1...) never
// leak into the console, and the console's tokens never touch the legacy pages.
const legacy = new URLSearchParams(window.location.search).get('ui') === 'legacy'

async function boot(): Promise<void> {
  const root = createRoot(document.getElementById('root')!)
  if (legacy) {
    await import('./index.css')
    const { default: App } = await import('./App.tsx')
    root.render(
      <StrictMode>
        <App />
      </StrictMode>,
    )
    return
  }
  await import('./console/console.css')
  const { ConsoleApp } = await import('./console/ConsoleApp.tsx')
  root.render(
    <StrictMode>
      <ConsoleApp />
    </StrictMode>,
  )
}

void boot()
