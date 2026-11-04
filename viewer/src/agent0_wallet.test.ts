/* Phase 2, Task 5 — on-chain failures leave nothing half-registered.
 *
 * Four things can go wrong when registering an agent on Base Sepolia through the browser
 * wallet, and they need different answers from the person: install a wallet, switch network,
 * approve the prompt, or look at why the transaction reverted. Before this, three of them
 * surfaced as whatever string the wallet happened to produce, and the fourth was worse than
 * undistinguished -- a REVERTED transaction reported "Registration confirmed but no ERC-8004
 * Registered event was found", because `receipt.status` was never checked. The user was told
 * their registration had confirmed when the chain had rejected it.
 *
 * Driven through viem against a fake EIP-1193 provider rather than by mocking viem: the whole
 * question is what the real client does with what a wallet returns. The flow needs exactly
 * four provider methods, which is what makes this practical.
 */
import { afterEach, describe, expect, it } from 'vitest'

import {
  AgentRegistrationError,
  BASE_SEPOLIA_CHAIN_ID,
  registerAgentWithMetaMask,
  type RegistrationFailure,
} from './agent0_wallet'

const TX = ('0x' + 'ab'.repeat(32)) as `0x${string}`
const ACCOUNT = '0x1111111111111111111111111111111111111111'

interface Behaviour {
  chainId?: string
  onSwitch?: () => never
  onAccounts?: () => never
  onSend?: () => never
  receiptStatus?: '0x0' | '0x1'
}

/** The four methods the registration flow actually calls, and nothing else. */
function install(behaviour: Behaviour = {}): void {
  const provider = {
    request: async ({ method }: { method: string; params?: unknown }) => {
      switch (method) {
        case 'eth_chainId':
          return behaviour.chainId ?? '0x14a34'
        case 'wallet_switchEthereumChain':
        case 'wallet_addEthereumChain':
          if (behaviour.onSwitch) behaviour.onSwitch()
          return null
        case 'eth_requestAccounts':
        case 'eth_accounts':
          if (behaviour.onAccounts) behaviour.onAccounts()
          return [ACCOUNT]
        case 'eth_sendTransaction':
          if (behaviour.onSend) behaviour.onSend()
          return TX
        case 'eth_getTransactionReceipt':
          return {
            status: behaviour.receiptStatus ?? '0x1',
            logs: [],
            blockNumber: '0x1',
            transactionHash: TX,
          }
        default:
          throw new Error(`the registration flow asked for an unexpected method: ${method}`)
      }
    },
  }
  ;(globalThis as unknown as { window: unknown }).window = { ethereum: provider }
}

function rejected(): never {
  throw Object.assign(new Error('User rejected the request.'), { code: 4001 })
}

async function failureOf(behaviour: Behaviour | null): Promise<AgentRegistrationError> {
  if (behaviour === null) (globalThis as unknown as { window: unknown }).window = {}
  else install(behaviour)
  try {
    await registerAgentWithMetaMask({ name: 'test agent', description: 'a test agent' })
  } catch (error) {
    if (error instanceof AgentRegistrationError) return error
    throw new Error(`expected an AgentRegistrationError, got: ${String(error)}`)
  }
  throw new Error('registration resolved when it should have failed')
}

afterEach(() => {
  delete (globalThis as unknown as { window?: unknown }).window
})

describe('the four ways on-chain registration fails', () => {
  it('names no injected provider', async () => {
    expect((await failureOf(null)).reason).toBe<RegistrationFailure>('no-provider')
  })

  it('names a chain it could not switch', async () => {
    const failure = await failureOf({
      chainId: '0x1',
      onSwitch: () => { throw Object.assign(new Error('internal wallet failure'), { code: -32603 }) },
    })
    expect(failure.reason).toBe<RegistrationFailure>('wrong-chain')
    expect(failure.message, 'the wallet’s own error text was passed through to the user')
      .not.toContain('internal wallet failure')
  })

  it('names a prompt the person declined', async () => {
    expect((await failureOf({ onAccounts: rejected })).reason).toBe<RegistrationFailure>('rejected')
  })

  it('names a declined transaction as declined, not as a chain problem', async () => {
    // Rejection can arrive at either prompt; both are the person saying no.
    expect((await failureOf({ onSend: rejected })).reason).toBe<RegistrationFailure>('rejected')
  })

  it('names a reverted transaction, and never calls it confirmed', async () => {
    const failure = await failureOf({ receiptStatus: '0x0' })
    expect(failure.reason).toBe<RegistrationFailure>('reverted')
    expect(failure.message.toLowerCase(), 'a reverted transaction was reported as confirmed')
      .not.toContain('confirmed')
  })

  it('declining the network switch is a rejection, not a chain failure', async () => {
    expect((await failureOf({ chainId: '0x1', onSwitch: rejected })).reason)
      .toBe<RegistrationFailure>('rejected')
  })

  it('gives each outcome a distinct reason', async () => {
    const reasons = [
      (await failureOf(null)).reason,
      (await failureOf({ chainId: '0x1', onSwitch: () => { throw new Error('nope') } })).reason,
      (await failureOf({ onAccounts: rejected })).reason,
      (await failureOf({ receiptStatus: '0x0' })).reason,
    ]
    expect(new Set(reasons).size, `two outcomes share a reason: ${reasons.join(', ')}`).toBe(4)
  })
})

describe('nothing is half-registered', () => {
  it('never returns a registration result for any of the four failures', async () => {
    /* The caller writes the agent into the workspace from the RESOLVED value
     * (`AgentsPage.tsx`: setLocalRecord/setSelected on `result`). So "nothing half-registered"
     * is exactly "none of these resolves" -- including the reverted one, which is the case
     * that used to depend on a missing log rather than on the receipt. */
    for (const behaviour of [null, { chainId: '0x1', onSwitch: rejected }, { onAccounts: rejected }, { receiptStatus: '0x0' as const }]) {
      await expect(failureOf(behaviour)).resolves.toBeInstanceOf(AgentRegistrationError)
    }
  })

  it('a successful receipt with no Registered event is still not a registration', async () => {
    // Confirmed on chain, but nothing to record: this must not resolve either.
    const failure = await failureOf({ receiptStatus: '0x1' })
    expect(failure.reason).toBe<RegistrationFailure>('no-agent-id')
    expect(BASE_SEPOLIA_CHAIN_ID).toBe(84532)
  })
})
