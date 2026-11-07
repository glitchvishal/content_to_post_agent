"use client";

import { useState } from "react";
import { ApiError, PLATFORM_META, type Platform, type ReviewRequest } from "@/lib/api";
import { toLocalInputValue } from "@/lib/format";
import ErrorBanner from "./ErrorBanner";

interface Props {
  posts: Partial<Record<Platform, string>>;
  editing: boolean;
  drafts: Partial<Record<Platform, string>>;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSubmit: (body: ReviewRequest) => Promise<unknown>;
}

export default function ReviewPanel({ posts, editing, drafts, onStartEdit, onCancelEdit, onSubmit }: Props) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [scheduleAt, setScheduleAt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const platforms = Object.keys(posts) as Platform[];
  const changed = platforms.filter((p) => (drafts[p] ?? posts[p]) !== posts[p]);
  const problems = platforms.flatMap((p) => {
    const text = (drafts[p] ?? posts[p] ?? "").trim();
    if (!text) return [`The ${PLATFORM_META[p].name} post is empty.`];
    if (text.length > PLATFORM_META[p].limit) return [`The ${PLATFORM_META[p].name} post is over its ${PLATFORM_META[p].limit}-character limit.`];
    return [];
  });

  async function send(body: ReviewRequest) {
    setError(null);
    if (scheduleAt) {
      const when = new Date(scheduleAt); // datetime-local is local time; toISOString() converts it to UTC
      if (Number.isNaN(when.getTime()) || when.getTime() <= Date.now()) {
        return setError("Pick a schedule time in the future, or leave it empty to use the default delay.");
      }
      if (body.decision !== "reject") body.schedule_at = when.toISOString();
    }
    setBusy(true);
    try {
      await onSubmit(body);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not send your decision.");
    } finally {
      setBusy(false);
    }
  }

  const saveEdits = () => {
    const edited: Partial<Record<Platform, string>> = {};
    changed.forEach((p) => (edited[p] = (drafts[p] ?? "").trim()));
    return send({ decision: "edit", posts: edited });
  };

  return (
    <section className="card border-amber-300 dark:border-amber-800" aria-label="Review">
      <h2 className="card-title">Your review</h2>
      <p className="mb-4 text-sm text-stone-600 dark:text-stone-300">
        {editing
          ? "Edit the posts above, then save. Edits are checked against each platform's character limit."
          : "Nothing is scheduled yet. Approve the drafts as they are, edit them, or reject them."}
      </p>

      {!rejecting && (
        <div className="mb-4 max-w-xs">
          <label htmlFor="schedule_at" className="mb-1 block text-xs font-medium">
            Schedule at <span className="font-normal text-stone-500">(optional, your local time)</span>
          </label>
          <input
            id="schedule_at"
            type="datetime-local"
            className="input"
            min={toLocalInputValue(new Date())}
            value={scheduleAt}
            onChange={(e) => setScheduleAt(e.target.value)}
          />
          <p className="mt-1 text-xs text-stone-500">Empty = the backend default (about an hour from approval).</p>
        </div>
      )}

      {rejecting ? (
        <div className="space-y-3">
          <label htmlFor="reason" className="block text-sm font-medium">
            Why are you rejecting these posts?
          </label>
          <textarea
            id="reason"
            className="input min-h-24"
            placeholder="e.g. Off-brand tone, wrong angle…"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            autoFocus
          />
          <div className="flex flex-wrap gap-3">
            <button
              className="btn-danger"
              disabled={busy || !reason.trim()}
              onClick={() => send({ decision: "reject", reason: reason.trim() })}
            >
              {busy && <span className="spinner !border-white !border-t-transparent" />}
              Confirm reject
            </button>
            <button className="btn-secondary" disabled={busy} onClick={() => setRejecting(false)}>
              Back
            </button>
          </div>
        </div>
      ) : editing ? (
        <div className="space-y-3">
          {problems.length > 0 && (
            <ul className="list-disc pl-5 text-xs text-red-600 dark:text-red-400">
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
          <div className="flex flex-wrap gap-3">
            <button className="btn-primary" disabled={busy || problems.length > 0 || changed.length === 0} onClick={saveEdits}>
              {busy && <span className="spinner !border-white !border-t-transparent" />}
              Save edits &amp; schedule
            </button>
            <button className="btn-secondary" disabled={busy} onClick={onCancelEdit}>
              Cancel
            </button>
          </div>
          {changed.length === 0 && <p className="text-xs text-stone-500">Change at least one post to save an edit.</p>}
        </div>
      ) : (
        <div className="flex flex-wrap gap-3">
          <button className="btn-success" disabled={busy} onClick={() => send({ decision: "approve" })}>
            {busy && <span className="spinner !border-white !border-t-transparent" />}
            Approve &amp; schedule
          </button>
          <button className="btn-secondary" disabled={busy} onClick={onStartEdit}>
            Edit
          </button>
          <button className="btn-secondary !text-red-700 dark:!text-red-300" disabled={busy} onClick={() => setRejecting(true)}>
            Reject
          </button>
        </div>
      )}

      {error && (
        <div className="mt-4">
          <ErrorBanner message={error} />
        </div>
      )}
    </section>
  );
}
