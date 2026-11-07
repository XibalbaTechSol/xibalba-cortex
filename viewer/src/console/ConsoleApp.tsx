// Console root: sign-in gate, then the two lenses over one shared state.
//
// Layout is [facet rail | lens | inspector] above the chain rail and status bar. Switching lens
// swaps only the centre pane; selection, facets and the time window live in ConsoleProvider so
// they survive it.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { accountLogout, completeSupabaseOAuth, isSignedIn, markSignedOut } from '../api'
import { ApiError } from '../apiError'
import { ConsoleProvider, useConsole } from './state'
import { SignIn } from './SignIn'
import { Landing } from './Landing'
import { HostedLanding } from './HostedLanding'
import { edition } from './edition'
import { clearHostedTransport, installHostedTransport, setHostedSession } from '../hostedApi'
import { hostedRequest, workspaceSession, type HostedMe } from './hostedWorkspace'
import { resetTokenFromSearch } from './passwordReset'
import { verifiedFromSearch } from './authNotice'
import { Rail, StatusBar, TopBar, WorkspaceHeader } from './Shell'
import { SettingsProvider, useSettings } from './settingsContext'
import { PageHost } from './pages/PageHost'
import { PageDrawer } from './PageDrawer'
import { FacetRail } from './FacetRail'
import { GraphLens } from './GraphLens'
import { TimelineLens } from './TimelineLens'
import { Inspector } from './Inspector'
import { ChainRail } from './ChainRail'
import { Recall } from './Recall'
import { Review } from './Review'
import { Integrity } from './Integrity'
import { PhoneWorkspace } from './Phone'
import { useMediaQuery } from './useMediaQuery'
import { DevicePair } from './DevicePair'

// A 401 from any call means the cookie session ended; send the user back to sign-in with a reason.
const EXPIRED = /\b401\b|authentication required|unauthorized|expired/i

function Workspace() {
  const { lens, page, overlay, setOverlay, error, model, unauthorized, signOut, selectedId } = useConsole()

  // ⌘K / Ctrl+K toggles Recall from anywhere, including inside inputs.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOverlay(overlay === 'recall' ? null : 'recall')
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [overlay, setOverlay])

  useEffect(() => {
    if (unauthorized || (error && !model && EXPIRED.test(error))) {
      try { sessionStorage.setItem('xibalba-cortex.auth-notice', 'Session expired. Sign in again to reconnect to this Cortex profile.') } catch { /* private mode: sign-in just shows no notice */ }
      signOut()
    }
  }, [error, model, unauthorized, signOut])

  const phone = useMediaQuery('(max-width: 760px)')
  const { settings } = useSettings()
  const [immersion, setImmersion] = useState(false)

  useEffect(() => {
    const handleToggle = () => setImmersion((v) => !v)
    window.addEventListener('xc-toggle-immersion', handleToggle)
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const isInput = target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)
      if (isInput) return
      if (e.key === 'z' || e.key === 'Z') {
        e.preventDefault()
        setImmersion((v) => !v)
      } else if (e.key === 'Escape' && immersion) {
        setImmersion(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('xc-toggle-immersion', handleToggle)
      window.removeEventListener('keydown', onKey)
    }
  }, [immersion])

  // what sits to the right of (or below) the navigation: a full page, or the three-column workspace
  const content = (
    <>
      {/* The lens owns the whole workspace; the facets, the chain rail and the detail window
          float over it. Previously these were three grid columns and a strip below, which left
          the graph about half the page on a 1600px screen -- the one surface that most wants
          the room. */}
      <main className="xc-workspace" data-detail={selectedId ? 'open' : 'closed'}>
        {lens === 'graph' ? <GraphLens /> : <TimelineLens />}
        <FacetRail />
        <ChainRail />
        {selectedId && <Inspector />}
      </main>
      <StatusBar />
    </>
  )

  return (
    <>
      {phone ? (
        <PhoneWorkspace />
      ) : settings.shell === 'rail' ? (
        <div className="xc-shell" data-collapsed={settings.railCollapsed} data-immersion={immersion}>
          <Rail />
          <div className="xc-main">
            <WorkspaceHeader />
            {content}
          </div>
        </div>
      ) : (
        <div className="xc-shell xc-shell--top" data-immersion={immersion}>
          <TopBar />
          {content}
        </div>
      )}
      {immersion && (
        <div
          className="xc-immersion-hud"
          style={{
            position: 'fixed',
            top: 14,
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 1200,
            background: 'rgba(11, 15, 25, 0.88)',
            backdropFilter: 'blur(16px)',
            border: '1px solid rgba(99, 102, 241, 0.4)',
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.7), 0 0 24px rgba(99, 102, 241, 0.2)',
            borderRadius: 0,
            padding: '6px 20px',
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            fontSize: 12,
            color: 'var(--ink)',
          }}
        >
          <span style={{ fontWeight: 700, letterSpacing: '0.04em', color: 'var(--accent)', display: 'flex', alignItems: 'center', gap: 6 }}>
            <span>🌌</span> ZEN IMMERSION (100% CANVAS)
          </span>
          <span style={{ width: 1, height: 16, background: 'rgba(255, 255, 255, 0.15)' }} />
          <span style={{ color: 'var(--ink-muted, #9ca3af)' }}>Press <strong>Z</strong> or <strong>ESC</strong> to exit</span>
          <button
            type="button"
            className="xc-btn"
            style={{ fontSize: 11, padding: '2px 10px', height: 26 }}
            onClick={() => setImmersion(false)}
          >
            Exit Zen
          </button>
        </div>
      )}
      {page && <PageDrawer page={page}><PageHost page={page} /></PageDrawer>}
      {overlay === 'recall' && <Recall />}
      {overlay === 'review' && <Review />}
      {overlay === 'integrity' && <Integrity />}
    </>
  )
}

// Which signed-out surface a hash asks for. Sign-in is explicit -- `#signin`, `#signup`, an
// emailed link, or an expired session, which leaves a notice behind for SignIn to show -- and
// everything else is the public landing page. Deciding it from the hash rather than from a piece
// of state keeps the two reachable by link, and keeps a visitor who was bounced out of
// `#memories` from landing on a marketing page with no explanation.
//
// The two emailed links are the hosted edition's, and both have to arrive at the form rather than
// at the marketing page: `?reset_token=` (managed/control.py:137, read by resetTokenFromSearch
// along with the console's own `?token=`) and `?verified=1` (managed/api.py:227's redirect after a
// clicked verification link). Nothing covered either before the one-SignIn consolidation, because
// HostedLanding happened to be the hosted edition's only signed-out surface.
const SIGN_IN_HASH = '#signin'
const SIGN_UP_HASH = '#signup'

function pairCodeFromUrl(hash: string, search: string): string | null {
  const paramsSearch = new URLSearchParams(search)
  const codeFromSearch = paramsSearch.get('code')
  if (codeFromSearch) return codeFromSearch
  const hashIdx = hash.indexOf('?')
  if (hashIdx !== -1) {
    const paramsHash = new URLSearchParams(hash.slice(hashIdx))
    return paramsHash.get('code')
  }
  return null
}

function hasOAuthCallback(): boolean {
  if (typeof window === 'undefined') return false
  const search = new URLSearchParams(window.location.search)
  if (search.has('code') || search.has('error')) return true
  const rawHash = window.location.hash.startsWith('#') ? window.location.hash.slice(1) : window.location.hash
  const hashParams = new URLSearchParams(rawHash)
  if (hashParams.has('access_token') || hashParams.has('code') || hashParams.has('error')) return true
  return false
}

function wantsSignIn(hash: string): boolean {
  if (hash === SIGN_IN_HASH || hash === SIGN_UP_HASH) return true
  if (hash.startsWith('#pair') || hash.startsWith('#device')) return true
  if (resetTokenFromSearch(window.location.search) || verifiedFromSearch(window.location.search)) return true
  if (pairCodeFromUrl(hash, typeof window !== 'undefined' ? window.location.search : '')) return true
  if (hasOAuthCallback()) return true
  try { return Boolean(sessionStorage.getItem('xibalba-cortex.auth-notice')) } catch { return false }
}

// The only application root. One component tree serves both editions; what the edition selects is
// configuration -- the landing's copy, and whether the console asks the hosted account API who
// this browser is. Self-hosted makes no such call, so its boot path is byte for byte what it was.
export function ConsoleApp() {
  const hostedEdition = edition() === 'managed'
  const [signedIn, setSignedIn] = useState(isSignedIn)
  // `undefined` = still asking the hosted account API; `null` = there is no hosted session.
  // Self-hosted starts at `null` and never moves: no request is made.
  const [me, setMe] = useState<HostedMe | null | undefined>(hostedEdition ? undefined : null)
  const [hash, setHash] = useState(() => (typeof location === 'undefined' ? '' : location.hash))

  useEffect(() => {
    const onHash = () => setHash(location.hash)
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const askHosted = useCallback(() => {
    setMe(undefined)
    hostedRequest<HostedMe>('me').then((payload) => setMe(payload)).catch((e: unknown) => {
      /* The hosted account API says there is no session. Everything this browser held FOR that
         session goes now -- the non-secret signed-in hint and the account summary -- or the next
         boot renders a workspace before asking anyone, and every read in it 401s.
         Two conditions, and both are load-bearing. A 401 is the session ENDING rather than the
         server failing, so an unreachable backend must not read as "you were signed out". And
         only a browser that BELIEVED it was signed in has anything to reset: a first-time visitor
         to the hosted landing has no session either, and their `me` 401s exactly the same way --
         sending them to a sign-in form with "session expired" on it would be a lie, and it would
         make the public landing unreachable. */
      if (e instanceof ApiError && e.status === 401 && isSignedIn()) {
        markSignedOut()
        setSignedIn(false)
        try { sessionStorage.setItem('xibalba-cortex.auth-notice', 'Session expired. Sign in again to reconnect to this Cortex workspace.') } catch { /* private mode: sign-in just shows no notice */ }
      }
      setMe(null)
    })
  }, [])

  // The data layer learns the edition exactly once, here, before anything under the console can
  // issue a call: with the mapping installed every `/api/*` path goes to the route the managed
  // backend serves, or is refused locally. Self-hosted installs nothing, so its path is unchanged.
  if (hostedEdition) installHostedTransport()

  useEffect(() => {
    if (hostedEdition) {
      if (hasOAuthCallback()) {
        completeSupabaseOAuth()
          .then((completed) => {
            if (completed) {
              setSignedIn(true)
            }
          })
          .catch(() => {})
          .finally(() => {
            askHosted()
          })
      } else {
        askHosted()
      }
    }
    return () => { if (hostedEdition) clearHostedTransport() }
  }, [hostedEdition, askHosted])

  // The entitlement the hosted write gate reads, and the CSRF token hosted mutations carry. One
  // copy, fed from the `me` this component already fetches.
  useEffect(() => { setHostedSession(me ?? null) }, [me])

  // The session: what this deployment serves, and whether it is a hosted workspace. The hosted
  // signal is the answer itself, not anything the answer listed -- see hostedWorkspace.ts.
  const session = useMemo(() => workspaceSession(me ?? null), [me])
  useEffect(() => {
    // A hosted server that stopped declaring `billing` has an unreachable Billing page. That is a
    // server misconfiguration, and it must not pass silently just because the console copes.
    if (session.fault) console.error(session.fault)
  }, [session.fault])

  /* One logout, through the one data layer. `accountLogout` posts `/api/auth/logout`, which the
     hosted mapping sends to `/api/managed/logout` carrying the CSRF token this transport holds --
     so the second, direct `hostedRequest('logout')` that used to run beside it was the same
     request twice, and the first of the two revoked the session the second then needed. The
     order matters: the call goes out BEFORE `setMe(null)` clears the held token, and
     `accountLogout` clears the local hint whether or not the server answers. */
  const signOut = useCallback(() => {
    accountLogout().catch(() => {}).finally(() => {
      setSignedIn(false)
      setMe(null)
    })
  }, [])

  /* ONE signed-out path for both editions: the sign-in form when something asked for it, and the
     edition's public landing otherwise. The hosted edition used to be forced down a second path
     here, because `SignIn` speaks `/api/auth/*` and the hosted backend serves only
     `/api/managed/*` -- hostedApi.ts's table is what made that premise false, so the duplicate
     login / signup / forgot / reset / verify form HostedLanding carried is gone. What is left of
     HostedLanding is its product surface: the hosted copy and the server's own plan catalog, which
     the self-hosted landing does not have. */
  const openSignIn = useCallback((hashValue: string) => () => { location.hash = hashValue }, [])
  const signedOut = wantsSignIn(hash) ? (
    <SignIn onSignedIn={() => { setSignedIn(true); if (hostedEdition) askHosted() }} />
  ) : hostedEdition ? (
    <HostedLanding onSignIn={openSignIn(SIGN_IN_HASH)} onSignUp={openSignIn(SIGN_UP_HASH)} />
  ) : (
    <Landing onSignIn={openSignIn(SIGN_IN_HASH)} />
  )

  const pairCode = pairCodeFromUrl(hash, typeof window !== 'undefined' ? window.location.search : '')

  return (
    <SettingsProvider>
      <div className="xc">
        {me === undefined ? (
          <main className="xc-page"><p className="xc-note" role="status">Loading your workspace…</p></main>
        ) : (hostedEdition ? session.hosted : signedIn) ? (
          pairCode ? (
            <DevicePair code={pairCode} onDone={() => { location.hash = '#agents' }} />
          ) : (
            <ConsoleProvider onSignOut={signOut} destinations={session.destinations} hosted={session.hosted}>
              <Workspace />
            </ConsoleProvider>
          )
        ) : (
          signedOut
        )}
      </div>
    </SettingsProvider>
  )
}
