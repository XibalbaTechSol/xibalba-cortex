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
  if (!provider) throw new Error('MetaMask is not installed or is unavailable in this browser.')
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

async function ensureBaseSepolia(provider: EIP1193Provider): Promise<void> {
  const chainId = await provider.request({ method: 'eth_chainId' })
  if (Number.parseInt(String(chainId), 16) === BASE_SEPOLIA_CHAIN_ID) return
  try {
    await provider.request({ method: 'wallet_switchEthereumChain', params: [{ chainId: '0x14a34' }] })
  } catch (error) {
    if ((error as { code?: number }).code !== 4902) throw error
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
  }
}

export async function registerAgentWithMetaMask(input: ClientRegistrationInput): Promise<ClientRegistrationResult> {
  if (!input.name.trim() || !input.description.trim()) throw new Error('Agent name and description are required.')
  const provider = requireProvider()
  await ensureBaseSepolia(provider)
  const wallet = createWalletClient({ chain: baseSepolia, transport: custom(provider) })
  const [account] = await wallet.requestAddresses()
  if (!account) throw new Error('MetaMask did not return an account.')
  const uri = registrationUri(input)
  const txHash = await wallet.writeContract({
    address: BASE_SEPOLIA_IDENTITY_REGISTRY,
    abi: identityRegistryAbi,
    functionName: 'register',
    args: [uri, metadataEntries(input.metadata)],
    account,
    chain: baseSepolia,
  })
  const publicClient = createPublicClient({ chain: baseSepolia, transport: custom(provider) })
  const receipt = await publicClient.waitForTransactionReceipt({ hash: txHash })
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
  if (tokenId === undefined) throw new Error(`Registration confirmed but no ERC-8004 Registered event was found. Transaction: ${txHash}`)
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
