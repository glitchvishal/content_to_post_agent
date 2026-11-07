import type { Usage } from "@/lib/api";
import { formatInr, formatNumber, formatUsd } from "@/lib/format";

export default function UsageCard({ usage, revisions }: { usage: Usage; revisions: number }) {
  const items: [string, string, string?][] = [
    ["Rewrites", String(revisions)],
    ["LLM calls", formatNumber(usage.llm_calls)],
    ["Tokens", `${formatNumber(usage.input_tokens)} in / ${formatNumber(usage.output_tokens)} out`],
    ["Cost", formatUsd(usage.cost_usd), formatInr(usage.cost_usd)],
  ];
  return (
    <section className="card">
      <h2 className="card-title">Revisions &amp; usage</h2>
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {items.map(([label, value, sub]) => (
          <div key={label}>
            <dt className="text-xs text-stone-500">{label}</dt>
            <dd className="mt-0.5 text-sm font-semibold">{value}</dd>
            {sub && <dd className="text-xs text-stone-500">{sub}</dd>}
          </div>
        ))}
      </dl>
    </section>
  );
}
