"use client";

import Link from "next/link";
import { use, useMemo, useState } from "react";
import ErrorBanner from "@/components/ErrorBanner";
import PlanCard from "@/components/PlanCard";
import PostCard from "@/components/PostCard";
import ReviewPanel from "@/components/ReviewPanel";
import ScheduledList from "@/components/ScheduledList";
import Timeline from "@/components/Timeline";
import UsageCard from "@/components/UsageCard";
import { API_URL, isActive, type Platform, type RunStatus } from "@/lib/api";
import { buildSteps } from "@/lib/timeline";
import { useRun } from "@/lib/useRun";

const STATUS_STYLE: Record<RunStatus, string> = {
  queued: "bg-stone-200 text-stone-700 dark:bg-stone-800 dark:text-stone-300",
  running: "bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300",
  awaiting_review: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  completed: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  rejected: "bg-stone-200 text-stone-700 dark:bg-stone-800 dark:text-stone-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
};

export default function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { run, events, error, loading, transport, submitReview, refresh } = useRun(id);
  const [editing, setEditing] = useState(false);
  const [drafts, setDrafts] = useState<Partial<Record<Platform, string>>>({});

  const steps = useMemo(() => (run ? buildSteps(run, events) : []), [run, events]);

  if (loading && !run) {
    return (
      <div className="flex items-center gap-3 text-stone-500" role="status">
        <span className="spinner" /> Loading run…
      </div>
    );
  }

  if (!run) {
    const notFound = error?.status === 404;
    return (
      <div className="mx-auto max-w-xl space-y-4">
        <ErrorBanner
          title={notFound ? "Run not found" : "Could not load this run"}
          message={
            notFound
              ? "The backend does not know this run. Runs are kept in memory, so they disappear when the API restarts."
              : (error?.message ?? "Unknown error.")
          }
          onRetry={notFound ? undefined : refresh}
        />
        <Link href="/" className="btn-primary">
          Start a new run
        </Link>
      </div>
    );
  }

  const posts = run.posts ?? {};
  const platforms = (Object.keys(posts) as Platform[]).filter((p) => posts[p] !== undefined);
  const waiting = run.status === "awaiting_review";

  const startEdit = () => {
    setDrafts({ ...posts });
    setEditing(true);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Link href="/" className="text-sm text-stone-500 hover:underline">
            ← New run
          </Link>
          <h1 className="mt-1 break-words text-2xl font-semibold tracking-tight">{run.title ?? "Working on your posts…"}</h1>
          <p className="mt-1 break-all text-xs text-stone-500">
            {run.source.url ?? `Pasted text · ${run.source.text_chars.toLocaleString()} characters`}
          </p>
        </div>
        <span className={`badge px-3 py-1 text-sm ${STATUS_STYLE[run.status]}`}>{run.status.replace("_", " ")}</span>
      </div>

      {run.status === "failed" && (
        <ErrorBanner
          title="This run failed"
          message={run.error ? `${run.error.message}${run.error.node ? ` (step: ${run.error.node})` : ""}` : "Unknown error."}
        />
      )}
      {run.status === "rejected" && (
        <div className="card text-sm">
          <p className="font-medium">You rejected these posts. Nothing was scheduled.</p>
          {run.review?.reason && <p className="mt-1 text-stone-500">Reason: {run.review.reason}</p>}
        </div>
      )}
      {error && <ErrorBanner title="Connection problem" message={error.message} onRetry={refresh} />}

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="min-w-0 space-y-6 lg:order-1">
          {run.plan && <PlanCard plan={run.plan} title={run.title} truncated={run.source_truncated} />}

          {platforms.length > 0 ? (
            <div className="grid gap-6 md:grid-cols-2">
              {platforms.map((p) => (
                <PostCard
                  key={p}
                  platform={p}
                  text={posts[p] ?? ""}
                  critique={run.critique?.[p]}
                  editing={editing && waiting}
                  draft={drafts[p] ?? posts[p] ?? ""}
                  onDraftChange={(value) => setDrafts((d) => ({ ...d, [p]: value }))}
                />
              ))}
            </div>
          ) : (
            isActive(run.status) && (
              <div className="card flex items-center gap-3 text-sm text-stone-500" role="status">
                <span className="spinner" /> Drafts will appear here as soon as they are written.
              </div>
            )
          )}

          {waiting && platforms.length > 0 && (
            <ReviewPanel
              posts={posts}
              editing={editing}
              drafts={drafts}
              onStartEdit={startEdit}
              onCancelEdit={() => setEditing(false)}
              onSubmit={async (body) => {
                const view = await submitReview(body);
                setEditing(false);
                return view;
              }}
            />
          )}

          {run.status === "completed" && (run.scheduled?.length ?? 0) > 0 && <ScheduledList items={run.scheduled!} />}
          {run.status === "completed" && !run.scheduled?.length && (
            <div className="card text-sm text-stone-500">The run completed, but nothing was scheduled.</div>
          )}

          {(run.usage.llm_calls > 0 || run.revisions > 0) && <UsageCard usage={run.usage} revisions={run.revisions} />}
        </div>

        <aside className="space-y-6 lg:order-2">
          <Timeline steps={steps} transport={transport} />
          <p className="px-1 text-xs text-stone-500">
            Run <code className="break-all">{run.run_id}</code> ·{" "}
            <a className="underline" href={`${API_URL}/runs/${run.run_id}`} target="_blank" rel="noreferrer">
              raw JSON
            </a>
          </p>
        </aside>
      </div>
    </div>
  );
}
