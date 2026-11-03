// Which edition's CONFIGURATION this boot uses.
//
// There is one application root: `main.tsx` renders `ConsoleApp` and nothing else. What an edition
// still chooses is configuration -- which copy the public landing shows, and whether the console
// asks the hosted account API who this browser is. `VITE_CORTEX_EDITION=managed` is set by every
// hosted image (deploy/{managed,render,railway}/Dockerfile), and the hosted deployment serves the
// app at `/managed` (managed/api.py redirects `/` there), so a build without the flag still knows
// itself from the path it was opened at. Both inputs are arguments, so the decision is testable.

export type Edition = 'managed' | 'self-hosted'

/** The path the hosted deployment serves the app at. */
export const HOSTED_PATH = '/managed'

export function editionOf(flag: string | undefined, pathname: string): Edition {
  if (flag === 'managed') return 'managed'
  return pathname.replace(/\/+$/, '') === HOSTED_PATH ? 'managed' : 'self-hosted'
}

/** This boot's edition. Self-hosted whenever there is no window to read, so a server-side or test
 *  render is never accidentally hosted. */
export function edition(): Edition {
  const pathname = typeof location === 'undefined' ? '/' : location.pathname
  return editionOf(import.meta.env.VITE_CORTEX_EDITION, pathname)
}
