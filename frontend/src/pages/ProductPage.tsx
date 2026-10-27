import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchProduct, NotFoundError } from "../api";
import CacheBadge from "../CacheBadge";

export default function ProductPage() {
  const id = Number(useParams().id);
  const product = useQuery({ queryKey: ["product", id], queryFn: () => fetchProduct(id) });

  if (product.isPending) return <p className="text-slate-500">Loading...</p>;
  if (product.isError) {
    const missing = product.error instanceof NotFoundError;
    return (
      <div className="space-y-3">
        <p className="text-rose-600">{missing ? "Product not found." : "Could not load the product."}</p>
        <Link to="/" className="text-indigo-600 hover:underline">
          ← Back to search
        </Link>
      </div>
    );
  }

  const { data: p, cacheStatus } = product.data;
  return (
    <div className="space-y-4">
      <Link to="/" className="text-sm text-indigo-600 hover:underline">
        ← Back to search
      </Link>
      <article className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-500">{p.category_name}</p>
            <h1 className="mt-1 text-2xl font-bold">{p.name}</h1>
            <p className="text-slate-500">
              {p.brand} · SKU {p.sku}
            </p>
          </div>
          <CacheBadge status={cacheStatus} />
        </div>
        <p className="mt-4 text-3xl font-bold">${p.price}</p>
        <p className="mt-1 text-sm text-slate-600">
          ★ {p.rating} · {p.stock > 0 ? `${p.stock} in stock` : "Out of stock"}
        </p>
        <p className="mt-6 leading-relaxed text-slate-700">{p.description}</p>
        <p className="mt-6 text-xs text-slate-400">Last updated {new Date(p.updated_at).toLocaleString()}</p>
      </article>
      <p className="text-sm text-slate-500">
        Reload this page: the first view is a cache MISS (read from Postgres), later views are a HIT (served
        from Redis) until the TTL expires or an admin updates the product.
      </p>
    </div>
  );
}
