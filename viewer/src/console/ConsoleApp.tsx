// Console root: sign-in gate, then the two lenses over one shared state.
//
// Layout is [facet rail | lens | inspector] above the chain rail and status bar. Switching lens
// swaps only the centre pane; selection, facets and the time window live in ConsoleProvider so
// they survive it.

import { useCallback, useEffect, useState } from 'react'
import { accountLogout, isSignedIn } from '../api'
import { ConsoleProvider, useConsole } from './state'
import { SignIn } from './SignIn'
import { Rail, StatusBar, TopBar, WorkspaceHeader } from './Shell'
import { SettingsProvider, useSettings } from './settingsContext'
import { PageHost } from './pages/PageHost'
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

// A 401 from any call means the cookie session ended; send the user back to sign-in with a reason.
const EXPIRED = /\b401\b|authentication required|unauthorized|expired/i

function Workspace() {
  const { lens, page, overlay, setOverlay, error, model, signOut, selectedId } = useConsole()

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
    if (error && !model && EXPIRED.test(error)) {
      try { sessionStorage.setItem('xibalba-cortex.auth-notice', 'Session expired. Sign in again to reconnect to this Cortex profile.') } catch { /* private mode: sign-in just shows no notice */ }
      signOut()
    }
  }, [error, model, signOut])

  const phone = useMediaQuery('(max-width: 760px)')
  const { settings } = useSettings()

  // what sits to the right of (or below) the navigation: a full page, or the three-column workspace
  const content = page ? (
    <>
      <PageHost page={page} />
      <StatusBar />
    </>
  ) : (
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
        <div className="xc-shell" data-collapsed={settings.railCollapsed}>
          <Rail />
          <div className="xc-main">
            <WorkspaceHeader />
            {content}
          </div>
        </div>
      ) : (
        <>
          <TopBar />
          {content}
        </>
      )}
      {overlay === 'recall' && <Recall />}
      {overlay === 'review' && <Review />}
      {overlay === 'integrity' && <Integrity />}
    </>
  )
}

export function ConsoleApp() {
  const [signedIn, setSignedIn] = useState(isSignedIn)

  const signOut = useCallback(() => {
    // the server owns the session record; clear the hint even if the call fails
    accountLogout().catch(() => {}).finally(() => setSignedIn(false))
  }, [])

  return (
    <SettingsProvider>
      <div className="xc">
        {signedIn ? (
          <ConsoleProvider onSignOut={signOut}>
            <Workspace />
          </ConsoleProvider>
        ) : (
          <SignIn onSignedIn={() => setSignedIn(true)} />
        )}
      </div>
    </SettingsProvider>
  )
}
