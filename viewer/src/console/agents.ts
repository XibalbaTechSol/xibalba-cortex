// Pure helpers for the Agents page: how an agent's identity and a device pairing are worded, and
// which pairing actions are offered in each state.

import type { AgentWorkspace } from '../api'

export interface IdentityView {
  label: string
  tone: 'ok' | 'review' | 'neutral'
  detail: string
}

/**
 * `on_chain: false` is only a fact when the oracle could be asked. The SDK's resolver fails open: an
 * unreachable oracle still answers `on_chain: false`. So an unverified identity is "not checked",
 * never "off-chain".
 */
export function describeIdentity(a: Pick<AgentWorkspace, 'on_chain' | 'identity_verified' | 'wallet_address'>): IdentityView {
  if (!a.identity_verified) return { label: 'not checked', tone: 'neutral', detail: 'The integrity oracle could not be reached, so on-chain status is unknown.' }
  if (a.on_chain) return { label: 'registered on-chain', tone: 'ok', detail: a.wallet_address ? `wallet ${a.wallet_address}` : 'registered, no wallet address on record' }
  return { label: 'off-chain', tone: 'review', detail: 'The oracle answered and this agent is not registered.' }
}

export type PairAction = 'rename' | 'detach' | 'revoke'

/** What can be done to a pairing in each state. A revoked pairing is final. */
export function pairActions(status: AgentWorkspace['pair_status'] | undefined): PairAction[] {
  if (status === 'active') return ['rename', 'detach', 'revoke']
  if (status === 'detached') return ['rename', 'revoke']
  return []
}

/** "not counted" is not zero: the API skips an expensive count and says so. */
export function countText(value: number, counted: boolean | undefined): string {
  return counted === false ? 'not counted' : value.toLocaleString()
}

export const PAIR_ACTION_COPY: Record<PairAction, { label: string; confirm: string | null }> = {
  rename: { label: 'Rename', confirm: null },
  detach: { label: 'Detach', confirm: 'Detaching stops this device writing as the agent. Its existing memories stay, and it can be paired again.' },
  revoke: { label: 'Revoke', confirm: 'Revoking is permanent: this device can never be paired to this agent again. Its existing memories stay.' },
}
