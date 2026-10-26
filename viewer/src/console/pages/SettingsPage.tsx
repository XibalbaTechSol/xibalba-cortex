// Settings. "Layout" is the one preference that lives in this browser; Inference, Embeddings,
// Account and Developer read and write the Cortex profile through the local API, each in its own
// file under ./settings so a section can change without touching the others.

import { useState } from 'react'
import { useSettings } from '../settingsContext'
import { DEFAULT_SETTINGS, GRAPH_CANVASES, NODE_SHAPES, type GraphCanvas, type NodeShape, type ShellLayout } from '../settings'
import { Page } from './Page'

/* A <select> hands back a string. These narrow it against the same lists the parser uses, so an
   option added to the markup but not to the type cannot slip through as a setting nothing renders. */
const asNodeShape = (v: string): NodeShape => (NODE_SHAPES.includes(v as NodeShape) ? (v as NodeShape) : DEFAULT_SETTINGS.nodeShape)
const asGraphCanvas = (v: string): GraphCanvas => (GRAPH_CANVASES.includes(v as GraphCanvas) ? (v as GraphCanvas) : DEFAULT_SETTINGS.graphCanvas)
import { InferenceSection } from './settings/InferenceSection'
import { EmbeddingsSection } from './settings/EmbeddingsSection'
import { AccountSection } from './settings/AccountSection'
import { DeveloperSection } from './settings/DeveloperSection'
import { AccessSection } from './settings/AccessSection'
import { ProfileSection } from './settings/ProfileSection'

type Section = 'layout' | 'inference' | 'embeddings' | 'account' | 'access' | 'profile' | 'developer'
const SECTIONS: Array<[Section, string]> = [
  ['layout', 'Layout'],
  ['inference', 'Inference'],
  ['embeddings', 'Embeddings'],
  ['account', 'Account'],
  ['access', 'Access'],
  ['profile', 'Profile'],
  ['developer', 'Developer'],
]

const LAYOUTS: Array<{ id: ShellLayout; title: string; body: string }> = [
  { id: 'rail', title: 'Left rail', body: 'The Graph and Timeline lenses in a rail down the left edge, with the tools beneath them; the workspace beside it. The default.' },
  { id: 'top', title: 'Top bar', body: 'A bar across the top: the two lenses and the tools on a second row. More room for the workspace, less room to label things.' },
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
  const isDefault = settings.shell === DEFAULT_SETTINGS.shell && settings.railCollapsed === DEFAULT_SETTINGS.railCollapsed && settings.graphMode === DEFAULT_SETTINGS.graphMode && settings.graphSnap === DEFAULT_SETTINGS.graphSnap && settings.nodeShape === DEFAULT_SETTINGS.nodeShape && settings.graphCanvas === DEFAULT_SETTINGS.graphCanvas

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
        {section === 'access' && <AccessSection />}
        {section === 'profile' && <ProfileSection />}
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

        <label className="xc-check xc-settings-row">
          <input type="checkbox" checked={settings.railCollapsed} onChange={(e) => update({ railCollapsed: e.target.checked })} />
          <span>Collapse navigation to icons</span>
          <span className="xc-note">The left rail, or the top bar’s second row. Also a button on each. The rail also collapses by itself on narrow windows.</span>
        </label>
        <label className="xc-check xc-settings-row">
          <input type="checkbox" checked={settings.facetsCollapsed} onChange={(e) => update({ facetsCollapsed: e.target.checked })} />
          <span>Collapse the Projection dock</span>
          <span className="xc-note">Keep the filters in a narrow edge strip. Also available from the dock header.</span>
        </label>
        <label className="xc-check xc-settings-row">
          <input type="checkbox" checked={settings.detailCollapsed} onChange={(e) => update({ detailCollapsed: e.target.checked })} />
          <span>Collapse the selected-memory dock</span>
          <span className="xc-note">Keep the selection while giving the graph more room. Also available from the dock header.</span>
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

        <label className="xc-field xc-settings-row">Node shape
          <select className="xc-input" value={settings.nodeShape} onChange={(e) => update({ nodeShape: asNodeShape(e.target.value) })}>
            <option value="box">Box — a cube in 3D, a square in 2D (default)</option>
            <option value="diamond">Diamond — an octahedron in 3D</option>
            <option value="facet">Facet — an icosahedron in 3D, a hexagon in 2D</option>
          </select>
          <span className="xc-note">The same form in both lenses: the Graph lens builds the solid, the 2D layout traces its silhouette. Every shape stays inside the cell the grid gives it, so snapping keeps working.</span>
        </label>

        <label className="xc-field xc-settings-row">Graph canvas
          <select className="xc-input" value={settings.graphCanvas} onChange={(e) => update({ graphCanvas: asGraphCanvas(e.target.value) })}>
            <option value="lattice">Spatial grid — faint outer planes (default)</option>
            <option value="frame">Frame — the bounding box only</option>
            <option value="plain">Plain — nothing behind the nodes</option>
          </select>
          <span className="xc-note">What the graph is drawn on. The 2D lens has no bounding frame of its own, so Frame and Plain both leave its field clear.</span>
        </label>

        <div className="xc-actions-row">
          <button type="button" className="xc-btn" disabled={isDefault} onClick={reset}>Restore defaults</button>
        </div>
        </>)}
      </section>
    </Page>
  )
}
