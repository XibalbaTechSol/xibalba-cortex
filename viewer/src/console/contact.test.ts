import { describe, expect, it } from 'vitest'
import { CONTACT_EMAIL, contactFields, contactMailto, type ContactFields } from './contact'

const base: ContactFields = {
  name: 'Dana Okonkwo',
  email: 'dana@example.org',
  org: 'Meridian Health',
  topic: 'Pilot',
  message: 'Auditing an agent that touches regulated records.',
}

describe('contactFields', () => {
  it('trims what the visitor typed', () => {
    const data = new FormData()
    data.set('name', '  Dana  ')
    data.set('email', ' dana@example.org ')
    expect(contactFields(data).name).toBe('Dana')
    expect(contactFields(data).email).toBe('dana@example.org')
  })
  it('reads a missing field as empty rather than "null"', () => {
    expect(contactFields(new FormData())).toEqual({ name: '', email: '', org: '', topic: '', message: '' })
  })
})

describe('contactMailto', () => {
  it('addresses the contact mailbox', () => {
    expect(contactMailto(base).startsWith(`mailto:${CONTACT_EMAIL}?`)).toBe(true)
  })

  it('carries every field into the body', () => {
    const body = decodeURIComponent(new URL(contactMailto(base)).searchParams.get('body')!)
    expect(body).toContain('Name: Dana Okonkwo')
    expect(body).toContain('Email: dana@example.org')
    expect(body).toContain('Organisation: Meridian Health')
    expect(body).toContain('Interest: Pilot')
    expect(body).toContain('Auditing an agent that touches regulated records.')
  })

  it('names the absent organisation instead of leaving a blank line', () => {
    const body = decodeURIComponent(new URL(contactMailto({ ...base, org: '' })).searchParams.get('body')!)
    expect(body).toContain('Organisation: —')
  })

  it('encodes the separators that would otherwise truncate the draft', () => {
    const url = contactMailto({ ...base, message: 'a & b\nsecond line ?x=1' })
    // The raw URL must not contain a bare newline, or an ampersand past the body marker.
    const raw = url.slice(url.indexOf('&body=') + 6)
    expect(raw).not.toContain('\n')
    expect(raw).not.toContain('&')
    const body = decodeURIComponent(new URL(url).searchParams.get('body')!)
    expect(body).toContain('a & b')
    expect(body).toContain('second line ?x=1')
  })

  it('keeps the subject on one encoded parameter', () => {
    const subject = new URL(contactMailto({ ...base, topic: 'Enterprise' })).searchParams.get('subject')!
    expect(subject).toBe('Cortex enquiry — Enterprise')
  })
})
