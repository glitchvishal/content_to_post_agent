import { PLATFORM_META, type ScheduledPost } from "@/lib/api";
import { formatLocal, formatUtc } from "@/lib/format";

export default function ScheduledList({ items }: { items: ScheduledPost[] }) {
  return (
    <section className="card border-emerald-300 dark:border-emerald-900">
      <h2 className="card-title">Scheduled</h2>
      <ul className="space-y-4">
        {items.map((s, i) => (
          <li key={s.id ?? i} className="text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">{PLATFORM_META[s.platform]?.name ?? s.platform}</span>
              <span className="badge bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">{s.status}</span>
            </div>
            <p className="mt-1 text-stone-600 dark:text-stone-300">
              {formatUtc(s.scheduled_at_utc)} <span className="text-stone-400">·</span> {formatLocal(s.scheduled_at_utc)}
            </p>
            <p className="mt-1.5 line-clamp-3 whitespace-pre-wrap break-words text-xs text-stone-500">{s.text}</p>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-xs text-stone-500">Scheduling is a mock: entries are written to the backend&apos;s data/scheduled_posts.json.</p>
    </section>
  );
}
