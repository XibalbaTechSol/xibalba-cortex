// Settings. This slice holds the one preference that lives in the browser (the shell layout);
// the sections that configure the Cortex profile itself are added with the surfaces that own them.

import { useState } from 'react'
import { useSettings } from '../settingsContext'
import { DEFAULT_SETTINGS, type ShellLayout } from '../settings'
import { Page } from './Page'

type Section = 'layout'
const SECTIONS: Array<[Section, string]> = [['layout', 'Layout']]

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
  const isDefault = settings.shell === DEFAULT_SETTINGS.shell && settings.railCollapsed === DEFAULT_SETTINGS.railCollapsed

  return (
    <Page eyebrow="System" title="Settings" note="Preferences for this browser. They are not stored in the Cortex profile.">
      <div className="xc-tabs" role="tablist" aria-label="Settings sections">
        {SECTIONS.map(([id, label]) => (
          <button key={id} type="button" role="tab" id={`st-${id}`} className="xc-tab" aria-selected={section === id} aria-controls="st-panel" onClick={() => setSection(id)}>{label}</button>
        ))}
      </div>

      <section id="st-panel" role="tabpanel" aria-labelledby={`st-${section}`} className="xc-win xc-settings-panel">
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

        <div className="xc-actions-row">
          <button type="button" className="xc-btn" disabled={isDefault} onClick={reset}>Restore defaults</button>
        </div>
      </section>
    </Page>
  )
}
