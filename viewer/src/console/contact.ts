// Composing the contact mail draft. Pure, because the landing page has no server behind it:
// the form hands the visitor a pre-filled draft in their own client, and the only thing worth
// testing is that the draft is assembled and encoded correctly.

/**
 * Where contact mail goes. See the note in Landing.tsx: an operator decision, on a domain that
 * resolves MX but whose `contact` mailbox has not been confirmed to exist.
 */
export const CONTACT_EMAIL = 'contact@xibalba.dev'

export type ContactFields = {
  name: string
  email: string
  org: string
  topic: string
  message: string
}

/** Reads the form without trusting any field to be present. */
export function contactFields(data: FormData): ContactFields {
  const get = (k: string) => String(data.get(k) ?? '').trim()
  return {
    name: get('name'),
    email: get('email'),
    org: get('org'),
    topic: get('topic'),
    message: get('message'),
  }
}

/**
 * A `mailto:` URL whose subject and body are percent-encoded. Encoding matters more than it
 * looks: an unencoded newline or ampersand in the body truncates the draft at that point in
 * most clients, silently dropping whatever the visitor actually wrote.
 */
export function contactMailto(f: ContactFields, to: string = CONTACT_EMAIL): string {
  const subject = `Cortex enquiry — ${f.topic || 'general'}`
  const body = [
    `Name: ${f.name}`,
    `Email: ${f.email}`,
    `Organisation: ${f.org || '—'}`,
    `Interest: ${f.topic || 'general'}`,
    '',
    f.message,
  ].join('\n')
  return `mailto:${to}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
}
