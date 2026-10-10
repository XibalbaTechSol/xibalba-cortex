// Settings. "Layout" is the one preference that lives in this browser; Inference, Embeddings,
// Account and Developer read and write the Cortex profile through the local API, each in its own
// file under ./settings so a section can change without touching the others.

import { useState } from 'react'
import { useSettings } from '../settingsContext'
import { DEFAULT_SETTINGS, type ShellLayout } from '../settings'
import { Page } from './Page'
import { InferenceSection } from './settings/InferenceSection'
import { EmbeddingsSection } from './settings/EmbeddingsSection'
import { AccountSection } from './settings/AccountSection'
import { DeveloperSection } from './settings/DeveloperSection'

type Section = 'layout' | 'inference' | 'embeddings' | 'account' | 'developer'
const SECTIONS: Array<[Section, string]> = [
  ['layout', 'Layout'],
  ['inference', 'Inference'],
  ['embeddings', 'Embeddings'],
  ['account', 'Account'],
  ['developer', 'Developer'],
]

const LAYOUTS: Array<{ id: ShellLayout; title: string; body: string }> = [
  { id: 'rail', title: 'Left rail', body: 'Every destination in a rail down the left edge, grouped, with the workspace beside it. The default.' },
  { id: 'top', title: 'Top bar', body: 'A bar across the top with every destination on a second row. More room for the workspace, less room to label things.' },
]

/** A small wireframe of each layout, drawn in CSS so it cannot drift from the real shell's proportions. */
function Wireframe({ layout }: { layout: ShellLayout }) {
  return (
    <span className={`xc-wire xc-wire--${layout}`} aria-hidden="true">
      <i className="xc-wire-nav" />
      <i className="xc-wire-main" />
      <i className="xc-wire-side" />
    </span>
  )
}

export function SettingsPage() {
  const { settings, update, reset } = useSettings()
  const [section, setSection] = useState<Section>('layout')
  const isDefault = settings.shell === DEFAULT_SETTINGS.shell && settings.railCollapsed === DEFAULT_SETTINGS.railCollapsed && settings.graphMode === DEFAULT_SETTINGS.graphMode && settings.graphSnap === DEFAULT_SETTINGS.graphSnap

  return (
    <Page eyebrow="System" title="Settings" note={section === 'layout' ? 'Layout is a preference of this browser and is not stored in the Cortex profile. The other sections read and change the profile itself.' : 'These sections read and change the Cortex profile through the local API.'}>
      <div className="xc-tabs" role="tablist" aria-label="Settings sections">
        {SECTIONS.map(([id, label]) => (
          <button key={id} type="button" role="tab" id={`st-${id}`} className="xc-tab" aria-selected={section === id} aria-controls="st-panel" onClick={() => setSection(id)}>{label}</button>
        ))}
      </div>

      <section id="st-panel" role="tabpanel" aria-labelledby={`st-${section}`} className="xc-win xc-settings-panel">
        {section === 'inference' && <InferenceSection />}
        {section === 'embeddings' && <EmbeddingsSection />}
        {section === 'account' && <AccountSection />}
        {section === 'developer' && <DeveloperSection />}
        {section === 'layout' && (<>
        <p className="xc-eyebrow">Shell layout</p>
        <div className="xc-choice" role="radiogroup" aria-label="Shell layout">
          {LAYOUTS.map((l) => (
            <label key={l.id} className="xc-choice-card" data-selected={settings.shell === l.id}>
              <input type="radio" name="shell" value={l.id} checked={settings.shell === l.id} onChange={() => update({ shell: l.id })} />
              <Wireframe layout={l.id} />
              <span className="xc-choice-text">
                <b>{l.title}</b>
                <span className="xc-note">{l.body}</span>
              </span>
            </label>
          ))}
        </div>

        <label className="xc-check xc-settings-row" data-disabled={settings.shell !== 'rail'}>
          <input type="checkbox" checked={settings.railCollapsed} disabled={settings.shell !== 'rail'} onChange={(e) => update({ railCollapsed: e.target.checked })} />
          <span>Collapse the rail to icons</span>
          <span className="xc-note">Applies to the left rail. It also collapses by itself on narrow windows.</span>
        </label>

        <label className="xc-field xc-settings-row">Graph view
          <select className="xc-input" value={settings.graphMode} onChange={(e) => update({ graphMode: e.target.value === '2d' ? '2d' : '3d' })}>
            <option value="3d">3D — orbit, pan and zoom (default; needs WebGL)</option>
            <option value="2d">2D — a flat force layout</option>
          </select>
          <span className="xc-note">Also switchable on the Graph lens itself. Without WebGL the Graph lens shows 2D. The Timeline lens is always 2D.</span>
        </label>

        <label className="xc-check xc-settings-row">
          <input type="checkbox" checked={settings.graphSnap} onChange={(e) => update({ graphSnap: e.target.checked })} />
          <span>Snap graph nodes to the grid</span>
          <span className="xc-note">Each node takes its own cell of a faint grid, in 2D and 3D. Off, nodes stay wherever the force layout puts them. Also a button on the Graph lens.</span>
        </label>

        <div className="xc-actions-row">
          <button type="button" className="xc-btn" disabled={isDefault} onClick={reset}>Restore defaults</button>
        </div>
        </>)}
      </section>
    </Page>
  )
}
