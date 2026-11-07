import type { Plan } from "@/lib/api";

export default function PlanCard({ plan, title, truncated }: { plan: Plan; title: string | null; truncated: boolean | null }) {
  return (
    <section className="card">
      <h2 className="card-title">Plan</h2>
      {title && <p className="mb-3 text-lg font-semibold leading-snug">{title}</p>}
      {truncated && (
        <p className="mb-3 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
          The article was long, so only the first part was used.
        </p>
      )}
      <dl className="grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs font-medium uppercase text-stone-500">Angle</dt>
          <dd className="mt-0.5">{plan.angle ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium uppercase text-stone-500">Audience</dt>
          <dd className="mt-0.5">{plan.audience ?? "—"}</dd>
        </div>
      </dl>
      {plan.key_points && plan.key_points.length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-medium uppercase text-stone-500">Key points</p>
          <ul className="mt-2 space-y-2.5">
            {plan.key_points.map((kp, i) => (
              <li key={i} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm">
                <span className="text-stone-400">{i + 1}.</span>
                <span className="min-w-0 flex-1 basis-60">{kp.point}</span>
                {kp.chunk_ids.length > 0 && (
                  <span className="badge bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-300">
                    source chunks: {kp.chunk_ids.join(", ")}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
