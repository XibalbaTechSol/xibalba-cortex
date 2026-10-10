// Inline stroke icons on a 24x24 viewBox, currentColor, no fills and no emoji (design system:
// Iconography). The stroke carries state colour; the well behind an icon stays transparent.

import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement>

const base = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
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
export const IconTimeline = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M3 12h18M7 8v8M12 6v12M17 9v6" />
  </svg>
)
export const IconSearch = (p: IconProps) => (
  <svg {...base} strokeWidth={2} {...p}>
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
export const IconFit = (p: IconProps) => (
  <svg {...base} {...p}>
    <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
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
  <svg {...base} strokeWidth={2.2} {...p}>
    <path d="M20 6 9 17l-5-5" />
  </svg>
)
export const IconWarn = (p: IconProps) => (
  <svg {...base} strokeWidth={2} {...p}>
    <path d="M12 9v4M12 17h.01M10.3 3.9 2.4 17.5A1.9 1.9 0 0 0 4 20.4h16a1.9 1.9 0 0 0 1.6-2.9L13.7 3.9a1.9 1.9 0 0 0-3.4 0Z" />
  </svg>
)
export const IconClose = (p: IconProps) => (
  <svg {...base} strokeWidth={2} {...p}>
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
