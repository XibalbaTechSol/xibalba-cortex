// Shared behaviour for Recall and the Review drawer: focus goes into the dialog on open, Escape
// closes it, Tab stays inside it, and focus returns to whatever opened it. One hook so both
// overlays are modal in exactly the same way.

import { useEffect, useRef, type RefObject } from 'react'

const FOCUSABLE = 'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href]'

export function useDialog(dialogRef: RefObject<HTMLElement | null>, onClose: () => void, initialFocus?: RefObject<HTMLElement | null>): void {
  // the opener is read once, at mount, before focus moves into the dialog
  const opener = useRef<Element | null>(document.activeElement)
  const close = useRef(onClose)
  close.current = onClose

  useEffect(() => {
    initialFocus?.current?.focus()
    const previous = opener.current
    return () => {
      if (previous instanceof HTMLElement) previous.focus()
    }
  }, [initialFocus])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        close.current()
        return
      }
      if (e.key !== 'Tab' || !dialogRef.current) return
      const items = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE))
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [dialogRef])
}
