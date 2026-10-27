const COLORS: Record<string, string> = {
  HIT: "bg-emerald-100 text-emerald-800",
  MISS: "bg-amber-100 text-amber-800",
  BYPASS: "bg-slate-200 text-slate-700",
  DEGRADED: "bg-rose-100 text-rose-800",
};

// Shows the server's X-Cache header for the request that produced the data.
export default function CacheBadge({ status }: { status: string | null }) {
  if (!status) return null;
  return (
    <span className={`rounded px-2 py-0.5 font-mono text-xs font-semibold ${COLORS[status] ?? COLORS.BYPASS}`}>
      cache {status}
    </span>
  );
}
