"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError, PLATFORM_META, type Platform } from "@/lib/api";
import ErrorBanner from "./ErrorBanner";

const MAX_TEXT = 100_000;
const MIN_TEXT = 200; // backend rejects articles shorter than this

export default function NewRunForm() {
  const router = useRouter();
  const [mode, setMode] = useState<"url" | "text">("url");
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [platforms, setPlatforms] = useState<Platform[]>(["linkedin", "x"]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = (p: Platform) =>
    setPlatforms((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]));

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (mode === "url") {
      try {
        const parsed = new URL(url.trim());
        if (!/^https?:$/.test(parsed.protocol)) throw new Error();
      } catch {
        return setError("Enter a full article URL starting with http:// or https://.");
      }
    } else if (text.trim().length < MIN_TEXT) {
      return setError(`Paste at least ${MIN_TEXT} characters of article text (you have ${text.trim().length}).`);
    }
    if (platforms.length === 0) return setError("Pick at least one platform.");

    setSubmitting(true);
    try {
      const body = mode === "url" ? { url: url.trim() } : { text: text.trim() };
      const { run_id } = await api.createRun({ ...body, platforms, auto_approve: false });
      router.push(`/runs/${run_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      setSubmitting(false);
    }
  }

  const tab = (value: "url" | "text", label: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={mode === value}
      onClick={() => setMode(value)}
      className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
        mode === value
          ? "bg-white text-stone-900 shadow-sm dark:bg-stone-800 dark:text-stone-100"
          : "text-stone-500 hover:text-stone-800 dark:text-stone-400 dark:hover:text-stone-200"
      }`}
    >
      {label}
    </button>
  );

  return (
    <form onSubmit={onSubmit} className="card space-y-5">
      <div role="tablist" className="inline-flex gap-1 rounded-lg bg-stone-100 p-1 dark:bg-stone-950">
        {tab("url", "Article URL")}
        {tab("text", "Paste text")}
      </div>

      {mode === "url" ? (
        <div>
          <label htmlFor="url" className="mb-1.5 block text-sm font-medium">
            Link to the article
          </label>
          <input
            id="url"
            type="url"
            inputMode="url"
            className="input"
            placeholder="https://example.com/some-article"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            autoFocus
          />
          <p className="mt-1.5 text-xs text-stone-500">Works for server-rendered pages. For paywalled or JavaScript-only pages, paste the text instead.</p>
        </div>
      ) : (
        <div>
          <label htmlFor="text" className="mb-1.5 block text-sm font-medium">
            Article text
          </label>
          <textarea
            id="text"
            className="input min-h-56 resize-y"
            placeholder="Paste the full article here…"
            value={text}
            maxLength={MAX_TEXT}
            onChange={(e) => setText(e.target.value)}
          />
          <p className="mt-1.5 text-xs text-stone-500">
            {text.length.toLocaleString()} / {MAX_TEXT.toLocaleString()} characters
          </p>
        </div>
      )}

      <fieldset>
        <legend className="mb-1.5 text-sm font-medium">Platforms</legend>
        <div className="flex flex-wrap gap-3">
          {(Object.keys(PLATFORM_META) as Platform[]).map((p) => (
            <label
              key={p}
              className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm transition ${
                platforms.includes(p)
                  ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950/40"
                  : "border-stone-300 dark:border-stone-700"
              }`}
            >
              <input type="checkbox" className="accent-indigo-600" checked={platforms.includes(p)} onChange={() => toggle(p)} />
              {PLATFORM_META[p].name}
              <span className="text-xs text-stone-500">{PLATFORM_META[p].limit} chars</span>
            </label>
          ))}
        </div>
      </fieldset>

      {error && <ErrorBanner message={error} />}

      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" className="btn-primary" disabled={submitting}>
          {submitting && <span className="spinner !border-white !border-t-transparent" />}
          {submitting ? "Starting…" : "Generate posts"}
        </button>
        <span className="text-xs text-stone-500">Nothing is scheduled until you approve it.</span>
      </div>
    </form>
  );
}
