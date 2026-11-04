import {
  createPublicClient,
  createWalletClient,
  custom,
  decodeEventLog,
  getAddress,
  parseAbi,
  stringToHex,
  type Address,
  type EIP1193Provider,
  type Hex,
} from 'viem'
import { baseSepolia } from 'viem/chains'

/** Why an on-chain registration did not happen. Each one needs a different action from the
 *  person -- install a wallet, switch network, approve the prompt, or look at the revert --
 *  so they are distinguished here rather than left as whatever string the wallet produced. */
export type RegistrationFailure =
  | 'no-provider'
  | 'wrong-chain'
  | 'rejected'
  | 'reverted'
  | 'no-agent-id'

export class AgentRegistrationError extends Error {
  // Declared, not a constructor parameter property: `erasableSyntaxOnly` is on.
  readonly reason: RegistrationFailure

  constructor(reason: RegistrationFailure, message: string) {
    super(message)
    this.name = 'AgentRegistrationError'
    this.reason = reason
  }
}

/** EIP-1193 code 4001 is the person declining a prompt. viem wraps provider errors, so the
 *  code can be several `cause` levels down. */
function isUserRejection(error: unknown): boolean {
  for (let current: unknown = error, depth = 0; current && depth < 10; depth += 1) {
    const node = current as { code?: unknown; name?: unknown; cause?: unknown }
    if (node.code === 4001 || node.name === 'UserRejectedRequestError') return true
    current = node.cause
  }
  return false
}

export const BASE_SEPOLIA_CHAIN_ID = 84532
export const BASE_SEPOLIA_IDENTITY_REGISTRY = '0x8004A818BFB912233c491871b3d84c89A494BD9e' as Address

const identityRegistryAbi = parseAbi([
  'function register(string agentURI, (string key, bytes value)[] metadata) returns (uint256 agentId)',
  'function tokenURI(uint256 tokenId) view returns (string)',
  'function ownerOf(uint256 tokenId) view returns (address)',
  'event Registered(uint256 indexed agentId, string agentURI, address indexed owner)',
])

export interface ClientRegistrationInput {
  name: string
  description: string
  image?: string
  active?: boolean
  trustModels?: string[]
  metadata?: Record<string, string>
}

export interface ClientRegistrationResult {
  account: Address
  txHash: Hex
  agentId: string
  record: Record<string, unknown>
}

export interface ClientAgentRecord {
  agentId: string
  name?: string
  description?: string
  image?: string | null
  agentURI?: string
  owners?: string[]
  walletAddress?: string
  active?: boolean
  trustModels?: string[]
  endpoints?: Array<Record<string, unknown>>
}

function requireProvider(): EIP1193Provider {
  const provider = (window as Window & { ethereum?: EIP1193Provider }).ethereum
  if (!provider) throw new AgentRegistrationError('no-provider', 'No browser wallet is available. Install MetaMask, or open this console in a browser where it is enabled.')
  return provider
}

function toBase64(value: string): string {
  const bytes = new TextEncoder().encode(value)
  let binary = ''
  for (let index = 0; index < bytes.length; index += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000))
  }
  return btoa(binary)
}

function registrationUri(input: ClientRegistrationInput): string {
  const document = {
    type: 'https://eips.ethereum.org/EIPS/eip-8004#registration-v1',
    name: input.name.trim(),
    description: input.description.trim(),
    image: input.image?.trim() || null,
    services: [],
    registrations: [],
    supportedTrust: input.trustModels?.length ? input.trustModels : ['reputation'],
    active: input.active ?? true,
    x402Support: false,
    updatedAt: Math.floor(Date.now() / 1000),
  }
  return `data:application/json;base64,${toBase64(JSON.stringify(document))}`
}

function metadataEntries(metadata: Record<string, string> | undefined): Array<{ key: string; value: Hex }> {
  return Object.entries(metadata ?? {})
    .filter(([key, value]) => key.trim() && value.trim())
    .map(([key, value]) => ({ key: key.trim(), value: stringToHex(value) }))
}

/* Deliberately not built from the wallet's own error. A provider message can carry an RPC
 * URL, a key, or an internal fault string, and none of it tells the person what to do. */
const wrongChain = () => new AgentRegistrationError('wrong-chain',
  `This wallet is not on Base Sepolia (chain ${BASE_SEPOLIA_CHAIN_ID}) and the network could not be selected for you. Switch to Base Sepolia in the wallet and try again.`)
const rejection = () => new AgentRegistrationError('rejected',
  'The wallet prompt was declined, so nothing was registered. Approve the prompt to continue.')

async function ensureBaseSepolia(provider: EIP1193Provider): Promise<void> {
  const chainId = await provider.request({ method: 'eth_chainId' })
  if (Number.parseInt(String(chainId), 16) === BASE_SEPOLIA_CHAIN_ID) return
  try {
    await provider.request({ method: 'wallet_switchEthereumChain', params: [{ chainId: '0x14a34' }] })
    return
  } catch (error) {
    if (isUserRejection(error)) throw rejection()
    // 4902: the wallet does not know this chain yet, so offer to add it. Anything else is a
    // chain problem the person has to resolve in the wallet.
    if ((error as { code?: number }).code !== 4902) throw wrongChain()
  }
  try {
    await provider.request({
      method: 'wallet_addEthereumChain',
      params: [{
        chainId: '0x14a34',
        chainName: 'Base Sepolia',
        nativeCurrency: { name: 'Ether', symbol: 'ETH', decimals: 18 },
        rpcUrls: ['https://sepolia.base.org'],
        blockExplorerUrls: ['https://sepolia.basescan.org'],
      }],
    })
  } catch (error) {
    if (isUserRejection(error)) throw rejection()
    throw wrongChain()
  }
}

export async function registerAgentWithMetaMask(input: ClientRegistrationInput): Promise<ClientRegistrationResult> {
  if (!input.name.trim() || !input.description.trim()) throw new Error('Agent name and description are required.')
  const provider = requireProvider()
  await ensureBaseSepolia(provider)
  const wallet = createWalletClient({ chain: baseSepolia, transport: custom(provider) })
  let account: Address | undefined
  let txHash: Hex
  try {
    ;[account] = await wallet.requestAddresses()
    if (!account) throw new AgentRegistrationError('rejected', 'The wallet returned no account, so nothing was registered.')
    txHash = await wallet.writeContract({
      address: BASE_SEPOLIA_IDENTITY_REGISTRY,
      abi: identityRegistryAbi,
      functionName: 'register',
      args: [registrationUri(input), metadataEntries(input.metadata)],
      account,
      chain: baseSepolia,
    })
  } catch (error) {
    // A decline at either prompt is the same answer from the person.
    if (isUserRejection(error)) throw rejection()
    throw error
  }
  const publicClient = createPublicClient({ chain: baseSepolia, transport: custom(provider) })
  const receipt = await publicClient.waitForTransactionReceipt({ hash: txHash })
  /* The receipt gates everything after it. Without this, a REVERTED transaction fell through
   * to the log scan below, found no `Registered` event, and reported "Registration confirmed
   * but no ERC-8004 Registered event was found" -- telling the person their registration had
   * confirmed when the chain had rejected it. The caller writes the agent into the workspace
   * from this function's resolved value, so throwing here is what keeps a failed transaction
   * from leaving a half-registered agent behind. */
  if (receipt.status !== 'success') {
    throw new AgentRegistrationError('reverted',
      `The registration transaction was rejected on chain and no agent was created. Transaction: ${txHash}`)
  }
  let tokenId: bigint | undefined
  for (const log of receipt.logs) {
    try {
      const decoded = decodeEventLog({ abi: identityRegistryAbi, data: log.data, topics: log.topics })
      if (decoded.eventName === 'Registered') {
        tokenId = decoded.args.agentId
        break
      }
    } catch {
      // Ignore unrelated logs emitted by the transaction.
    }
  }
  if (tokenId === undefined) throw new AgentRegistrationError('no-agent-id', `The transaction succeeded but carried no ERC-8004 Registered event, so there is no agent id to record. Transaction: ${txHash}`)
  const agentId = `${BASE_SEPOLIA_CHAIN_ID}:${tokenId.toString()}`
  const record = await readAgent0Registration(provider, tokenId)
  return { account: getAddress(account), txHash, agentId, record }
}

export async function readAgent0Registration(provider: EIP1193Provider, tokenId: bigint): Promise<Record<string, unknown>> {
  const publicClient = createPublicClient({ chain: baseSepolia, transport: custom(provider) })
  const [agentURI, owner] = await Promise.all([
    publicClient.readContract({ address: BASE_SEPOLIA_IDENTITY_REGISTRY, abi: identityRegistryAbi, functionName: 'tokenURI', args: [tokenId] }),
    publicClient.readContract({ address: BASE_SEPOLIA_IDENTITY_REGISTRY, abi: identityRegistryAbi, functionName: 'ownerOf', args: [tokenId] }),
  ])
  let document: Record<string, unknown> = {}
  if (agentURI.startsWith('data:application/json;base64,')) {
    const encoded = agentURI.slice('data:application/json;base64,'.length)
    document = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(encoded), (char) => char.charCodeAt(0)))) as Record<string, unknown>
  }
  return {
    ...document,
    agentId: `${BASE_SEPOLIA_CHAIN_ID}:${tokenId.toString()}`,
    agentURI,
    owners: [getAddress(owner)],
    walletAddress: getAddress(owner),
  }
}
