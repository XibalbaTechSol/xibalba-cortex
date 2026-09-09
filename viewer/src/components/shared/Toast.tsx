import { useEffect, useRef, useState } from 'react'
import { registerToastHandler, type Toast, type ToastType } from './useToast'

let _toastId = 0

export function ToastContainer() {
  const [toasts, setToasts] = useState<Toast[]>([])
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map())

  useEffect(() => {
    const handleAdd = (message: string, type: ToastType) => {
      const id = ++_toastId
      setToasts((prev) => [...prev, { id, message, type }])
      const t = setTimeout(() => {
        setToasts((prev) => prev.filter((x) => x.id !== id))
        timers.current.delete(id)
      }, 4000)
      timers.current.set(id, t)
    }

    registerToastHandler(handleAdd)
    return () => {
      registerToastHandler(null)
    }
  }, [])

  return (
    <div className="toast-container" role="region" aria-label="Notifications" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.type}`} role="status">
          <span className="toast-icon" aria-hidden="true">
            {t.type === 'success' ? '✓' : t.type === 'error' ? '✕' : 'ℹ'}
          </span>
          <span className="toast-message">{t.message}</span>
        </div>
      ))}
    </div>
  )
}
