import { useQuery } from "@tanstack/react-query";
import { fetchCacheMetrics, type EndpointMetrics } from "../api";

const LABELS: Record<string, string> = {
  product_detail: "GET /products/{id}",
  search: "GET /products?…",
  categories: "GET /categories",
};

function percent(ratio: number | null) {
  return ratio === null ? "—" : `${(ratio * 100).toFixed(1)}%`;
}

export default function MetricsPage() {
  // Poll every 2s so you can watch the numbers move during a load test.
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: fetchCacheMetrics, refetchInterval: 2000 });

  if (metrics.isPending) return <p className="text-slate-500">Loading...</p>;
  if (metrics.isError) return <p className="text-rose-600">Could not load metrics.</p>;

  const m = metrics.data.data;
  const totals = m.endpoints.reduce(
    (sum, e) => ({ hits: sum.hits + e.hits, misses: sum.misses + e.misses, requests: sum.requests + e.requests }),
    { hits: 0, misses: 0, requests: 0 },
  );
  const overallRatio = totals.hits + totals.misses ? totals.hits / (totals.hits + totals.misses) : null;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Cache metrics</h1>

      <div className="grid gap-4 sm:grid-cols-4">
        <Stat label="Cache" value={m.cache_enabled ? "Enabled" : "Disabled"} />
        <Stat label="Redis" value={m.redis_available ? "Up" : "Down"} warn={!m.redis_available} />
        <Stat label="Stampede strategy" value={m.stampede_strategy} />
        <Stat label="Overall hit ratio" value={percent(overallRatio)} />
      </div>

      {!m.redis_available && (
        <p className="rounded-md bg-rose-50 p-3 text-sm text-rose-700">
          Redis is unreachable. The API is serving everything from Postgres (X-Cache: DEGRADED). Counters are
          stored in Redis, so they are unavailable until it is back.
        </p>
      )}

      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-100 text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-3">Endpoint</th>
              <th className="px-4 py-3 text-right">Requests</th>
              <th className="px-4 py-3 text-right">Hits</th>
              <th className="px-4 py-3 text-right">Misses</th>
              <th className="px-4 py-3 text-right">Bypassed</th>
              <th className="px-4 py-3 text-right">Degraded</th>
              <th className="px-4 py-3">Hit ratio</th>
              <th className="px-4 py-3 text-right">Avg latency</th>
            </tr>
          </thead>
          <tbody>
            {m.endpoints.map((e) => (
              <Row key={e.endpoint} e={e} />
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-sm text-slate-500">
        Counters live in Redis hashes shared by all API workers. Latency is measured inside the API (cache lookup
        plus database on a miss), not including network time to your browser.
      </p>
    </div>
  );
}

function Row({ e }: { e: EndpointMetrics }) {
  return (
    <tr className="border-t border-slate-100">
      <td className="px-4 py-3 font-mono text-xs">{LABELS[e.endpoint] ?? e.endpoint}</td>
      <td className="px-4 py-3 text-right tabular-nums">{e.requests.toLocaleString()}</td>
      <td className="px-4 py-3 text-right tabular-nums text-emerald-700">{e.hits.toLocaleString()}</td>
      <td className="px-4 py-3 text-right tabular-nums text-amber-700">{e.misses.toLocaleString()}</td>
      <td className="px-4 py-3 text-right tabular-nums">{e.bypassed.toLocaleString()}</td>
      <td className="px-4 py-3 text-right tabular-nums">{e.degraded.toLocaleString()}</td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="h-2 w-24 overflow-hidden rounded bg-slate-200">
            <div className="h-full bg-emerald-500" style={{ width: `${(e.hit_ratio ?? 0) * 100}%` }} />
          </div>
          <span className="tabular-nums">{percent(e.hit_ratio)}</span>
        </div>
      </td>
      <td className="px-4 py-3 text-right tabular-nums">
        {e.avg_latency_ms === null ? "—" : `${e.avg_latency_ms.toFixed(2)} ms`}
      </td>
    </tr>
  );
}

function Stat({ label, value, warn = false }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-1 text-xl font-semibold ${warn ? "text-rose-600" : ""}`}>{value}</p>
    </div>
  );
}
