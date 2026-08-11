import {
  createPublicClient,
  createWalletClient,
  custom,
  defineChain,
  formatEther,
  getAddress,
  http,
  parseEther,
  type Address,
  type EIP1193Provider,
  type Hash,
} from "viem";
import type { Activity, Listing, MarketRequest, NetworkMode, Offer } from "./types";

export const TESTNET_ADDRESS = getAddress(
  import.meta.env.VITE_TESTNET_MARKET_ADDRESS ?? "0x641549D4c1ea67E16c84c996065629Df0AA34399",
);
export const LEGACY_TESTNET_ADDRESS = "0x7Eab155DCae4Be8837678Af3ca96909b4141104E";
const mainnetValue = import.meta.env.VITE_MAINNET_MARKET_ADDRESS as string | undefined;
export const MAINNET_ADDRESS = mainnetValue ? getAddress(mainnetValue) : null;
export const MAINNET_WRITES = import.meta.env.VITE_ENABLE_MAINNET_WRITES === "true";
export const MAX_TRANSACTION_INJ = import.meta.env.VITE_MAX_TRANSACTION_INJ ?? "0.1";
export const MIN_GAS_RESERVE_INJ = import.meta.env.VITE_MIN_GAS_RESERVE_INJ ?? "0.01";

export const injectiveTestnet = defineChain({
  id: 1439,
  name: "Injective EVM Testnet",
  nativeCurrency: { name: "Injective", symbol: "INJ", decimals: 18 },
  rpcUrls: { default: { http: [import.meta.env.VITE_TESTNET_RPC_URL ?? "https://k8s.testnet.json-rpc.injective.network/"] } },
  blockExplorers: { default: { name: "Blockscout", url: "https://testnet.blockscout.injective.network" } },
  testnet: true,
});

export const injectiveMainnet = defineChain({
  id: 1776,
  name: "Injective EVM Mainnet",
  nativeCurrency: { name: "Injective", symbol: "INJ", decimals: 18 },
  rpcUrls: { default: { http: [import.meta.env.VITE_MAINNET_RPC_URL ?? "https://sentry.evm-rpc.injective.network/"] } },
  blockExplorers: { default: { name: "Injective Explorer", url: "https://explorer.injective.network" } },
});

export const marketAbi = [
  { type: "function", name: "openRequestIds", stateMutability: "view", inputs: [], outputs: [{ name: "", type: "uint256[]" }] },
  { type: "function", name: "activeListingIds", stateMutability: "view", inputs: [], outputs: [{ name: "", type: "uint256[]" }] },
  { type: "function", name: "offerIdsOf", stateMutability: "view", inputs: [{ name: "requestId", type: "uint256" }], outputs: [{ name: "", type: "uint256[]" }] },
  { type: "function", name: "getListing", stateMutability: "view", inputs: [{ name: "id", type: "uint256" }], outputs: [{ name: "seller", type: "address" }, { name: "description", type: "string" }, { name: "tags", type: "string[]" }, { name: "recipeUri", type: "string" }, { name: "recipeHash", type: "bytes32" }, { name: "price", type: "uint256" }, { name: "active", type: "bool" }, { name: "createdTs", type: "uint256" }] },
  { type: "function", name: "getRequest", stateMutability: "view", inputs: [{ name: "id", type: "uint256" }], outputs: [{ name: "requester", type: "address" }, { name: "need", type: "string" }, { name: "budget", type: "uint256" }, { name: "tags", type: "string[]" }, { name: "status", type: "uint8" }, { name: "createdTs", type: "uint256" }, { name: "acceptedOfferId", type: "uint256" }] },
  { type: "function", name: "getOffer", stateMutability: "view", inputs: [{ name: "id", type: "uint256" }], outputs: [{ name: "requestId", type: "uint256" }, { name: "responder", type: "address" }, { name: "recipeUri", type: "string" }, { name: "recipeHash", type: "bytes32" }, { name: "price", type: "uint256" }, { name: "status", type: "uint8" }, { name: "createdTs", type: "uint256" }] },
  { type: "function", name: "publishRequest", stateMutability: "payable", inputs: [{ name: "need", type: "string" }, { name: "tags", type: "string[]" }], outputs: [{ name: "id", type: "uint256" }] },
  { type: "function", name: "submitOffer", stateMutability: "nonpayable", inputs: [{ name: "requestId", type: "uint256" }, { name: "recipeUri", type: "string" }, { name: "recipeHash", type: "bytes32" }, { name: "price", type: "uint256" }], outputs: [{ name: "id", type: "uint256" }] },
  { type: "function", name: "acceptOffer", stateMutability: "nonpayable", inputs: [{ name: "offerId", type: "uint256" }], outputs: [] },
  { type: "function", name: "releasePayment", stateMutability: "nonpayable", inputs: [{ name: "offerId", type: "uint256" }], outputs: [] },
  { type: "function", name: "cancelRequest", stateMutability: "nonpayable", inputs: [{ name: "requestId", type: "uint256" }], outputs: [] },
  { type: "function", name: "rate", stateMutability: "nonpayable", inputs: [{ name: "offerId", type: "uint256" }, { name: "ratee", type: "address" }, { name: "score", type: "uint8" }], outputs: [] },
  { type: "function", name: "listSkill", stateMutability: "nonpayable", inputs: [{ name: "description", type: "string" }, { name: "tags", type: "string[]" }, { name: "recipeUri", type: "string" }, { name: "recipeHash", type: "bytes32" }, { name: "price", type: "uint256" }], outputs: [{ name: "id", type: "uint256" }] },
  { type: "function", name: "buySkill", stateMutability: "payable", inputs: [{ name: "id", type: "uint256" }], outputs: [] },
  { type: "function", name: "delistSkill", stateMutability: "nonpayable", inputs: [{ name: "id", type: "uint256" }], outputs: [] },
] as const;

export function networkConfig(mode: Exclude<NetworkMode, "demo">) {
  if (mode === "testnet" && TESTNET_ADDRESS.toLowerCase() === LEGACY_TESTNET_ADDRESS.toLowerCase()) {
    throw new Error("已拒绝旧版测试网合约：它缺少技能挂牌接口。请配置新版 Market 地址。");
  }
  return mode === "testnet"
    ? { chain: injectiveTestnet, address: TESTNET_ADDRESS, writes: true }
    : { chain: injectiveMainnet, address: MAINNET_ADDRESS, writes: MAINNET_WRITES && Boolean(MAINNET_ADDRESS) };
}

export function publicClient(mode: Exclude<NetworkMode, "demo">) {
  const config = networkConfig(mode);
  return createPublicClient({ chain: config.chain, transport: http() });
}

export async function connectInjected(mode: Exclude<NetworkMode, "demo">) {
  const ethereum = (window as Window & { ethereum?: EIP1193Provider }).ethereum;
  if (!ethereum) throw new Error("未检测到注入式 EVM 钱包，请安装兼容钱包后重试。未发起任何交易。");
  const config = networkConfig(mode);
  const wallet = createWalletClient({ chain: config.chain, transport: custom(ethereum) });
  const [account] = await wallet.requestAddresses();
  const chainId = await wallet.getChainId();
  if (chainId !== config.chain.id) {
    try {
      await wallet.switchChain({ id: config.chain.id });
    } catch {
      throw new Error(`钱包当前网络为 ${chainId}，请切换到 Chain ID ${config.chain.id}。未发起任何交易。`);
    }
  }
  return { wallet, account };
}

export async function readListings(mode: Exclude<NetworkMode, "demo">): Promise<Listing[]> {
  const config = networkConfig(mode);
  if (!config.address) return [];
  const client = publicClient(mode);
  const ids = await client.readContract({ address: config.address, abi: marketAbi, functionName: "activeListingIds" });
  return Promise.all(ids.map(async (id) => {
    const value = await client.readContract({ address: config.address!, abi: marketAbi, functionName: "getListing", args: [id] });
    return { id: id.toString(), seller: value[0], description: value[1], tags: [...value[2]], recipe_uri: value[3], recipe_hash: value[4].slice(2), price: value[5], active: value[6], created_ts: Number(value[7]) };
  }));
}

export async function readRequests(mode: Exclude<NetworkMode, "demo">): Promise<MarketRequest[]> {
  const config = networkConfig(mode);
  if (!config.address) return [];
  const client = publicClient(mode);
  const openIds = await client.readContract({ address: config.address, abi: marketAbi, functionName: "openRequestIds" });
  const remembered = loadRememberedRequests(mode);
  const ids = [...new Set([...openIds.map(String), ...remembered])].map(BigInt);
  const results = await Promise.all(ids.map(async (id): Promise<MarketRequest | null> => {
    try {
      const value = await client.readContract({ address: config.address!, abi: marketAbi, functionName: "getRequest", args: [id] });
      return { id: id.toString(), requester: String(value[0]), need: value[1], budget: value[2], tags: [...value[3]], status: ["open", "answered", "settled", "cancelled"][value[4]] as MarketRequest["status"], created_ts: Number(value[5]), accepted_offer_id: value[6] === 0n ? null : value[6].toString() };
    } catch {
      return null;
    }
  }));
  return results.filter((item): item is MarketRequest => item !== null);
}

function rememberedKey(mode: Exclude<NetworkMode, "demo">) {
  return `injenium.requests.${mode}.v1`;
}

function loadRememberedRequests(mode: Exclude<NetworkMode, "demo">): string[] {
  try { return JSON.parse(localStorage.getItem(rememberedKey(mode)) ?? "[]") as string[]; }
  catch { return []; }
}

export function rememberRequest(mode: Exclude<NetworkMode, "demo">, requestId: string) {
  const ids = [...new Set([requestId, ...loadRememberedRequests(mode)])].slice(0, 50);
  localStorage.setItem(rememberedKey(mode), JSON.stringify(ids));
}

export async function readOffers(mode: Exclude<NetworkMode, "demo">, requestId: string): Promise<Offer[]> {
  const config = networkConfig(mode);
  if (!config.address) return [];
  const client = publicClient(mode);
  const ids = await client.readContract({ address: config.address, abi: marketAbi, functionName: "offerIdsOf", args: [BigInt(requestId)] });
  return Promise.all(ids.map(async (id) => {
    const value = await client.readContract({ address: config.address!, abi: marketAbi, functionName: "getOffer", args: [id] });
    return { id: id.toString(), request_id: value[0].toString(), responder: value[1], recipe_uri: value[2], recipe_hash: value[3].slice(2), price: value[4], status: ["open", "accepted", "paid", "rejected"][value[5]] as Offer["status"], created_ts: Number(value[6]) };
  }));
}

export function displayInj(value: number | string | bigint) {
  if (typeof value === "bigint") return formatEther(value);
  if (typeof value === "string" && /^\d+$/.test(value) && value.length > 10) return formatEther(BigInt(value));
  if (typeof value === "number" && value > 1e9) return formatEther(BigInt(Math.trunc(value)));
  return String(value);
}

export function validateSpend(amount: string, balance?: bigint) {
  const value = parseEther(amount);
  const maximum = parseEther(MAX_TRANSACTION_INJ);
  const reserve = parseEther(MIN_GAS_RESERVE_INJ);
  if (value <= 0n) throw new Error("金额必须大于 0 INJ。");
  if (value > maximum) throw new Error(`金额超过单笔上限 ${MAX_TRANSACTION_INJ} INJ。`);
  if (balance !== undefined && balance < value + reserve) throw new Error(`余额不足：交易后必须至少保留 ${MIN_GAS_RESERVE_INJ} INJ 作为 gas。`);
  return value;
}

const ACTIVITY_KEY = "injenium.activities.v1";

export function loadActivities(): Activity[] {
  try {
    return JSON.parse(localStorage.getItem(ACTIVITY_KEY) ?? "[]") as Activity[];
  } catch {
    return [];
  }
}

export function saveActivities(items: Activity[]) {
  localStorage.setItem(ACTIVITY_KEY, JSON.stringify(items.slice(0, 100)));
}

export async function recoverPending(items: Activity[]): Promise<Activity[]> {
  const next = [...items];
  for (const activity of next) {
    if (activity.status !== "pending" || !activity.hash || !activity.chainId) continue;
    const mode = activity.chainId === 1439 ? "testnet" : "mainnet";
    try {
      const receipt = await publicClient(mode).getTransactionReceipt({ hash: activity.hash });
      activity.status = receipt.status === "success" ? "confirmed" : "failed";
      activity.detail = receipt.status === "success" ? "链上回执已确认" : "交易已回滚，未产生预期状态变更";
    } catch {
      activity.detail = "交易已广播，仍在等待链上回执；页面不会自动重发。";
    }
  }
  saveActivities(next);
  return next;
}

export type ChainWrite = {
  functionName: "publishRequest" | "submitOffer" | "acceptOffer" | "releasePayment" | "cancelRequest" | "rate" | "listSkill" | "buySkill" | "delistSkill";
  args: readonly unknown[];
  value?: bigint;
  title: string;
};

export async function executeWrite(mode: Exclude<NetworkMode, "demo">, write: ChainWrite): Promise<{ hash: Hash; account: Address }> {
  const config = networkConfig(mode);
  if (!config.address) throw new Error("当前网络尚未配置 Market 合约地址。未发起任何交易。");
  if (!config.writes) throw new Error("主网当前处于只读模式。未发起任何交易。");
  const { wallet, account } = await connectInjected(mode);
  if (write.value) {
    const balance = await publicClient(mode).getBalance({ address: account });
    validateSpend(formatEther(write.value), balance);
  }
  const hash = await wallet.writeContract({
    account,
    address: config.address,
    abi: marketAbi,
    chain: config.chain,
    functionName: write.functionName,
    args: write.args,
    value: write.value,
  } as never);
  return { hash, account };
}
