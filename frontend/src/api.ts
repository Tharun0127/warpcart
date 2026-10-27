// Typed wrappers around the Warpcart API. Every call goes through /api,
// which the dev server or nginx forwards to FastAPI.

export type Category = { id: number; name: string; slug: string };

export type ProductSummary = {
  id: number;
  sku: string;
  name: string;
  brand: string;
  price: string; // money arrives as a string, e.g. "19.99"
  stock: number;
  rating: string;
  category_slug: string;
  category_name: string;
};

export type ProductDetail = ProductSummary & {
  description: string;
  created_at: string;
  updated_at: string;
};

export type SearchPage = {
  items: ProductSummary[];
  page: number;
  page_size: number;
  has_more: boolean;
};

export type SearchFilters = {
  q: string;
  category: string;
  minPrice: string;
  maxPrice: string;
};

export type EndpointMetrics = {
  endpoint: string;
  requests: number;
  hits: number;
  misses: number;
  bypassed: number;
  degraded: number;
  hit_ratio: number | null;
  avg_latency_ms: number | null;
};

export type CacheMetrics = {
  cache_enabled: boolean;
  stampede_strategy: string;
  redis_available: boolean;
  endpoints: EndpointMetrics[];
};

// The X-Cache header travels with the data so the UI can show HIT/MISS.
export type WithCacheStatus<T> = { data: T; cacheStatus: string | null };

export class NotFoundError extends Error {}

async function getJson<T>(path: string): Promise<WithCacheStatus<T>> {
  const response = await fetch(`/api${path}`);
  if (response.status === 404) throw new NotFoundError("not found");
  if (!response.ok) throw new Error(`request failed: ${response.status}`);
  return { data: (await response.json()) as T, cacheStatus: response.headers.get("X-Cache") };
}

export function fetchCategories() {
  return getJson<Category[]>("/categories");
}

export function fetchProduct(id: number) {
  return getJson<ProductDetail>(`/products/${id}`);
}

export function fetchSearchPage(filters: SearchFilters, page: number) {
  const params = new URLSearchParams({ page: String(page), page_size: "24" });
  if (filters.q.trim()) params.set("q", filters.q.trim());
  if (filters.category) params.set("category", filters.category);
  if (filters.minPrice) params.set("min_price", filters.minPrice);
  if (filters.maxPrice) params.set("max_price", filters.maxPrice);
  return getJson<SearchPage>(`/products?${params}`);
}

export function fetchCacheMetrics() {
  return getJson<CacheMetrics>("/metrics/cache");
}
