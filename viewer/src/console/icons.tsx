// Inline stroke icons on a 24x24 viewBox, currentColor, no fills and no emoji (design system:
// Iconography). The stroke carries state colour; the well behind an icon stays transparent.

import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement>

const base = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
} as const

export const IconGraph = (p: IconProps) => (
  <svg {...base} {...p}>
    <circle cx="6" cy="7" r="2.4" />
    <circle cx="18" cy="6" r="2.4" />
    <circle cx="12" cy="17" r="2.4" />
    <path d="M8 8.2 10.4 15M16.3 7.8 13.6 15.3M8.3 6.6 15.6 6.2" />
  </svg>
)
/** Snap-to-grid: cells, with one node sitting in one of them. */
export const IconGrid = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M3 9h18M3 15h18M9 3v18M15 3v18" />
    <rect x="9.8" y="9.8" width="4.4" height="4.4" fill="currentColor" stroke="none" />
  </svg>
)
/** Unpin: a pin with a stroke through it. */
export const IconUnpin = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M9 4h6l-1 5 3 3H7l3-3-1-5ZM12 12v7" />
    <path d="M4 4l16 16" />
  </svg>
)
export const IconTimeline = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M3 12h18M7 8v8M12 6v12M17 9v6" />
  </svg>
)
export const IconSearch = (p: IconProps) => (
  <svg {...base} {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="m16.5 16.5 4 4" />
  </svg>
)
export const IconRefresh = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6" />
  </svg>
)
export const IconSignOut = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M10 4H5v16h5M15 8l4 4-4 4M19 12H9" />
  </svg>
)
export const IconPlay = (p: IconProps) => (
  <svg {...base} fill="currentColor" stroke="none" {...p}>
    <path d="M8 5v14l11-7z" />
  </svg>
)
export const IconPause = (p: IconProps) => (
  <svg {...base} fill="currentColor" stroke="none" {...p}>
    <path d="M7 5h4v14H7zM13 5h4v14h-4z" />
  </svg>
)
export const IconChevronUp = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="m6 15 6-6 6 6" />
  </svg>
)
export const IconChevronDown = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="m6 9 6 6 6-6" />
  </svg>
)
export const IconFit = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
  </svg>
)
/** a window with its left pane marked: show or hide the Filters pane */
export const IconPanelLeft = (p: IconProps) => (
  <svg {...base} {...p}>
    <rect x="3" y="4" width="18" height="16" />
    <path d="M9 4v16" />
  </svg>
)
/** the same, with the right pane marked: show or hide the Inspector */
export const IconPanelRight = (p: IconProps) => (
  <svg {...base} {...p}>
    <rect x="3" y="4" width="18" height="16" />
    <path d="M15 4v16" />
  </svg>
)
/** a crosshair: frame the selection */
export const IconTarget = (p: IconProps) => (
  <svg {...base} {...p}>
    <circle cx="12" cy="12" r="6" />
    <path d="M12 2v4M12 18v4M2 12h4M18 12h4" />
  </svg>
)
export const IconCheck = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M20 6 9 17l-5-5" />
  </svg>
)
export const IconWarn = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M12 9v4M12 17h.01M10.3 3.9 2.4 17.5A1.9 1.9 0 0 0 4 20.4h16a1.9 1.9 0 0 0 1.6-2.9L13.7 3.9a1.9 1.9 0 0 0-3.4 0Z" />
  </svg>
)
export const IconClose = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M18 6 6 18M6 6l12 12" />
  </svg>
)

export const IconReview = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M4 6.5l1.6 1.6L8.4 5" />
    <path d="M4 12.5l1.6 1.6 2.8-3.1" />
    <path d="M4 18.5l1.6 1.6 2.8-3.1" />
    <path d="M12 7h8M12 13h8M12 19h8" />
  </svg>
)

export const IconIntegrity = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M12 3l7 3v5c0 4.4-2.9 7.9-7 10-4.1-2.1-7-5.6-7-10V6l7-3z" />
    <path d="M9 12l2.2 2.2L15.2 10" />
  </svg>
)

export const IconLock = (p: IconProps) => (
  <svg {...base} {...p}>
    <rect x="5" y="11" width="14" height="9" />
    <path d="M8 11V8a4 4 0 018 0v3" />
  </svg>
)

export const IconArrowRight = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M4 12h15M13 6l6 6-6 6" />
  </svg>
)

export const IconGoogle = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M21 12.2c0-.7-.1-1.4-.2-2H12v4.1h5.1c-.2 1.2-1 2.2-2.1 2.9v2.4h3.4c2-1.9 3.1-4.7 3.1-7.4z" stroke="none" fill="currentColor" />
    <path d="M12 21.3c2.6 0 4.8-.8 6.4-2.4l-3.4-2.4c-.9.6-2 1-3 1-2.4 0-4.4-1.6-5.1-3.8H3.3v2.5C5 19.6 8.2 21.3 12 21.3z" stroke="none" fill="currentColor" />
    <path d="M6.9 13.7c-.2-.6-.3-1.2-.3-1.7s.1-1.1.3-1.7V7.8H3.3C2.6 9.1 2.2 10.5 2.2 12s.4 2.9 1.1 4.2l3.6-2.5z" stroke="none" fill="currentColor" />
    <path d="M12 5.7c1.4 0 2.7.5 3.7 1.4l2.8-2.8C16.8 2.8 14.6 2 12 2 8.2 2 5 3.7 3.3 6.9l3.6 2.5c.7-2.2 2.7-3.7 5.1-3.7z" stroke="none" fill="currentColor" />
  </svg>
)

export const IconGitHub = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" stroke="none" fill="currentColor" />
  </svg>
)

export const IconMemories = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M4 6h16M4 12h16M4 18h10" />
  </svg>
)

export const IconEntities = (p: IconProps) => (
  <svg {...base} {...p}>
    <circle cx="12" cy="12" r="2.4" />
    <circle cx="5" cy="6" r="1.8" />
    <circle cx="19" cy="7" r="1.8" />
    <circle cx="6" cy="19" r="1.8" />
    <path d="M10 10.6L6.3 7.4M14 10.8l3.6-2.5M10.5 14l-3.4 3.4" />
  </svg>
)

export const IconSessions = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M12 4l8 4-8 4-8-4 8-4z" />
    <path d="M4 12l8 4 8-4M4 16l8 4 8-4" />
  </svg>
)

export const IconOperations = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M3 12h4l2-6 4 12 2-6h6" />
  </svg>
)

export const IconAgents = (p: IconProps) => (
  <svg {...base} {...p}>
    <rect x="6" y="6" width="12" height="12" />
    <path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" />
  </svg>
)

export const IconSettings = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M4 7h10M18 7h2M4 17h2M10 17h10" />
    <rect x="14" y="5" width="4" height="4" />
    <rect x="6" y="15" width="4" height="4" />
  </svg>
)

export const IconChevronLeft = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M15 5l-7 7 7 7" />
  </svg>
)

export const IconChevronRight = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M9 5l7 7-7 7" />
  </svg>
)

export const IconMore = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M5 12h.01M12 12h.01M19 12h.01" strokeWidth={3} />
  </svg>
)
