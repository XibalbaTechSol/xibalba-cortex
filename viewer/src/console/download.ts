// Handing bytes to the browser as a file, and naming that file without trusting the server's path.

import type { Attachment } from '../api'

/** Save a Blob under `filename` via a temporary link. Revoked on the next tick; the download has started. */
export function saveBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

const EXTENSIONS: Record<string, string> = {
  'image/png': 'png',
  'image/jpeg': 'jpg',
  'image/gif': 'gif',
  'image/webp': 'webp',
  'application/pdf': 'pdf',
  'application/json': 'json',
  'text/plain': 'txt',
  'text/markdown': 'md',
  'text/csv': 'csv',
}

/**
 * A safe download name for an attachment. `storage_locator` is a path on the server's disk, so it is
 * never used: the name is the attachment id (opaque) plus an extension chosen from the media type.
 */
export function attachmentFilename(a: Pick<Attachment, 'id' | 'media_type'>): string {
  const base = a.id.replace(/[^A-Za-z0-9._-]+/g, '_').slice(0, 64) || 'attachment'
  const ext = EXTENSIONS[(a.media_type ?? '').split(';')[0].trim().toLowerCase()]
  return ext ? `${base}.${ext}` : base
}
