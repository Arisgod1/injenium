import type {
  CatalogItem,
  DemoMarket,
  Inspection,
  RecipeSource,
  RunResult,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  const raw = await response.text();
  let payload: unknown;
  try {
    payload = raw ? JSON.parse(raw) : null;
  } catch {
    payload = raw;
  }
  if (!response.ok) {
    const detail = payload && typeof payload === "object" && "detail" in payload ? payload.detail : payload;
    const message =
      typeof detail === "string"
        ? detail
        : detail && typeof detail === "object" && "message" in detail
          ? String(detail.message)
          : `Companion 请求失败（HTTP ${response.status}）`;
    throw new ApiError(message, response.status, detail);
  }
  return payload as T;
}

export const api = {
  status: () => request<{ ipfsPublish: boolean; signingCapability: boolean }>("/api/v1/status"),
  catalog: () => request<CatalogItem[]>("/api/v1/catalog"),
  inspect: (source: RecipeSource, expectedHash?: string) =>
    request<Inspection>("/api/v1/recipes/inspect", {
      method: "POST",
      body: JSON.stringify({ source, expectedHash }),
    }),
  load: (source: RecipeSource, expectedHash?: string) =>
    request<Inspection>("/api/v1/demo/load", {
      method: "POST",
      body: JSON.stringify({ source, expectedHash }),
    }),
  publish: (recipeHash: string) =>
    request<{ uri: string; hash: string }>("/api/v1/recipes/publish", {
      method: "POST",
      body: JSON.stringify({ recipeHash }),
    }),
  run: (hash: string) => request<RunResult>(`/api/v1/demo/run/${hash}`, { method: "POST" }),
  market: () => request<DemoMarket>("/api/v1/demo/market"),
  reset: () => request<DemoMarket>("/api/v1/demo/reset", { method: "POST" }),
  createRequest: (need: string, budget: string, tags: string[]) =>
    request<{ id: string; market: DemoMarket }>("/api/v1/demo/requests", {
      method: "POST",
      body: JSON.stringify({ need, budget, tags }),
    }),
  createOffer: (requestId: string, recipeHash: string) =>
    request<{ id: string; market: DemoMarket }>(`/api/v1/demo/requests/${requestId}/offers`, {
      method: "POST",
      body: JSON.stringify({ recipeHash }),
    }),
  acceptRun: (offerId: string) =>
    request<{ run: RunResult; market: DemoMarket }>(`/api/v1/demo/offers/${offerId}/accept-run`, { method: "POST" }),
  release: (offerId: string) =>
    request<{ tx: string; market: DemoMarket }>(`/api/v1/demo/offers/${offerId}/release`, { method: "POST" }),
  rate: (offerId: string, score: number) =>
    request<{ tx: string; market: DemoMarket }>(`/api/v1/demo/offers/${offerId}/rate`, {
      method: "POST",
      body: JSON.stringify({ score }),
    }),
  cancelRequest: (requestId: string) =>
    request<{ tx: string; market: DemoMarket }>(`/api/v1/demo/requests/${requestId}/cancel`, { method: "POST" }),
  createListing: (description: string, price: string, tags: string[], recipeHash: string) =>
    request<{ id: string; market: DemoMarket }>("/api/v1/demo/listings", {
      method: "POST",
      body: JSON.stringify({ description, price, tags, recipeHash }),
    }),
  buyRun: (listingId: string) =>
    request<{ tx: string; run: RunResult; market: DemoMarket }>(`/api/v1/demo/listings/${listingId}/buy-run`, { method: "POST" }),
  delist: (listingId: string) =>
    request<{ tx: string; market: DemoMarket }>(`/api/v1/demo/listings/${listingId}`, { method: "DELETE" }),
};
