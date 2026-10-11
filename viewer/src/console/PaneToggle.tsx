// Show or hide the two panes either side of the lens. They live in the lens bar, at its ends, because
// that is where the pane they control is: the Filters toggle at the left edge, the Inspector toggle at
// the right. Hiding a pane gives its width to the lens; the choice persists in the browser settings.

import { useSettings } from './settingsContext'
import { IconPanelLeft, IconPanelRight } from './icons'

export function PaneToggle({ side }: { side: 'filters' | 'inspector' }) {
  const { settings, update } = useSettings()
  const collapsed = side === 'filters' ? settings.facetsCollapsed : settings.inspectorCollapsed
  const name = side === 'filters' ? 'Filters' : 'Inspector'
  return (
    <button
      type="button"
      className="xc-btn xc-btn--square xc-pane-toggle"
      aria-pressed={!collapsed}
      aria-label={collapsed ? `Show ${name}` : `Hide ${name}`}
      title={collapsed ? `Show ${name}` : `Hide ${name}`}
      onClick={() => update(side === 'filters' ? { facetsCollapsed: !collapsed } : { inspectorCollapsed: !collapsed })}
    >
      {side === 'filters' ? <IconPanelLeft /> : <IconPanelRight />}
    </button>
  )
}
