import type { RunEvent, RunView } from "./api";

export type StepState = "done" | "active" | "waiting" | "pending" | "failed" | "skipped";

export interface Step {
  key: string;
  label: string;
  state: StepState;
  detail?: string;
  elapsed?: number;
}

interface DoneNode {
  node: string;
  detail?: string;
  elapsed?: number;
}

const CANONICAL = ["fetch_and_chunk", "plan", "write", "critique", "human_review", "schedule"] as const;

const LABELS: Record<string, string> = {
  fetch_and_chunk: "Fetch & chunk",
  plan: "Plan",
  write: "Write",
  critique: "Critique",
  human_review: "Human review",
  schedule: "Schedule",
};

function describe(node: string, d: RunEvent["data"]): string | undefined {
  switch (node) {
    case "fetch_and_chunk":
      return `${d.chunks ?? "?"} chunks${d.truncated ? " · source truncated" : ""}`;
    case "plan": {
      const platforms = Array.isArray(d.platforms) ? (d.platforms as string[]).join(", ") : "";
      return `${d.key_points ?? "?"} key points${platforms ? ` · ${platforms}` : ""}`;
    }
    case "write":
      return Array.isArray(d.written) ? `wrote ${(d.written as string[]).join(", ")}` : undefined;
    case "critique": {
      const scores = (d.scores ?? {}) as Record<string, { faithfulness: number; platform_fit: number; hook: number; passed: boolean }>;
      return Object.entries(scores)
        .map(([p, s]) => `${p}: F${s.faithfulness} P${s.platform_fit} H${s.hook} ${s.passed ? "pass" : "fail"}`)
        .join(" · ");
    }
    case "human_review":
      return d.decision ? String(d.decision) : undefined;
    case "schedule":
      return Array.isArray(d.scheduled) ? `${d.scheduled.length} scheduled` : undefined;
  }
}

/** Nodes that have finished, from SSE events (rich) or, when SSE is unavailable, reconstructed from the run view. */
function finishedNodes(run: RunView, events: RunEvent[]): DoneNode[] {
  const fromEvents = events
    .filter((e) => e.event === "node" && e.data.node)
    .map((e) => ({ node: e.data.node as string, detail: describe(e.data.node as string, e.data), elapsed: e.data.elapsed_s }));
  if (fromEvents.length > 0) return fromEvents;

  const nodes: DoneNode[] = [];
  if (run.title || run.plan) nodes.push({ node: "fetch_and_chunk" });
  if (run.plan) nodes.push({ node: "plan" });
  if (run.posts) {
    nodes.push({ node: "write" });
    if (run.critique) nodes.push({ node: "critique" });
    for (let i = 0; i < run.revisions; i++) nodes.push({ node: "write" }, { node: "critique" });
  }
  if (run.review) nodes.push({ node: "human_review", detail: run.review.decision });
  if (run.scheduled?.length) nodes.push({ node: "schedule", detail: `${run.scheduled.length} scheduled` });
  return nodes;
}

/** Build the progress timeline: finished steps, the current one, and the steps still ahead. */
export function buildSteps(run: RunView, events: RunEvent[]): Step[] {
  const done = finishedNodes(run, events);
  const steps: Step[] = [];
  let writes = 0;

  done.forEach((d, i) => {
    let label = LABELS[d.node] ?? d.node;
    if (d.node === "write") {
      writes += 1;
      if (writes > 1) label = `Rewrite #${writes - 1}`;
    }
    if (d.node === "critique" && writes > 1) label = "Re-check";
    steps.push({ key: `${d.node}-${i}`, label, state: "done", detail: d.detail, elapsed: d.elapsed });
  });

  const lastNode = done.length ? done[done.length - 1].node : null;
  const lastIdx = lastNode ? CANONICAL.indexOf(lastNode as (typeof CANONICAL)[number]) : -1;
  const seen = new Set(done.map((d) => d.node));
  const remaining = CANONICAL.slice(lastIdx + 1);

  if (run.status === "failed") {
    const failedNode = run.error?.node ?? remaining[0];
    steps.push({
      key: "failed",
      label: failedNode ? (LABELS[failedNode] ?? failedNode) : "Run",
      state: "failed",
      detail: run.error?.message,
    });
    return steps;
  }

  if (run.status === "rejected") {
    if (!seen.has("human_review")) steps.push({ key: "human_review-done", label: "Human review", state: "done", detail: "reject" });
    steps.push({ key: "schedule-skipped", label: "Schedule", state: "skipped", detail: "nothing scheduled" });
    return steps;
  }

  if (run.status === "completed") return steps;

  // After a critique pass, a running graph is rewriting (the human-review pause shows as awaiting_review).
  if (run.status === "running" && lastNode === "critique") {
    steps.push({ key: "rewrite-active", label: `Rewrite #${writes}`, state: "active", detail: "fixing posts that failed the checks" });
    steps.push({ key: "recheck-pending", label: "Re-check", state: "pending" });
    steps.push({ key: "human_review-pending", label: "Human review", state: "pending" });
    steps.push({ key: "schedule-pending", label: "Schedule", state: "pending" });
    return steps;
  }

  remaining.forEach((node, i) => {
    let state: StepState = "pending";
    if (i === 0) state = run.status === "awaiting_review" && node === "human_review" ? "waiting" : "active";
    if (node === "human_review" && run.status === "awaiting_review") state = "waiting";
    const detail = state === "waiting" ? "waiting for your decision" : undefined;
    steps.push({ key: `${node}-${state}`, label: LABELS[node], state, detail });
  });
  return steps;
}
