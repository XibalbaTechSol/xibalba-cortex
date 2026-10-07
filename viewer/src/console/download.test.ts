import { describe, expect, it } from 'vitest'
import { attachmentFilename } from './download'

describe('attachmentFilename', () => {
  it('uses the id and an extension from the media type', () => {
    expect(attachmentFilename({ id: 'att-1', media_type: 'image/png' })).toBe('att-1.png')
    expect(attachmentFilename({ id: 'att-2', media_type: 'application/pdf' })).toBe('att-2.pdf')
  })
  it('ignores media type parameters and case', () => {
    expect(attachmentFilename({ id: 'a', media_type: 'Text/Plain; charset=utf-8' })).toBe('a.txt')
  })
  it('adds no extension for a type it does not know, rather than guessing', () => {
    expect(attachmentFilename({ id: 'a', media_type: 'application/x-weird' })).toBe('a')
  })
  it('strips path characters from the id', () => {
    expect(attachmentFilename({ id: '../../etc/passwd', media_type: 'text/plain' })).toBe('.._.._etc_passwd.txt')
  })
  it('falls back to a fixed name for an empty id', () => {
    expect(attachmentFilename({ id: '', media_type: 'text/plain' })).toBe('attachment.txt')
  })
})
