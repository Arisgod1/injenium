export type NetworkMode = "demo" | "testnet" | "mainnet";

export type RecipeStep = {
  primitive: string;
  params: Record<string, unknown>;
};

export type Recipe = {
  intent: string;
  preconditions: string[];
  steps: RecipeStep[];
  success_criteria: string;
  schema_version: number;
  payload: Record<string, unknown>;
};

export type RecipeSource =
  | { kind: "builtin"; id: string }
  | { kind: "inline"; recipe: Record<string, unknown> }
  | { kind: "ipfs"; uri: string };

export type Inspection = {
  recipe: Recipe;
  hash: string;
  expectedHash: string | null;
  hashMatches: boolean;
  validation: { ok: boolean; problems: string[] };
  permissions: { primitive: string; count: number }[];
  risk: "low" | "blocked";
};

export type CatalogItem = {
  id: string;
  title: string;
  description: string;
  tags: string[];
  price: string;
  hash: string;
  stepCount: number;
};

export type Listing = {
  id: string;
  seller: string;
  description: string;
  tags: string[];
  recipe_uri: string;
  recipe_hash: string;
  price: number | string | bigint;
  active: boolean;
  created_ts: number;
};

export type MarketRequest = {
  id: string;
  requester: string;
  need: string;
  budget: number | string | bigint;
  tags: string[];
  status: "open" | "answered" | "settled" | "cancelled";
  created_ts: number;
  accepted_offer_id?: string | null;
};

export type Offer = {
  id: string;
  request_id: string;
  responder: string;
  recipe_uri: string;
  recipe_hash: string;
  price: number | string | bigint;
  status: "open" | "accepted" | "paid" | "rejected";
  created_ts: number;
};

export type DemoMarket = {
  wallets: {
    buyer: { address: string; balance: string };
    seller: { address: string; balance: string };
  };
  requests: MarketRequest[];
  offers: Offer[];
  listings: Listing[];
  ratings: Array<{ offer_id: string; rater: string; ratee: string; score: number; created_ts: number }>;
  loadedHashes: string[];
};

export type RunResult = {
  ok: boolean;
  message: string;
  steps: Array<{
    index: number;
    primitive: string;
    params: Record<string, unknown>;
    ok: boolean;
    detail: string;
  }>;
  calls: Array<{ primitive: string; args: Record<string, unknown> }>;
};

export type Activity = {
  id: string;
  mode: NetworkMode;
  title: string;
  detail: string;
  status: "pending" | "confirmed" | "failed" | "local";
  createdAt: number;
  hash?: `0x${string}`;
  chainId?: number;
};
