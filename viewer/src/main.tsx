import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// One application root. The console is the only UI: there is no edition branch here, and no
// second component to pick. It used to share this bundle with the original tab-based viewer
// (`?ui=legacy`, since archived) and then with a separate managed app at `/managed`; both are
// gone, so this boots the console and nothing else.
//
// `VITE_CORTEX_EDITION` still exists, and still matters -- but it selects CONFIGURATION, inside
// `console/edition.ts`: which copy the public landing shows, and whether the console asks the
// hosted account API who this browser is. It selects no component.
//
// The import stays dynamic only because the console's CSS and its component tree are a single
// lazily-loaded chunk.
async function boot(): Promise<void> {
  const root = createRoot(document.getElementById('root')!)
  await import('./console/console.css')
  const { ConsoleApp } = await import('./console/ConsoleApp.tsx')
  root.render(<StrictMode><ConsoleApp /></StrictMode>)
}

void boot()
