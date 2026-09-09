import { useCallback } from 'react'

export type ToastType = 'success' | 'error' | 'info'

export interface Toast {
  id: number
  message: string
  type: ToastType
}

type AddToastFn = (msg: string, type: ToastType) => void

let _addToast: AddToastFn | null = null

export function registerToastHandler(handler: AddToastFn | null) {
  _addToast = handler
}

export function useToast() {
  const add = useCallback((message: string, type: ToastType = 'info') => {
    _addToast?.(message, type)
  }, [])
  return { toast: add }
}
