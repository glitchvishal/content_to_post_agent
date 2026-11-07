import type { Step, StepState } from "@/lib/timeline";

function Icon({ state }: { state: StepState }) {
  const base = "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold";
  switch (state) {
    case "done":
      return <span className={`${base} bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300`}>✓</span>;
    case "active":
      return (
        <span className={`${base} bg-indigo-100 dark:bg-indigo-950`} aria-label="in progress">
          <span className="spinner" />
        </span>
      );
    case "waiting":
      return <span className={`${base} animate-pulse bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300`}>●</span>;
    case "failed":
      return <span className={`${base} bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300`}>!</span>;
    case "skipped":
      return <span className={`${base} bg-stone-100 text-stone-400 dark:bg-stone-800`}>–</span>;
    default:
      return <span className={`${base} border border-stone-300 text-transparent dark:border-stone-700`}>○</span>;
  }
}

export default function Timeline({ steps, transport }: { steps: Step[]; transport: "sse" | "polling" | "idle" }) {
  return (
    <section className="card" aria-label="Progress">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="card-title !mb-0">Progress</h2>
        {transport !== "idle" && (
          <span className="text-xs text-stone-500">{transport === "sse" ? "live" : "polling every 2s"}</span>
        )}
      </div>
      <ol className="space-y-3">
        {steps.map((s) => (
          <li key={s.key} className="flex items-start gap-3">
            <Icon state={s.state} />
            <div className="min-w-0 flex-1">
              <p
                className={`text-sm font-medium ${
                  s.state === "pending" || s.state === "skipped" ? "text-stone-400 dark:text-stone-500" : ""
                } ${s.state === "failed" ? "text-red-700 dark:text-red-300" : ""}`}
              >
                {s.label}
                {s.elapsed !== undefined && <span className="ml-2 text-xs font-normal text-stone-500">{s.elapsed.toFixed(1)}s</span>}
              </p>
              {s.detail && <p className="break-words text-xs text-stone-500 dark:text-stone-400">{s.detail}</p>}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
