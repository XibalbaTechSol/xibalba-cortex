import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { ALL_DESTINATIONS, DESTINATIONS, destinationsFrom } from './nav'
import { editionOf, HOSTED_PATH } from './edition'
import { BILLING_UNDECLARED, declaredDestinations, workspaceSession } from './hostedWorkspace'

const MANAGED_API = resolve(import.meta.dirname, '../../../src/xibalba_cortex/managed/api.py')
const MANAGED_SOURCE = readFileSync(MANAGED_API, 'utf8')

/* Which edition's CONFIGURATION a boot uses. It selects copy and whether the console asks the
   hosted account API who it is -- never which component renders, which is why main.tsx has no
   branch left. Both inputs are passed in, so this is testable in plain node. */
describe('editionOf', () => {
  it('is self-hosted with no flag and an ordinary path', () => {
    expect(editionOf(undefined, '/')).toBe('self-hosted')
    expect(editionOf('', '/console')).toBe('self-hosted')
    expect(editionOf('self-hosted', '/')).toBe('self-hosted')
  })
  it('is managed when the build flag says so, at any path', () => {
    expect(editionOf('managed', '/')).toBe('managed')
    expect(editionOf('managed', '/anything/else')).toBe('managed')
  })
  it('is managed on the hosted path, however many trailing slashes it carries', () => {
    expect(editionOf(undefined, HOSTED_PATH)).toBe('managed')
    expect(editionOf(undefined, '/managed/')).toBe('managed')
    expect(editionOf(undefined, '/managed//')).toBe('managed')
  })
  it('does not match a path that merely begins with the hosted one', () => {
    expect(editionOf(undefined, '/managed-notes')).toBe('self-hosted')
    expect(editionOf(undefined, '/x/managed')).toBe('self-hosted')
  })
})

/* Ruling C: the hosted-workspace capabilities are gated on an explicit signal from the session --
   the hosted account API answered -- and NOT on `billing` appearing in the nav list. A hosted
   deployment that stopped declaring `billing` must keep its API keys and its export, and must say
   that the declaration is wrong rather than quietly dropping a destination. */
describe('workspaceSession', () => {
  it('no hosted answer is a self-hosted session with every built destination', () => {
    const session = workspaceSession(null)
    expect(session.hosted).toBe(false)
    expect(session.destinations).toEqual(DESTINATIONS)
    expect(session.fault).toBeNull()
  })
  it('a hosted answer is hosted, whatever it declared', () => {
    expect(workspaceSession({ destinations: ['graph', 'billing'] }).hosted).toBe(true)
    expect(workspaceSession({}).hosted).toBe(true)
    expect(workspaceSession({ destinations: [] }).hosted).toBe(true)
  })
  it('resolves the declaration through nav, dropping ids the console does not know', () => {
    expect(workspaceSession({ destinations: ['settings', 'graph', 'wormhole', 'billing'] }).destinations.map((d) => d.id))
      .toEqual(['graph', 'settings', 'billing'])
  })
  it('a hosted session that declares no billing is a declaration fault, and still hosted', () => {
    const session = workspaceSession({ destinations: ['graph', 'memories', 'agents', 'settings'] })
    expect(session.hosted).toBe(true)
    expect(session.fault).toBe(BILLING_UNDECLARED)
  })
  it('a hosted session that declares nothing at all is a fault too', () => {
    expect(workspaceSession({}).fault).toBe(BILLING_UNDECLARED)
    expect(workspaceSession({ destinations: [] }).fault).toBe(BILLING_UNDECLARED)
  })
  it('the hosted declaration raises no fault', () => {
    const session = workspaceSession({ destinations: [...declaredDestinations(MANAGED_SOURCE)] })
    expect(session.fault).toBeNull()
  })
})

/* The check has to read the REAL declaration, not a copy of it: a list hand-copied into a test
   cannot catch the backend dropping `billing`. This reads MANAGED_DESTINATIONS out of the module
   that defines it without importing or modifying any Python. */
describe('the hosted edition’s own declaration', () => {
  it('still contains billing, so the billing destination cannot silently vanish', () => {
    const ids = declaredDestinations(MANAGED_SOURCE)
    expect(ids).toContain('billing')
    expect(workspaceSession({ destinations: [...ids] }).fault).toBeNull()
  })
  it('declares only ids the console can resolve', () => {
    const known = new Set(ALL_DESTINATIONS.map((d) => d.id))
    const ids = declaredDestinations(MANAGED_SOURCE)
    expect(ids.length).toBeGreaterThan(0)
    expect(ids.filter((id) => !known.has(id as never))).toEqual([])
    expect(destinationsFrom([...ids]).length).toBe(ids.length)
  })
  /* The reader, and the fault it feeds, proved against a declaration that HAS lost billing --
     the mutation this guard exists to catch, without touching the real module. */
  it('reports a declaration that dropped billing', () => {
    const mutated = MANAGED_SOURCE.replace('"billing")', ')')
    expect(mutated).not.toBe(MANAGED_SOURCE)
    const ids = declaredDestinations(mutated)
    expect(ids).not.toContain('billing')
    expect(workspaceSession({ destinations: [...ids] }).fault).toBe(BILLING_UNDECLARED)
  })
  it('refuses a source with no declaration rather than reading it as empty', () => {
    expect(() => declaredDestinations('x = 1\n')).toThrow(/MANAGED_DESTINATIONS/)
  })
})
