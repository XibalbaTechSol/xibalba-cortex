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
