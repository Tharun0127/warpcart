import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { fetchCategories, fetchSearchPage, type SearchFilters } from "../api";
import { useDebounce } from "../useDebounce";
import CacheBadge from "../CacheBadge";

const EMPTY_FILTERS: SearchFilters = { q: "", category: "", minPrice: "", maxPrice: "" };

export default function SearchPage() {
  const [filters, setFilters] = useState<SearchFilters>(EMPTY_FILTERS);
  // Debounce the whole filter object: typing in any box waits 300 ms.
  const debounced = useDebounce(filters, 300);

  const categories = useQuery({ queryKey: ["categories"], queryFn: fetchCategories });

  const search = useInfiniteQuery({
    queryKey: ["search", debounced],
    queryFn: ({ pageParam }) => fetchSearchPage(debounced, pageParam),
    initialPageParam: 1,
    getNextPageParam: (last) => (last.data.has_more ? last.data.page + 1 : undefined),
  });

  const sentinel = useInfiniteScroll(() => {
    if (search.hasNextPage && !search.isFetchingNextPage) search.fetchNextPage();
  });

  const pages = search.data?.pages ?? [];
  const products = pages.flatMap((p) => p.data.items);
  const lastStatus = pages.at(-1)?.cacheStatus ?? null;

  function update(field: keyof SearchFilters, value: string) {
    setFilters((current) => ({ ...current, [field]: value }));
  }

  return (
    <div className="space-y-6">
      <section className="grid gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm md:grid-cols-[2fr_1fr_1fr_1fr]">
        <input
          className="rounded-md border border-slate-300 px-3 py-2 focus:border-indigo-500 focus:outline-none"
          placeholder="Search products, e.g. wireless, lamp, tent"
          value={filters.q}
          onChange={(e) => update("q", e.target.value)}
        />
        <select
          className="rounded-md border border-slate-300 px-3 py-2"
          value={filters.category}
          onChange={(e) => update("category", e.target.value)}
        >
          <option value="">All categories</option>
          {categories.data?.data.map((c) => (
            <option key={c.slug} value={c.slug}>
              {c.name}
            </option>
          ))}
        </select>
        <input
          className="rounded-md border border-slate-300 px-3 py-2"
          type="number"
          min={0}
          placeholder="Min price"
          value={filters.minPrice}
          onChange={(e) => update("minPrice", e.target.value)}
        />
        <input
          className="rounded-md border border-slate-300 px-3 py-2"
          type="number"
          min={0}
          placeholder="Max price"
          value={filters.maxPrice}
          onChange={(e) => update("maxPrice", e.target.value)}
        />
      </section>

      <div className="flex items-center justify-between text-sm text-slate-500">
        <span>
          {search.isPending ? "Searching..." : `${products.length} products loaded`}
          {search.hasNextPage ? " (scroll for more)" : ""}
        </span>
        <CacheBadge status={lastStatus} />
      </div>

      {search.isError && <p className="text-rose-600">Search failed. Check that the API is running.</p>}

      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {products.map((p) => (
          <li key={p.id}>
            <Link
              to={`/products/${p.id}`}
              className="block h-full rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-indigo-400 hover:shadow"
            >
              <p className="text-xs uppercase tracking-wide text-slate-500">{p.category_name}</p>
              <p className="mt-1 font-semibold leading-snug">{p.name}</p>
              <p className="text-sm text-slate-500">{p.brand}</p>
              <div className="mt-3 flex items-center justify-between">
                <span className="text-lg font-bold">${p.price}</span>
                <span className="text-sm text-slate-500">
                  ★ {p.rating} · {p.stock > 0 ? `${p.stock} in stock` : "out of stock"}
                </span>
              </div>
            </Link>
          </li>
        ))}
      </ul>

      {!search.isPending && products.length === 0 && (
        <p className="py-12 text-center text-slate-500">No products match these filters.</p>
      )}
      <div ref={sentinel} className="h-10" />
      {search.isFetchingNextPage && <p className="text-center text-sm text-slate-500">Loading more...</p>}
    </div>
  );
}

// Calls onVisible whenever the returned element scrolls into view.
function useInfiniteScroll(onVisible: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  const callback = useRef(onVisible);
  callback.current = onVisible;

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    // rootMargin starts loading a little before the user hits the bottom.
    const observer = new IntersectionObserver((entries) => entries[0].isIntersecting && callback.current(), {
      rootMargin: "400px",
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return ref;
}
