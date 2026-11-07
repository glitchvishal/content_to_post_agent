"use client";

import { useState } from "react";
import { PLATFORM_META, type Critique, type Platform } from "@/lib/api";

export function scoreClasses(score: number): string {
  if (score >= 8) return "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300";
  if (score === 7) return "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300";
  return "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300";
}

function Score({ label, value }: { label: string; value: number }) {
  return (
    <span className={`badge ${scoreClasses(value)}`} title={`${label}: ${value}/10`}>
      {label} {value}
    </span>
  );
}

interface Props {
  platform: Platform;
  text: string;
  critique?: Critique;
  editing: boolean;
  draft: string;
  onDraftChange: (value: string) => void;
}

export default function PostCard({ platform, text, critique, editing, draft, onDraftChange }: Props) {
  const [showFeedback, setShowFeedback] = useState(false);
  const [copied, setCopied] = useState(false);
  const { name, limit } = PLATFORM_META[platform];
  const shown = editing ? draft : text;
  const chars = shown.length;
  const over = chars > limit;

  async function copy() {
    try {
      await navigator.clipboard.writeText(shown);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable (e.g. insecure context); ignore */
    }
  }

  return (
    <article className="card flex flex-col">
      <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">{name}</h3>
        <div className="flex items-center gap-2">
          {critique && (
            <span
              className={`badge ${
                critique.passed
                  ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
                  : "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300"
              }`}
            >
              {critique.passed ? "passed" : "below the bar"}
            </span>
          )}
          <button type="button" onClick={copy} className="text-xs text-stone-500 hover:text-stone-900 dark:hover:text-stone-100">
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </header>

      {editing ? (
        <textarea
          aria-label={`${name} post`}
          className={`input min-h-48 resize-y leading-relaxed ${over ? "!border-red-500 !ring-red-500/30" : ""}`}
          value={draft}
          onChange={(e) => onDraftChange(e.target.value)}
        />
      ) : (
        <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">{text}</p>
      )}

      <p className={`mt-2 text-xs ${over ? "font-semibold text-red-600 dark:text-red-400" : "text-stone-500"}`}>
        {chars.toLocaleString()} / {limit.toLocaleString()} characters{over ? ` · ${chars - limit} over the limit` : ""}
      </p>

      {critique && (
        <div className="mt-4 border-t border-stone-200 pt-3 dark:border-stone-800">
          <div className="flex flex-wrap gap-2">
            <Score label="faithfulness" value={critique.faithfulness} />
            <Score label="platform fit" value={critique.platform_fit} />
            <Score label="hook" value={critique.hook} />
          </div>

          {critique.unsupported_claims.length > 0 && (
            <div className="mt-3 rounded-md bg-red-50 p-3 text-xs text-red-900 dark:bg-red-950/40 dark:text-red-200">
              <p className="font-semibold">Claims the source does not support</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                {critique.unsupported_claims.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </div>
          )}

          <button
            type="button"
            className="mt-3 text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
            aria-expanded={showFeedback}
            onClick={() => setShowFeedback((v) => !v)}
          >
            {showFeedback ? "Hide" : "Show"} judge feedback
          </button>
          {showFeedback && <p className="mt-1.5 text-sm text-stone-600 dark:text-stone-300">{critique.feedback || "No feedback."}</p>}
        </div>
      )}
    </article>
  );
}
