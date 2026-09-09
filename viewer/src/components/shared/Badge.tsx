import type { ReactNode } from 'react'

export function Badge({ children }: { children: ReactNode }) {
  if (children === null || children === undefined || children === '') return null
  return <span className="badge">{children}</span>
}

export function Hash({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="muted">none</span>
  return <code title={value}>{value.slice(0, 18)}...</code>
}
