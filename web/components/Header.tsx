"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { API_URL, api } from "@/lib/api";

const GITHUB_URL = process.env.NEXT_PUBLIC_GITHUB_URL ?? "https://github.com/glitchvishal/content-to-post-agent";

type Health = { state: "loading" } | { state: "ok"; model: string } | { state: "down" };

export default function Header() {
  const [health, setHealth] = useState<Health>({ state: "loading" });

  useEffect(() => {
    let cancelled = false;
    api
      .health()
      .then((h) => !cancelled && setHealth({ state: "ok", model: h.model }))
      .catch(() => !cancelled && setHealth({ state: "down" }));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <header className="border-b border-stone-200 bg-white/80 backdrop-blur dark:border-stone-800 dark:bg-stone-950/80">
      <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
        <Link href="/" className="font-semibold tracking-tight">
          Content-to-Post <span className="text-indigo-600 dark:text-indigo-400">Agent</span>
        </Link>
        <nav className="flex items-center gap-4 text-sm text-stone-600 dark:text-stone-400">
          <span
            className="flex items-center gap-1.5"
            title={health.state === "down" ? `Cannot reach ${API_URL}` : API_URL}
            aria-live="polite"
          >
            <span
              className={`h-2 w-2 rounded-full ${
                health.state === "ok" ? "bg-emerald-500" : health.state === "down" ? "bg-red-500" : "bg-stone-400"
              }`}
            />
            {health.state === "ok" ? `API · ${health.model}` : health.state === "down" ? "API offline" : "API…"}
          </span>
          <a href={`${API_URL}/docs`} target="_blank" rel="noreferrer" className="hover:text-stone-900 dark:hover:text-stone-100">
            API docs
          </a>
          <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="hover:text-stone-900 dark:hover:text-stone-100">
            GitHub
          </a>
        </nav>
      </div>
    </header>
  );
}
